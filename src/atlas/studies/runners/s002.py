from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

import psutil

from atlas.studies.evaluators import evaluate_code_results, extract_python
from atlas.studies.evidence_writer import RunDraft, sha256_file, utc_now, write_run_draft
from atlas.studies.runners.common import (
    artifact_manifest,
    artifact_path,
    load_jsonl,
    metric,
    process_sample,
    repository_root,
    summarize_requests,
)
from atlas.studies.runners.s002_lifecycle import SANDBOX_IMAGE, build_root
from atlas.utilities.serialization import load_data

EXPERIMENT_CONFIGS = {
    "E0005": ("CFG009", "CFG008"),
    "E0006": ("CFG008", "CFG010", "CFG011"),
    "E0007": ("CFG008", "CFG012"),
    "E0008": ("CFG013", "CFG008", "CFG014"),
}
SEEDS = (101, 202, 303)


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    ttft_ms: float
    e2e_ms: float
    cached_tokens: int


def run_id(experiment: str, configuration: str, replicate: int) -> str:
    experiment_number = int(experiment[-1]) - 4
    configuration_number = int(configuration[-3:]) - 7
    return f"R{2000 + experiment_number * 100 + configuration_number * 10 + replicate:04d}"


def _free_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _wait_for_server(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited with status {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("llama-server did not become healthy within 120 seconds")


def _start_server(
    work_dir: Path, *, threads: int, slots: int, context: int, prefix_cache: bool
) -> tuple[subprocess.Popen[bytes], int, Any]:
    server = build_root() / "bin" / "llama-server"
    if not server.is_file():
        raise RuntimeError("llama.cpp is not built; bundle start did not complete")
    port = _free_port()
    command = [
        str(server),
        "--model",
        str(artifact_path("qwen-coder-q4-k-m.gguf")),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--threads",
        str(threads),
        "--threads-batch",
        str(threads),
        "--ctx-size",
        str(context),
        "--parallel",
        str(slots),
        "--n-gpu-layers",
        "0",
        "--device",
        "none",
        "--offline",
        "--no-ui",
        "--metrics",
        "--cache-prompt" if prefix_cache else "--no-cache-prompt",
        "--temperature",
        "0",
        "--top-k",
        "1",
    ]
    log = (work_dir / "llama-server.log").open("ab")
    environment = os.environ.copy()
    environment["DYLD_LIBRARY_PATH"] = str(server.parent)
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment)
    (work_dir / "llama-server.pid").write_text(str(process.pid))
    try:
        _wait_for_server(port, process)
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        log.close()
        raise
    return process, port, log


def _stop_server(process: subprocess.Popen[bytes], log: Any, work_dir: Path) -> None:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log.close()
    (work_dir / "llama-server.pid").unlink(missing_ok=True)


def _completion(port: int, prompt: str, seed: int) -> Completion:
    body = json.dumps(
        {
            "model": "qwen-coder",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Write a correct, deterministic Python function. Return only one "
                        "Python code block with the requested function and no explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "seed": seed,
            "max_tokens": 128,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token: float | None = None
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            payload = json.loads(line[6:])
            usage.update(payload.get("usage") or {})
            choices = payload.get("choices") or []
            content = choices[0].get("delta", {}).get("content") if choices else None
            if content:
                if first_token is None:
                    first_token = time.perf_counter()
                chunks.append(content)
    ended = time.perf_counter()
    prompt_details = usage.get("prompt_tokens_details") or {}
    return Completion(
        text="".join(chunks),
        input_tokens=int(usage.get("prompt_tokens") or max(1, len(prompt.split()))),
        output_tokens=int(usage.get("completion_tokens") or max(1, len("".join(chunks).split()))),
        ttft_ms=((first_token or ended) - started) * 1000,
        e2e_ms=(ended - started) * 1000,
        cached_tokens=int(prompt_details.get("cached_tokens") or 0),
    )


def _sandbox(work_dir: Path, task: dict[str, Any], text: str) -> dict[str, Any]:
    task_root = work_dir / "sandbox" / task["id"]
    task_root.mkdir(parents=True, exist_ok=True)
    code = extract_python(text, task["function"])
    (task_root / "solution.py").write_text(code + "\n")
    test_body = code + "\n\n" + "\n".join(task["tests"]) + "\n"
    (task_root / "test_solution.py").write_text(test_body)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "65534:65534",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--cpus",
        "1",
        "--memory",
        "128m",
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--mount",
        f"type=bind,src={task_root},dst=/workspace,readonly",
        "--workdir",
        "/workspace",
        SANDBOX_IMAGE,
        "python",
        "-I",
        "test_solution.py",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        return {
            "request_id": task["id"],
            "sandbox_completed": True,
            "tests_passed": result.returncode == 0,
            "exit_code": result.returncode,
            "diagnostic": (result.stderr or result.stdout)[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "request_id": task["id"],
            "sandbox_completed": False,
            "tests_passed": False,
            "exit_code": 124,
            "diagnostic": "sandbox wall-time limit exceeded",
        }


def _configuration(study_root: Path, config_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_data(study_root / "configurations" / f"{config_id}.yaml")
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid configuration {config_id}")
    runtime_id = config["runtime_configuration"].split("/")[-1].split("@")[0]
    runtime = load_data(study_root / "configurations" / f"{runtime_id}.yaml")
    if not isinstance(runtime, dict):
        raise RuntimeError(f"Invalid runtime configuration {runtime_id}")
    return config, runtime


def _task_prompt(task: dict[str, Any], context: int) -> str:
    repetitions = max(0, (context - 256) // 16)
    prefix = "Shared project rule: use pure Python and no external state. " * repetitions
    return f"{prefix}\nSignature: {task['signature']}\nTask: {task['instruction']}"


def _execute_run(
    *,
    work_dir: Path,
    study_root: Path,
    tasks: list[dict[str, Any]],
    experiment: str,
    configuration: str,
    replicate: int,
    seed: int,
    request_limit: int,
) -> Path:
    config, runtime = _configuration(study_root, configuration)
    condition = config["extensions"]["atlas.condition"]
    threads = int(condition["threads"])
    slots = int(condition["slots"])
    context = int(condition["context"])
    server_context = int(runtime["memory"]["context_tokens"])
    selected = tasks[:request_limit]
    random.Random(seed).shuffle(selected)
    run_work = work_dir / run_id(experiment, configuration, replicate)
    run_work.mkdir(parents=True)
    started_at = utc_now()
    process, port, log = _start_server(
        run_work,
        threads=threads,
        slots=slots,
        context=server_context,
        prefix_cache=bool(condition["prefix_cache"]),
    )
    server_process = psutil.Process(process.pid)
    rss_start = int(server_process.memory_info().rss)
    server_process.cpu_percent(None)
    measured_at = time.perf_counter()
    try:
        prompts = [_task_prompt(task, context) for task in selected]
        if slots == 2:
            with ThreadPoolExecutor(max_workers=2) as executor:
                completions = list(
                    executor.map(lambda item: _completion(port, item[1], seed), enumerate(prompts))
                )
        else:
            completions = [_completion(port, prompt, seed) for prompt in prompts]
        elapsed_seconds = time.perf_counter() - measured_at
        rss_end = int(server_process.memory_info().rss)
        cpu_ratio = server_process.cpu_percent(None) / 100.0
    finally:
        _stop_server(process, log, run_work)
    code_results = [
        _sandbox(run_work, task, completion.text)
        for task, completion in zip(selected, completions, strict=True)
    ]
    quality = evaluate_code_results(code_results)
    quality_by_id = {item["request_id"]: item for item in code_results}
    request_rows = []
    responses = []
    for task, completion in zip(selected, completions, strict=True):
        tpot = max(0.0, completion.e2e_ms - completion.ttft_ms) / max(
            completion.output_tokens - 1, 1
        )
        now = time.time_ns()
        passed = bool(quality_by_id[task["id"]]["tests_passed"])
        request_rows.append(
            {
                "request_id": task["id"],
                "request_class": "coding-task",
                "outcome": "complete",
                "t0_ns": now,
                "t5_ns": now + int(completion.e2e_ms * 1_000_000),
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
                "ttft_client_ms": completion.ttft_ms,
                "tpot_ms": tpot,
                "itl_mean_ms": tpot,
                "itl_p95_ms": tpot,
                "e2e_ms": completion.e2e_ms,
                "queue_ms": 0.0,
                "quality_passed": passed,
            }
        )
        responses.append(
            {
                "request_id": task["id"],
                "text": completion.text,
                "cached_prompt_tokens": completion.cached_tokens,
            }
        )
    quality_rate = fmean(float(row["quality_passed"]) for row in request_rows)
    cached_requests = sum(completion.cached_tokens > 0 for completion in completions)
    metrics = summarize_requests(
        request_rows,
        elapsed_seconds=elapsed_seconds,
        rss_bytes=rss_end,
        peak_rss_bytes=max(rss_start, rss_end),
        cpu_ratio=cpu_ratio,
        quality_rate=quality_rate,
        extra={
            "MET042": metric(cached_requests / len(completions), "ratio"),
            "MET091": metric(quality_rate, "ratio"),
            "MET096": metric(float(quality["dimensions"]["sandbox_completion"]), "ratio"),
        },
        slo_ttft_ms=5000,
        slo_tpot_ms=300,
        slo_e2e_ms=60000,
    )
    summary = {
        "profile": "full" if request_limit == 6 else "quick",
        "warmup_requests": 0,
        "measurement_requests": len(request_rows),
        "elapsed_seconds": elapsed_seconds,
        "slo_passed": all(
            row["ttft_client_ms"] <= 5000 and row["tpot_ms"] <= 300 and row["e2e_ms"] <= 60000
            for row in request_rows
        ),
        "metrics": metrics,
    }
    manifest = artifact_manifest()
    checksums = {name: str(item["sha256"]) for name, item in manifest.items()}
    checksums["llama-server"] = sha256_file(build_root() / "bin" / "llama-server")
    draft = RunDraft(
        run_id=run_id(experiment, configuration, replicate),
        experiment=f"atlas://experiment/{experiment}@v1",
        configuration=f"atlas://configuration/{configuration}@v1",
        runtime="atlas://runtime/RT002@v1",
        replicate=replicate,
        seed=seed,
        started_at=started_at,
        ended_at=utc_now(),
        requests=request_rows,
        samples=[
            process_sample("MET023", rss_end, "byte"),
            process_sample("MET025", cpu_ratio, "ratio"),
        ],
        responses=responses,
        quality_results=quality,
        quality_passed=bool(quality["passed"]),
        summary=summary,
        input_fingerprints={"tasks.jsonl": sha256_file(study_root / "inputs" / "tasks.jsonl")},
        artifact_checksums=checksums,
        command=[
            "atlas",
            "execution",
            "run",
            "S002-cpu-coding-agent",
            "llama-cpp-cpu-server",
        ],
        environment=[
            {"name": "LLAMA_ARG_THREADS", "value": str(threads), "redacted": False},
            {"name": "LLAMA_ARG_N_PARALLEL", "value": str(slots), "redacted": False},
        ],
    )
    return write_run_draft(work_dir, draft)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    root = repository_root()
    study_root = root / "studies" / "S002-cpu-coding-agent" / "v1"
    tasks = load_jsonl(study_root / "inputs" / "tasks.jsonl")
    replicates = 1 if args.profile == "quick" else 3
    request_limit = 3 if args.profile == "quick" else 6
    for experiment, configurations in EXPERIMENT_CONFIGS.items():
        for configuration in configurations:
            for replicate in range(1, replicates + 1):
                _execute_run(
                    work_dir=args.work_dir,
                    study_root=study_root,
                    tasks=tasks,
                    experiment=experiment,
                    configuration=configuration,
                    replicate=replicate,
                    seed=SEEDS[replicate - 1],
                    request_limit=request_limit,
                )


if __name__ == "__main__":
    main()
