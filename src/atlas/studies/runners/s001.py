from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

import psutil

from atlas.studies.evaluators import evaluate_chat_records
from atlas.studies.evidence_writer import RunDraft, sha256_file, utc_now, write_run_draft
from atlas.studies.runners.common import (
    artifact_manifest,
    load_jsonl,
    metric,
    process_rss,
    process_sample,
    repository_root,
    stage_directory,
    summarize_requests,
)
from atlas.utilities.serialization import load_data

EXPERIMENT_CONFIGS = {
    "E0001": ("CFG001", "CFG002"),
    "E0002": ("CFG001", "CFG003", "CFG004"),
    "E0003": ("CFG001", "CFG005", "CFG006"),
    "E0004": ("CFG001", "CFG007"),
}
SEEDS = (101, 202, 303)
MODEL_FILES = {
    "config.json": "smollm2-config.json",
    "generation_config.json": "smollm2-generation-config.json",
    "model.safetensors": "smollm2-model.safetensors",
    "special_tokens_map.json": "smollm2-special-tokens-map.json",
    "tokenizer.json": "smollm2-tokenizer.json",
    "tokenizer_config.json": "smollm2-tokenizer-config.json",
}


@dataclass(frozen=True)
class Generation:
    texts: list[str]
    input_tokens: list[int]
    output_tokens: list[int]
    ttft_ms: float
    elapsed_ms: float
    token_step_ms: list[float]


def run_id(experiment: str, configuration: str, replicate: int) -> str:
    experiment_number = int(experiment[-1])
    configuration_number = int(configuration[-3:])
    return f"R{1000 + experiment_number * 100 + configuration_number * 10 + replicate:04d}"


def _load_model(model_dir: Path) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    model = AutoModelForCausalLM.from_pretrained(model_dir, local_files_only=True)
    model.eval()
    return tokenizer, model


def _prompts(tokenizer: Any, records: list[dict[str, Any]]) -> list[str]:
    prompts = []
    for record in records:
        messages = [
            {
                "role": "system",
                "content": (
                    "Answer succinctly and directly. Preserve the important nouns, numbers, "
                    "and constraints from the request."
                ),
            }
        ]
        messages.append({"role": "user", "content": "\n".join(record["turns"])})
        prompts.append(
            tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        )
    return prompts


def generate_batch(
    tokenizer: Any, model: Any, prompts: list[str], maximum_new_tokens: int
) -> Generation:
    import torch

    encoded = tokenizer(prompts, padding=True, truncation=True, max_length=448, return_tensors="pt")
    input_counts = encoded["attention_mask"].sum(dim=1).tolist()
    generated: list[list[int]] = [[] for _ in prompts]
    active = torch.ones(len(prompts), dtype=torch.bool)
    step_times: list[float] = []
    started = time.perf_counter()
    with torch.inference_mode():
        before = time.perf_counter()
        output = model(**encoded, use_cache=True)
        next_tokens = output.logits[:, -1, :].argmax(dim=-1)
        step_times.append((time.perf_counter() - before) * 1000)
        first_token_at = time.perf_counter()
        past = output.past_key_values
        attention_mask = encoded["attention_mask"]
        for index, token in enumerate(next_tokens.tolist()):
            generated[index].append(token)
        active &= next_tokens != tokenizer.eos_token_id
        for _ in range(maximum_new_tokens - 1):
            if not bool(active.any()):
                break
            attention_mask = torch.cat(
                [attention_mask, torch.ones((len(prompts), 1), dtype=attention_mask.dtype)], dim=1
            )
            before = time.perf_counter()
            output = model(
                input_ids=next_tokens[:, None],
                attention_mask=attention_mask,
                past_key_values=past,
                use_cache=True,
            )
            step_times.append((time.perf_counter() - before) * 1000)
            past = output.past_key_values
            next_tokens = output.logits[:, -1, :].argmax(dim=-1)
            for index, token in enumerate(next_tokens.tolist()):
                if active[index]:
                    generated[index].append(token)
            active &= next_tokens != tokenizer.eos_token_id
    elapsed_ms = (time.perf_counter() - started) * 1000
    return Generation(
        texts=tokenizer.batch_decode(generated, skip_special_tokens=True),
        input_tokens=[int(value) for value in input_counts],
        output_tokens=[len(value) for value in generated],
        ttft_ms=(first_token_at - started) * 1000,
        elapsed_ms=elapsed_ms,
        token_step_ms=step_times,
    )


def _configuration(study_root: Path, config_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_data(study_root / "configurations" / f"{config_id}.yaml")
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid configuration {config_id}")
    runtime_id = config["runtime_configuration"].split("/")[-1].split("@")[0]
    runtime = load_data(study_root / "configurations" / f"{runtime_id}.yaml")
    if not isinstance(runtime, dict):
        raise RuntimeError(f"Invalid runtime configuration {runtime_id}")
    return config, runtime


def _execute_run(
    *,
    work_dir: Path,
    study_root: Path,
    model_dir: Path,
    records: list[dict[str, Any]],
    experiment: str,
    configuration: str,
    replicate: int,
    seed: int,
    request_limit: int,
) -> Path:
    import torch

    config, runtime = _configuration(study_root, configuration)
    condition = config["extensions"]["atlas.condition"]
    threads = int(runtime["threads"]["intra_op"])
    batch_size = int(runtime["batching"]["maximum_requests"])
    torch.set_num_threads(threads)
    randomizer = random.Random(seed)
    selected = records[:request_limit]
    randomizer.shuffle(selected)
    started_at = utc_now()
    process = psutil.Process()
    process.cpu_percent(None)
    rss_start = process_rss()
    cold = condition["state"] == "cold"
    tokenizer = model = None
    if not cold:
        tokenizer, model = _load_model(model_dir)
        warm_records = selected[:2]
        generate_batch(tokenizer, model, _prompts(tokenizer, warm_records), 8)
    measurement_start = time.perf_counter()
    responses: list[dict[str, Any]] = []
    request_rows: list[dict[str, Any]] = []
    modeled_available_ms = 0.0
    arrivals = [index * 2000.0 for index in range(len(selected))]
    if condition["traffic"] == "bursty":
        arrivals = [(index // 4) * 200.0 for index in range(len(selected))]
    for offset in range(0, len(selected), batch_size):
        batch = selected[offset : offset + batch_size]
        load_ms = 0.0
        if model is None or tokenizer is None:
            before_load = time.perf_counter()
            tokenizer, model = _load_model(model_dir)
            load_ms = (time.perf_counter() - before_load) * 1000
        prompts = _prompts(tokenizer, batch)
        generation = generate_batch(tokenizer, model, prompts, 64)
        service_ms = load_ms + generation.elapsed_ms
        batch_arrival = max(arrivals[offset : offset + len(batch)])
        batch_start = max(modeled_available_ms, batch_arrival)
        modeled_available_ms = batch_start + service_ms
        for index, (record, text) in enumerate(zip(batch, generation.texts, strict=True)):
            row_index = offset + index
            queue_ms = max(0.0, batch_start - arrivals[row_index])
            ttft = queue_ms + load_ms + generation.ttft_ms
            output_tokens = generation.output_tokens[index]
            tpot = (
                sum(generation.token_step_ms[1:]) / max(output_tokens - 1, 1)
                if output_tokens > 1
                else generation.ttft_ms
            )
            e2e = queue_ms + service_ms
            responses.append({"request_id": record["id"], "text": text})
            request_rows.append(
                {
                    "request_id": record["id"],
                    "request_class": record["class"],
                    "outcome": "complete",
                    "t0_ns": time.time_ns(),
                    "t5_ns": time.time_ns() + int(e2e * 1_000_000),
                    "input_tokens": generation.input_tokens[index],
                    "output_tokens": output_tokens,
                    "ttft_client_ms": ttft,
                    "tpot_ms": tpot,
                    "itl_mean_ms": tpot,
                    "itl_p95_ms": max(generation.token_step_ms),
                    "e2e_ms": e2e,
                    "queue_ms": queue_ms,
                    "quality_passed": False,
                }
            )
    elapsed_seconds = time.perf_counter() - measurement_start
    quality = evaluate_chat_records(responses, {record["id"]: record for record in records})
    details = {item["request_id"]: item for item in quality["details"]}
    for row in request_rows:
        detail = details[row["request_id"]]
        row["quality_passed"] = bool(
            detail["valid_output"] and detail["topic_keyword_recall"] >= 0.75
        )
    quality_rate = fmean(float(row["quality_passed"]) for row in request_rows)
    rss_end = process_rss()
    cpu_ratio = process.cpu_percent(None) / 100.0
    metrics = summarize_requests(
        request_rows,
        elapsed_seconds=elapsed_seconds,
        rss_bytes=rss_end,
        peak_rss_bytes=max(rss_start, rss_end),
        cpu_ratio=cpu_ratio,
        quality_rate=quality_rate,
        extra={
            "MET093": metric(float(quality["dimensions"]["topic_keyword_recall"]), "ratio"),
            "MET096": metric(float(quality["dimensions"]["valid_output"]), "ratio"),
        },
    )
    summary = {
        "profile": "full" if request_limit == 12 else "quick",
        "warmup_requests": 0 if cold else min(2, len(selected)),
        "measurement_requests": len(request_rows),
        "elapsed_seconds": elapsed_seconds,
        "slo_passed": all(
            row["ttft_client_ms"] <= 2500 and row["tpot_ms"] <= 175 and row["e2e_ms"] <= 15000
            for row in request_rows
        ),
        "metrics": metrics,
    }
    manifest = artifact_manifest()
    checksums = {name: str(item["sha256"]) for name, item in manifest.items()}
    ended_at = utc_now()
    draft = RunDraft(
        run_id=run_id(experiment, configuration, replicate),
        experiment=f"atlas://experiment/{experiment}@v1",
        configuration=f"atlas://configuration/{configuration}@v1",
        runtime="atlas://runtime/RT001@v1",
        replicate=replicate,
        seed=seed,
        started_at=started_at,
        ended_at=ended_at,
        requests=request_rows,
        samples=[
            process_sample("MET023", rss_end, "byte"),
            process_sample("MET025", cpu_ratio, "ratio"),
        ],
        responses=responses,
        quality_results=quality,
        quality_passed=bool(quality["passed"]),
        summary=summary,
        input_fingerprints={
            "conversations.jsonl": sha256_file(study_root / "inputs" / "conversations.jsonl")
        },
        artifact_checksums=checksums,
        command=["atlas", "execution", "run", "S001-cpu-interactive-chat", "transformers-cpu"],
        environment=[
            {"name": "TOKENIZERS_PARALLELISM", "value": "false", "redacted": False},
            {"name": "OMP_NUM_THREADS", "value": str(threads), "redacted": False},
        ],
    )
    return write_run_draft(work_dir, draft)


def main() -> None:
    import torch

    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    root = repository_root()
    study_root = root / "studies" / "S001-cpu-interactive-chat" / "v1"
    model_dir = stage_directory(args.work_dir / "model", MODEL_FILES)
    records = load_jsonl(study_root / "inputs" / "conversations.jsonl")
    replicates = 1 if args.profile == "quick" else 3
    request_limit = 3 if args.profile == "quick" else 12
    torch.set_num_interop_threads(1)
    for experiment, configurations in EXPERIMENT_CONFIGS.items():
        for configuration in configurations:
            for replicate in range(1, replicates + 1):
                _execute_run(
                    work_dir=args.work_dir,
                    study_root=study_root,
                    model_dir=model_dir,
                    records=records,
                    experiment=experiment,
                    configuration=configuration,
                    replicate=replicate,
                    seed=SEEDS[replicate - 1],
                    request_limit=request_limit,
                )


if __name__ == "__main__":
    main()
