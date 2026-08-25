from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from statistics import fmean
from typing import Any

from atlas.studies.evaluators import evaluate_rag_records
from atlas.studies.evidence_writer import RunDraft, sha256_file, utc_now, write_run_draft
from atlas.studies.runners.common import (
    artifact_manifest,
    cache_root,
    metric,
    process_sample,
    repository_root,
    stage_directory,
    summarize_requests,
)
from atlas.studies.runners.s003_lifecycle import IMAGE
from atlas.utilities.serialization import load_data

EXPERIMENT_CONFIGS = {
    "E0009": ("CFG015", "CFG016"),
    "E0010": ("CFG017", "CFG015", "CFG018"),
    "E0011": ("CFG015", "CFG019"),
    "E0012": ("CFG020", "CFG015"),
}
SEEDS = (101, 202, 303)
GENERATION_FILES = {
    "config.json": "smollm2-config.json",
    "generation_config.json": "smollm2-generation-config.json",
    "model.safetensors": "smollm2-model.safetensors",
    "special_tokens_map.json": "smollm2-special-tokens-map.json",
    "tokenizer.json": "smollm2-tokenizer.json",
    "tokenizer_config.json": "smollm2-tokenizer-config.json",
}
EMBEDDING_FILES = {
    "config.json": "minilm-config.json",
    "model.onnx": "minilm-model-fp32.onnx",
    "model-int8.onnx": "minilm-model-int8-arm64.onnx",
    "special_tokens_map.json": "minilm-special-tokens-map.json",
    "tokenizer.json": "minilm-tokenizer.json",
    "tokenizer_config.json": "minilm-tokenizer-config.json",
    "vocab.txt": "minilm-vocab.txt",
}


def run_id(experiment: str, configuration: str, replicate: int) -> str:
    experiment_number = int(experiment[-2:]) - 8
    configuration_number = int(configuration[-3:]) - 14
    return f"R{3000 + experiment_number * 100 + configuration_number * 10 + replicate:04d}"


def _configuration(study_root: Path, config_id: str) -> dict[str, Any]:
    config = load_data(study_root / "configurations" / f"{config_id}.yaml")
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid configuration {config_id}")
    return config


def _worker_command(
    *,
    condition_path: Path,
    documents: Path,
    questions: Path,
    embedding_model: Path,
    generation_model: Path,
    request_limit: int,
    intra_op_threads: int,
    inter_op_threads: int,
) -> list[str]:
    return [
        "--condition",
        str(condition_path),
        "--documents",
        str(documents),
        "--questions",
        str(questions),
        "--embedding-model",
        str(embedding_model),
        "--generation-model",
        str(generation_model),
        "--request-limit",
        str(request_limit),
        "--intra-op-threads",
        str(intra_op_threads),
        "--inter-op-threads",
        str(inter_op_threads),
    ]


def _invoke_worker(
    *,
    environment: str,
    root: Path,
    run_work: Path,
    condition_path: Path,
    study_root: Path,
    embedding_model: Path,
    generation_model: Path,
    request_limit: int,
    intra_op_threads: int,
    inter_op_threads: int,
) -> tuple[dict[str, Any], float, str | None]:
    arguments = _worker_command(
        condition_path=condition_path,
        documents=study_root / "inputs" / "documents.jsonl",
        questions=study_root / "inputs" / "questions.jsonl",
        embedding_model=embedding_model,
        generation_model=generation_model,
        request_limit=request_limit,
        intra_op_threads=intra_op_threads,
        inter_op_threads=inter_op_threads,
    )
    started = time.perf_counter()
    image_id = None
    if environment == "container":
        image_probe = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE],
            capture_output=True,
            text=True,
            check=True,
        )
        image_id = image_probe.stdout.strip()
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "--cpus",
            str(intra_op_threads),
            "--memory",
            "3g",
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,src={root},dst={root},readonly",
            "--mount",
            f"type=bind,src={cache_root()},dst={cache_root()},readonly",
            "--mount",
            f"type=bind,src={run_work},dst={run_work}",
            "--env",
            f"PYTHONPATH={root / 'src'}",
            "--env",
            "HOME=/tmp",
            IMAGE,
            "python",
            str(root / "src" / "atlas" / "studies" / "runners" / "s003_worker.py"),
            *arguments,
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "atlas.studies.runners.s003_worker",
            *arguments,
        ]
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-4000:]
        raise RuntimeError(f"RAG worker exited with {result.returncode}: {detail}")
    total_ms = (time.perf_counter() - started) * 1000
    return json.loads(result.stdout), total_ms, image_id


def _execute_run(
    *,
    work_dir: Path,
    study_root: Path,
    embedding_model: Path,
    generation_model: Path,
    experiment: str,
    configuration: str,
    replicate: int,
    seed: int,
    request_limit: int,
) -> Path:
    config = _configuration(study_root, configuration)
    condition = dict(config["extensions"]["atlas.condition"])
    runtime_configuration_id = str(config["runtime_configuration"]).split("/")[-1].split("@")[0]
    runtime_configuration = load_data(
        study_root / "configurations" / f"{runtime_configuration_id}.yaml"
    )
    if not isinstance(runtime_configuration, dict):
        raise RuntimeError(f"Invalid runtime configuration {runtime_configuration_id}")
    threads = runtime_configuration["threads"]
    intra_op_threads = int(threads["intra_op"])
    inter_op_threads = int(threads["inter_op"])
    run_work = work_dir / run_id(experiment, configuration, replicate)
    run_work.mkdir(parents=True)
    condition_path = run_work / "condition.json"
    condition_path.write_text(json.dumps(condition, sort_keys=True) + "\n")
    started_at = utc_now()
    payload, total_ms, image_id = _invoke_worker(
        environment=str(condition["environment"]),
        root=repository_root(),
        run_work=run_work,
        condition_path=condition_path,
        study_root=study_root,
        embedding_model=embedding_model,
        generation_model=generation_model,
        request_limit=request_limit,
        intra_op_threads=intra_op_threads,
        inter_op_threads=inter_op_threads,
    )
    rows = payload["rows"]
    startup_overhead = max(0.0, total_ms - payload["elapsed_seconds"] * 1000)
    if rows:
        rows[0]["ttft_client_ms"] += startup_overhead
        rows[0]["e2e_ms"] += startup_overhead
    quality = evaluate_rag_records(payload["responses"])
    quality_by_id = {item["request_id"]: item for item in quality["details"]}
    now = time.time_ns()
    for row in rows:
        details = quality_by_id[row["request_id"]]
        row.update(
            {
                "outcome": "complete",
                "t0_ns": now,
                "t5_ns": now + int(row["e2e_ms"] * 1_000_000),
                "quality_passed": bool(
                    details["retrieval_recall"] >= 0.9
                    and details["answer_keyword_recall"] >= 0.7
                    and details["citation_precision"] >= 0.8
                    and details["format_passed"]
                ),
            }
        )
    quality_rate = fmean(float(row["quality_passed"]) for row in rows)
    dimensions = quality["dimensions"]
    metrics = summarize_requests(
        rows,
        elapsed_seconds=total_ms / 1000,
        rss_bytes=int(payload["rss_bytes"]),
        peak_rss_bytes=int(payload["rss_bytes"]),
        cpu_ratio=float(payload["cpu_ratio"]),
        quality_rate=quality_rate,
        extra={
            "MET092": metric(float(dimensions["retrieval_recall"]), "ratio"),
            "MET093": metric(float(dimensions["answer_keyword_recall"]), "ratio"),
            "MET094": metric(float(dimensions["citation_precision"]), "ratio"),
            "MET095": metric(float(dimensions["citation_recall"]), "ratio"),
            "MET096": metric(float(dimensions["format_pass_rate"]), "ratio"),
        },
        slo_ttft_ms=3500,
        slo_tpot_ms=300,
        slo_e2e_ms=18000,
    )
    summary = {
        "profile": "full" if request_limit == 12 else "quick",
        "warmup_requests": 0,
        "measurement_requests": len(rows),
        "elapsed_seconds": total_ms / 1000,
        "worker_startup_ms": float(payload["startup_ms"]),
        "environment_overhead_ms": startup_overhead,
        "slo_passed": all(row["e2e_ms"] <= 18000 for row in rows),
        "metrics": metrics,
    }
    manifest = artifact_manifest()
    checksums = {name: str(item["sha256"]) for name, item in manifest.items()}
    if image_id and image_id.startswith("sha256:"):
        checksums["container-image"] = image_id.removeprefix("sha256:")
    draft = RunDraft(
        run_id=run_id(experiment, configuration, replicate),
        experiment=f"atlas://experiment/{experiment}@v1",
        configuration=f"atlas://configuration/{configuration}@v1",
        runtime="atlas://runtime/RT003@v1",
        replicate=replicate,
        seed=seed,
        started_at=started_at,
        ended_at=utc_now(),
        requests=rows,
        samples=[
            process_sample("MET023", payload["rss_bytes"], "byte"),
            process_sample("MET025", payload["cpu_ratio"], "ratio"),
        ],
        responses=payload["responses"],
        quality_results=quality,
        quality_passed=bool(quality["passed"]),
        summary=summary,
        input_fingerprints={
            "documents.jsonl": sha256_file(study_root / "inputs" / "documents.jsonl"),
            "questions.jsonl": sha256_file(study_root / "inputs" / "questions.jsonl"),
        },
        artifact_checksums=checksums,
        command=[
            "atlas",
            "execution",
            "run",
            "S003-cpu-enterprise-rag",
            "docker-cpu-pipeline",
        ],
        environment=[
            {"name": "execution_environment", "value": condition["environment"], "redacted": False},
            {
                "name": "embedding_representation",
                "value": condition["representation"],
                "redacted": False,
            },
            {
                "name": "intra_op_threads",
                "value": str(intra_op_threads),
                "redacted": False,
            },
            {
                "name": "inter_op_threads",
                "value": str(inter_op_threads),
                "redacted": False,
            },
        ],
    )
    return write_run_draft(work_dir, draft)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    root = repository_root()
    study_root = root / "studies" / "S003-cpu-enterprise-rag" / "v1"
    embedding_model = stage_directory(args.work_dir / "minilm", EMBEDDING_FILES)
    generation_model = stage_directory(args.work_dir / "smollm2", GENERATION_FILES)
    replicates = 1 if args.profile == "quick" else 3
    request_limit = 3 if args.profile == "quick" else 12
    order = list(EXPERIMENT_CONFIGS.items())
    random.Random(20260825).shuffle(order)
    for experiment, configurations in order:
        for configuration in configurations:
            for replicate in range(1, replicates + 1):
                _execute_run(
                    work_dir=args.work_dir,
                    study_root=study_root,
                    embedding_model=embedding_model,
                    generation_model=generation_model,
                    experiment=experiment,
                    configuration=configuration,
                    replicate=replicate,
                    seed=SEEDS[replicate - 1],
                    request_limit=request_limit,
                )


if __name__ == "__main__":
    main()
