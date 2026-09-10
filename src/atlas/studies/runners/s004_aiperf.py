from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from statistics import fmean
from typing import Any

from atlas.studies.runners.s004_trace import RequestSpec

AIPERF_VERSION = "0.12.0"
AIPERF_DEFAULT_BINARY = Path("/workspace/aiperf-venv/bin/aiperf")
CROSSCHECK_CONTEXT_TOKENS = 32768
CROSSCHECK_CONCURRENCY = 8
CROSSCHECK_REQUESTS = 96
CROSSCHECK_OUTPUT_TOKENS = 64
CROSSCHECK_RELATIVE_TOLERANCE = 0.10


def verify_aiperf(binary: Path) -> str:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"Pinned AIPerf executable is missing or not executable: {binary}")
    python = binary.parent / "python"
    if not python.is_file():
        raise RuntimeError(f"AIPerf environment has no Python interpreter: {python}")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('aiperf'))",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=environment,
    )
    version = result.stdout.strip()
    if result.returncode != 0 or version != AIPERF_VERSION:
        raise RuntimeError(f"Expected AIPerf {AIPERF_VERSION}, found {version or 'unavailable'}")
    return version


def aiperf_payload(spec: RequestSpec, *, model: str) -> dict[str, Any]:
    """Return an exact-token OpenAI completion payload accepted by AIPerf.

    AIPerf's raw-payload loader requires a ``messages`` array even when its
    response parser targets ``/v1/completions``. SGLang's completion request
    model ignores that loader sentinel and consumes the integer ``prompt``.
    """

    return {
        "messages": [],
        "model": model,
        "prompt": list(spec.input_ids),
        "max_tokens": spec.output_tokens,
        "temperature": 0,
        "top_p": 1,
        "top_k": 1,
        "ignore_eos": True,
        "return_token_ids": True,
        "stream": True,
        "stream_options": {"include_usage": True},
        "rid": spec.request_id,
    }


def write_aiperf_payloads(
    path: Path,
    specs: Sequence[RequestSpec],
    *,
    model: str,
) -> str:
    if not specs:
        raise ValueError("AIPerf cross-check requires at least one request")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(aiperf_payload(spec, model=model), sort_keys=True, separators=(",", ":"))
        for spec in specs
    ]
    encoded = ("\n".join(lines) + "\n").encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _metric_average(summary: dict[str, Any], name: str) -> tuple[float, str]:
    metric = summary.get(name)
    if not isinstance(metric, dict):
        raise ValueError(f"AIPerf summary has no {name} metric")
    value = metric.get("avg")
    unit = metric.get("unit")
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"AIPerf {name}.avg is missing or non-finite")
    if not isinstance(unit, str) or not unit:
        raise ValueError(f"AIPerf {name}.unit is missing")
    return float(value), unit


def _relative_disagreement(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1e-12)


def compare_aiperf_summary(
    atlas_rows: Sequence[dict[str, Any]],
    aiperf_summary: dict[str, Any],
) -> dict[str, Any]:
    """Compare independent clients without incorporating the check into estimates."""

    selected = [
        row
        for row in atlas_rows
        if row.get("outcome") == "complete"
        and row.get("load_cell_id")
        == f"context-{CROSSCHECK_CONTEXT_TOKENS}-concurrency-{CROSSCHECK_CONCURRENCY}"
    ]
    if not selected:
        raise ValueError("Atlas evidence has no completed 32K/concurrency-8 matrix requests")
    start_ns = min(int(row["t0_ns"]) for row in selected)
    end_ns = max(int(row["t5_ns"]) for row in selected)
    atlas = {
        "time_to_first_token_ms": fmean(float(row["ttft_client_ms"]) for row in selected),
        "inter_token_latency_ms": fmean(float(row["itl_mean_ms"]) for row in selected),
        "output_token_throughput_token_per_second": sum(
            int(row["output_tokens"]) for row in selected
        )
        / max((end_ns - start_ns) / 1e9, 1e-12),
    }
    aiperf_ttft, ttft_unit = _metric_average(aiperf_summary, "time_to_first_token")
    aiperf_itl, itl_unit = _metric_average(aiperf_summary, "inter_token_latency")
    aiperf_throughput, throughput_unit = _metric_average(aiperf_summary, "output_token_throughput")
    if ttft_unit != "ms" or itl_unit != "ms":
        raise ValueError(f"AIPerf latency units must be ms, found TTFT={ttft_unit} ITL={itl_unit}")
    if throughput_unit not in {"tokens/sec", "token/s", "tokens/s"}:
        raise ValueError(f"Unexpected AIPerf throughput unit: {throughput_unit}")
    aiperf = {
        "time_to_first_token_ms": aiperf_ttft,
        "inter_token_latency_ms": aiperf_itl,
        "output_token_throughput_token_per_second": aiperf_throughput,
    }
    absolute_floors = {
        "time_to_first_token_ms": 10.0,
        "inter_token_latency_ms": 1.0,
        "output_token_throughput_token_per_second": 1.0,
    }
    comparisons = {}
    passed = True
    for name, atlas_value in atlas.items():
        aiperf_value = aiperf[name]
        absolute = abs(atlas_value - aiperf_value)
        relative = _relative_disagreement(atlas_value, aiperf_value)
        within = absolute <= absolute_floors[name] or relative <= CROSSCHECK_RELATIVE_TOLERANCE
        comparisons[name] = {
            "atlas": atlas_value,
            "aiperf": aiperf_value,
            "absolute_difference": absolute,
            "symmetric_relative_difference": relative,
            "within_tolerance": within,
        }
        passed = passed and within

    request_count, request_count_unit = _metric_average(aiperf_summary, "request_count")
    input_length, input_length_unit = _metric_average(aiperf_summary, "input_sequence_length")
    output_length, output_length_unit = _metric_average(aiperf_summary, "output_sequence_length")
    error_count = 0.0
    if isinstance(aiperf_summary.get("error_request_count"), dict):
        error_count, _ = _metric_average(aiperf_summary, "error_request_count")
    shape_checks = {
        "request_count": request_count == CROSSCHECK_REQUESTS,
        "request_count_unit_present": bool(request_count_unit),
        "input_sequence_length": input_length == CROSSCHECK_CONTEXT_TOKENS,
        "input_sequence_length_unit": input_length_unit in {"tokens", "token"},
        "output_sequence_length": output_length == CROSSCHECK_OUTPUT_TOKENS,
        "output_sequence_length_unit": output_length_unit in {"tokens", "token"},
        "error_request_count": error_count == 0,
        "aiperf_version": aiperf_summary.get("aiperf_version") == AIPERF_VERSION,
    }
    passed = passed and all(shape_checks.values())
    return {
        "status": "pass" if passed else "disagreement",
        "headline_eligible": passed,
        "role": "non-confirmatory-independent-load-generator-validation",
        "aiperf_version": aiperf_summary.get("aiperf_version"),
        "relative_tolerance": CROSSCHECK_RELATIVE_TOLERANCE,
        "absolute_tolerance_floors": absolute_floors,
        "comparisons": comparisons,
        "shape_checks": shape_checks,
        "atlas_observations": len(selected),
        "aiperf_observations": request_count,
        "interpretation": (
            "A disagreement blocks headline use until investigated; it does not enter "
            "the confirmatory estimates."
        ),
    }


def run_aiperf(
    *,
    binary: Path,
    base_url: str,
    model: Path,
    specs: Sequence[RequestSpec],
    output_dir: Path,
    random_seed: int,
    timeout_seconds: float = 1800,
) -> dict[str, Any]:
    verify_aiperf(binary)
    output_dir.mkdir(parents=True, exist_ok=False)
    payload_path = output_dir / "exact-token-payloads.jsonl"
    payload_sha256 = write_aiperf_payloads(payload_path, specs, model=str(model))
    artifacts = output_dir / "artifacts"
    command = [
        str(binary),
        "profile",
        "--model",
        str(model),
        "--tokenizer",
        str(model),
        "--tokenizer-trust-remote-code",
        "--url",
        base_url,
        "--endpoint-type",
        "completions",
        "--input-file",
        str(payload_path),
        "--custom-dataset-type",
        "raw_payload",
        "--streaming",
        "--use-server-token-count",
        "--concurrency",
        str(CROSSCHECK_CONCURRENCY),
        "--request-count",
        str(len(specs)),
        "--dataset-sampling-strategy",
        "sequential",
        "--random-seed",
        str(random_seed),
        "--export-level",
        "records",
        "--artifact-dir",
        str(artifacts),
        "--no-server-metrics",
        "--no-auto-plot",
    ]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
        env=environment,
    )
    (output_dir / "stdout.log").write_text(completed.stdout)
    (output_dir / "stderr.log").write_text(completed.stderr)
    _metadata = {
        "command": command,
        "exit_code": completed.returncode,
        "payload_sha256": payload_sha256,
        "request_count": len(specs),
    }
    (output_dir / "invocation.json").write_text(
        json.dumps(_metadata, indent=2, sort_keys=True) + "\n"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"AIPerf cross-check exited {completed.returncode}; see {output_dir / 'stderr.log'}"
        )
    summaries = list(artifacts.rglob("profile_export_aiperf.json"))
    if len(summaries) != 1:
        raise RuntimeError(f"Expected one AIPerf summary under {artifacts}, found {len(summaries)}")
    summary = json.loads(summaries[0].read_text())
    if not isinstance(summary, dict):
        raise RuntimeError("AIPerf summary is not a JSON object")
    return {
        "summary": summary,
        "summary_path": str(summaries[0]),
        **_metadata,
    }
