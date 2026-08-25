from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import fmean
from typing import Any

import numpy as np
import psutil

from atlas.utilities.serialization import load_data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def repository_root() -> Path:
    value = os.environ.get("ATLAS_REPOSITORY_ROOT")
    if not value:
        raise RuntimeError("ATLAS_REPOSITORY_ROOT is required")
    return Path(value).resolve()


def cache_root() -> Path:
    value = os.environ.get("ATLAS_CACHE_DIR")
    if not value:
        raise RuntimeError("ATLAS_CACHE_DIR is required")
    return Path(value).resolve()


def bundle_root() -> Path:
    value = os.environ.get("ATLAS_BUNDLE_DIR")
    if not value:
        raise RuntimeError("ATLAS_BUNDLE_DIR is required")
    return Path(value).resolve()


def artifact_manifest() -> dict[str, dict[str, Any]]:
    data = load_data(bundle_root() / "execution.yaml")
    if not isinstance(data, dict):
        raise RuntimeError("execution.yaml must contain an object")
    return {str(item["name"]): item for item in data.get("artifacts", [])}


def artifact_path(name: str) -> Path:
    artifact = artifact_manifest().get(name)
    if artifact is None:
        raise RuntimeError(f"Execution manifest has no artifact named {name}")
    path = cache_root() / "artifacts" / artifact["sha256"] / artifact["name"]
    if not path.is_file():
        raise RuntimeError(f"Artifact is not prepared: {name}; run atlas execution prepare")
    return path


def stage_directory(target: Path, names: dict[str, str]) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for target_name, artifact_name in names.items():
        destination = target / target_name
        source = artifact_path(artifact_name)
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.symlink_to(source)
    return target


def percentile(values: list[float], quantile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), quantile))


def distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0}
    return {
        "count": len(values),
        "mean": fmean(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
    }


def metric(value: float, unit: str, values: list[float] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"value": float(value), "unit": unit}
    if values is not None:
        result["distribution"] = distribution(values)
    return result


def summarize_requests(
    rows: list[dict[str, Any]],
    *,
    elapsed_seconds: float,
    rss_bytes: int,
    peak_rss_bytes: int,
    cpu_ratio: float,
    quality_rate: float,
    extra: dict[str, dict[str, Any]] | None = None,
    slo_ttft_ms: float = 2500,
    slo_tpot_ms: float = 175,
    slo_e2e_ms: float = 15000,
) -> dict[str, dict[str, Any]]:
    elapsed = max(elapsed_seconds, 1e-9)
    completed = [row for row in rows if row["outcome"] == "complete"]
    failed = len(rows) - len(completed)
    input_tokens = sum(int(row["input_tokens"]) for row in completed)
    output_tokens = sum(int(row["output_tokens"]) for row in completed)
    ttft = [float(row["ttft_client_ms"]) for row in completed]
    queue = [float(row["queue_ms"]) for row in completed]
    tpot = [float(row["tpot_ms"]) for row in completed]
    itl = [float(row["itl_mean_ms"]) for row in completed]
    e2e = [float(row["e2e_ms"]) for row in completed]
    slo_good = [
        row
        for row in completed
        if row["ttft_client_ms"] <= slo_ttft_ms
        and row["tpot_ms"] <= slo_tpot_ms
        and row["e2e_ms"] <= slo_e2e_ms
        and row["quality_passed"]
    ]
    metrics = {
        "MET001": metric(len(rows), "count"),
        "MET002": metric(len(completed), "count"),
        "MET003": metric(failed, "count"),
        "MET004": metric(0, "count"),
        "MET005": metric(0, "count"),
        "MET006": metric(0, "count"),
        "MET007": metric(input_tokens, "token"),
        "MET008": metric(output_tokens, "token"),
        "MET009": metric(input_tokens + output_tokens, "token"),
        "MET010": metric(fmean(ttft), "ms", ttft),
        "MET011": metric(fmean(ttft), "ms", ttft),
        "MET012": metric(fmean(queue), "ms", queue),
        "MET013": metric(fmean(tpot), "ms/token", tpot),
        "MET014": metric(fmean(itl), "ms", itl),
        "MET015": metric(fmean(e2e), "ms", e2e),
        "MET016": metric(len(rows) / elapsed, "request/s"),
        "MET017": metric(len(completed) / elapsed, "request/s"),
        "MET018": metric(input_tokens / elapsed, "token/s"),
        "MET019": metric(output_tokens / elapsed, "token/s"),
        "MET020": metric((input_tokens + output_tokens) / elapsed, "token/s"),
        "MET021": metric(len(slo_good) / elapsed, "request/s"),
        "MET023": metric(rss_bytes, "byte"),
        "MET024": metric(peak_rss_bytes, "byte"),
        "MET025": metric(cpu_ratio, "ratio"),
        "MET028": metric(failed / len(rows) if rows else 0.0, "ratio"),
        "MET029": metric(len(completed) / len(rows) if rows else 0.0, "ratio"),
        "MET030": metric(quality_rate, "ratio"),
    }
    metrics.update(extra or {})
    return metrics


def process_sample(metric_id: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "timestamp_ns": __import__("time").time_ns(),
        "metric_id": metric_id,
        "value": float(value),
        "unit": unit,
        "scope": "runner-process",
    }


def process_rss() -> int:
    return int(psutil.Process().memory_info().rss)
