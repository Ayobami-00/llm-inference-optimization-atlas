from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from statistics import fmean, median
from typing import Any

import psutil

from atlas.studies.evaluators import evaluate_engram_equivalence
from atlas.studies.evidence_writer import RunDraft, sha256_file, utc_now, write_run_draft
from atlas.studies.runners.common import distribution, process_sample, repository_root
from atlas.studies.runners.s004_aiperf import (
    AIPERF_DEFAULT_BINARY,
    CROSSCHECK_CONCURRENCY,
    CROSSCHECK_REQUESTS,
    compare_aiperf_summary,
    run_aiperf,
    verify_aiperf,
)
from atlas.studies.runners.s004_client import (
    RequestResult,
    flush_cache,
    healthcheck,
    load_snapshot,
    run_count,
    run_fixed_concurrency,
    run_open_loop,
)
from atlas.studies.runners.s004_lifecycle import (
    BASE_URL,
    CONDITION_ENVIRONMENT,
    launch_server,
    preflight,
    resolve_treatment,
    resolved_server_configuration,
    verify_preregistration_pushed,
)
from atlas.studies.runners.s004_lifecycle import (
    sha256_file as lifecycle_sha256_file,
)
from atlas.studies.runners.s004_trace import (
    CONTENT_FAMILIES,
    CONTEXT_CONCURRENCY,
    RequestSpec,
    capacity_trace,
    exact_content_tokens,
    matrix_request,
    reconcile_request_ids,
    relative_boundary_width,
    trace_fingerprint,
)
from atlas.utilities.serialization import load_data

CONFIGURATION_ORDER = (
    ("CFG021", "CFG022", "CFG023"),
    ("CFG021", "CFG022", "CFG023"),
    ("CFG023", "CFG022", "CFG021"),
    ("CFG021", "CFG023", "CFG022"),
    ("CFG023", "CFG021", "CFG022"),
)
SEEDS = (41001, 41002, 41003, 41004, 41005)
MODEL_PATH = Path("/workspace/models/DeepSeek-V4.1-Flash-dba1be0")
EXPECTED_GPU_POWER_LIMIT_W = 1_000.0
POWER_LIMIT_TOLERANCE_W = 0.1
SOFTWARE_POWER_CAP_THROTTLE_MASK = 0x4
INVALIDATING_GPU_CLOCK_EVENT_MASK = 0xE8
HARDWARE_HEALTH_POLICY_VERSION = "E0013-AMENDMENT-001"
COLLECTOR_SHUTDOWN_TIMEOUT_SECONDS = 20.0
GPU_TELEMETRY_QUERY_FIELDS = (
    "index",
    "utilization.gpu",
    "memory.used",
    "power.draw",
    "power.limit",
    "temperature.gpu",
    "clocks.current.sm",
    "clocks_throttle_reasons.active",
    "ecc.errors.uncorrected.volatile.total",
)
# Retain the older public name for callers that imported it before the
# preregistration amendment. Software power capping (0x4) is intentionally no
# longer part of this invalidating mask.
THERMAL_OR_POWER_THROTTLE_MASK = INVALIDATING_GPU_CLOCK_EVENT_MASK
CAPACITY_INITIAL_RATE = 0.2
MINIMUM_SLO_CLASS_OBSERVATIONS = 3


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return float(ordered[index])


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    result = distribution(list(values))
    if len(values) >= 100:
        result["p99"] = _percentile(values, 0.99)
    return result


def _metric(value: float, unit: str, values: Sequence[float] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"value": float(value), "unit": unit}
    if values is not None:
        result["distribution"] = _distribution(values)
    return result


class TelemetryCollector:
    def __init__(
        self,
        output: Path,
        *,
        server_pid: int,
        interval_seconds: float = 1.0,
        include_load: bool = True,
    ) -> None:
        self.output = output
        self.server_pid = server_pid
        self.interval_seconds = interval_seconds
        self.include_load = include_load
        self.samples: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak_rss_bytes = 0
        self._pcie_unavailable_reported = False
        self._shutdown_failure: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._shutdown_failure is not None:
            _write_json(self.output, {"samples": self.samples, "events": self.events})
            return
        if self._thread is not None:
            self._thread.join(timeout=COLLECTOR_SHUTDOWN_TIMEOUT_SECONDS)
            if self._thread.is_alive():
                self._shutdown_failure = (
                    "Telemetry collector did not finish its mandatory sampling cycle within "
                    f"{COLLECTOR_SHUTDOWN_TIMEOUT_SECONDS:.0f} seconds"
                )
                self.events.append(
                    {
                        "timestamp_ns": time.time_ns(),
                        "event_type": "collector-error",
                        "details_json": json.dumps(
                            {"error": self._shutdown_failure, "terminal": True}, sort_keys=True
                        ),
                    }
                )
                _write_json(self.output, {"samples": self.samples, "events": self.events})
                raise RuntimeError(self._shutdown_failure)
            self._thread = None
        _write_json(self.output, {"samples": self.samples, "events": self.events})

    def _sample(
        self, timestamp_ns: int, metric_id: str, value: float, unit: str, scope: str
    ) -> None:
        self.samples.append(
            {
                "timestamp_ns": timestamp_ns,
                "metric_id": metric_id,
                "value": float(value),
                "unit": unit,
                "scope": scope,
            }
        )

    def _process_snapshot(self, timestamp_ns: int) -> None:
        root = psutil.Process(self.server_pid)
        processes = [root, *root.children(recursive=True)]
        resident = sum(process.memory_info().rss for process in processes if process.is_running())
        self._peak_rss_bytes = max(self._peak_rss_bytes, resident)
        self._sample(timestamp_ns, "MET023", resident, "byte", "server-process-tree")
        self._sample(timestamp_ns, "MET024", self._peak_rss_bytes, "byte", "server-process-tree")
        self._sample(
            timestamp_ns,
            "MET025",
            psutil.cpu_percent(interval=None) / 100,
            "ratio",
            "host",
        )
        self._sample(timestamp_ns, "MET053", psutil.virtual_memory().used, "byte", "host")

        locked_kib = 0
        numa_pages: dict[str, int] = defaultdict(int)
        page_size = os.sysconf("SC_PAGE_SIZE")
        for process in processes:
            status = Path(f"/proc/{process.pid}/status")
            numa_maps = Path(f"/proc/{process.pid}/numa_maps")
            try:
                for line in status.read_text().splitlines():
                    if line.startswith("VmLck:"):
                        locked_kib += int(line.split()[1])
                for line in numa_maps.read_text().splitlines():
                    for item in line.split():
                        if item.startswith("N") and "=" in item:
                            node, count = item.split("=", maxsplit=1)
                            if node[1:].isdigit() and count.isdigit():
                                numa_pages[node] += int(count)
            except (FileNotFoundError, PermissionError, psutil.NoSuchProcess):
                continue
        self.events.append(
            {
                "timestamp_ns": timestamp_ns,
                "event_type": "host-memory",
                "details_json": json.dumps(
                    {
                        "locked_bytes": locked_kib * 1024,
                        "numa_resident_bytes": {
                            node: pages * page_size for node, pages in sorted(numa_pages.items())
                        },
                    },
                    sort_keys=True,
                ),
            }
        )

    def _gpu_snapshot(self, timestamp_ns: int) -> None:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(GPU_TELEMETRY_QUERY_FIELDS)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        rows = [[field.strip() for field in line.split(",")] for line in result.stdout.splitlines()]
        if len(rows) != 4 or any(len(fields) != 9 for fields in rows):
            raise RuntimeError(f"Expected four complete nvidia-smi telemetry rows, received {rows}")
        if {fields[0] for fields in rows} != {"0", "1", "2", "3"}:
            raise RuntimeError(
                f"Unexpected nvidia-smi GPU indices: {[fields[0] for fields in rows]}"
            )
        for fields in rows:
            gpu = fields[0]
            power_limit_w: float | str
            try:
                numeric_power_limit_w = float(fields[4])
            except ValueError:
                # Preserve the raw value so the mandatory health gate can emit
                # an explicit invalidation instead of losing the entire sample.
                power_limit_w = fields[4]
            else:
                if not math.isfinite(numeric_power_limit_w):
                    # Keep telemetry.json standards-compliant while preserving
                    # the unreadable value for the health gate.
                    power_limit_w = fields[4]
                else:
                    power_limit_w = numeric_power_limit_w
            self._sample(timestamp_ns, "MET026", float(fields[1]) / 100, "ratio", f"gpu{gpu}")
            self._sample(
                timestamp_ns, "MET058", float(fields[2]) * 1024 * 1024, "byte", f"gpu{gpu}"
            )
            self._sample(timestamp_ns, "MET027", float(fields[3]), "W", f"gpu{gpu}")
            self._sample(timestamp_ns, "MET064", float(fields[5]), "Cel", f"gpu{gpu}")
            self._sample(timestamp_ns, "MET063", float(fields[6]) * 1_000_000, "Hz", f"gpu{gpu}")
            self.events.append(
                {
                    "timestamp_ns": timestamp_ns,
                    "event_type": "gpu-health",
                    "details_json": json.dumps(
                        {
                            "gpu_index": int(gpu),
                            "power_limit_w": power_limit_w,
                            "temperature_c": float(fields[5]),
                            "sm_clock_mhz": float(fields[6]),
                            "throttle_reasons": fields[7],
                            "uncorrected_volatile_ecc": int(fields[8]),
                        },
                        sort_keys=True,
                    ),
                }
            )

        try:
            pcie = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,pcie.rx_util,pcie.tx_util",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            for line in pcie.stdout.splitlines():
                fields = [field.strip() for field in line.split(",")]
                if len(fields) != 3:
                    continue
                interval_bytes = (
                    (float(fields[1]) + float(fields[2])) * 1024 * self.interval_seconds
                )
                self._sample(timestamp_ns, "MET059", interval_bytes, "byte", f"gpu{fields[0]}")
        except (ValueError, subprocess.SubprocessError) as error:
            if not self._pcie_unavailable_reported:
                self.events.append(
                    {
                        "timestamp_ns": timestamp_ns,
                        "event_type": "pcie-counter-unavailable",
                        "details_json": json.dumps({"error": str(error)}),
                    }
                )
                self._pcie_unavailable_reported = True

    def _load_snapshot(self, timestamp_ns: int) -> None:
        if not self.include_load:
            return
        snapshot = load_snapshot(BASE_URL, timeout=3)
        for index, state in enumerate(snapshot.get("loads", [])):
            if not isinstance(state, dict):
                continue
            for key, metric_id, unit in (
                ("num_running_reqs", "MET031", "count"),
                ("num_waiting_reqs", "MET032", "count"),
                ("token_usage", "MET041", "ratio"),
                ("cache_hit_rate", "MET043", "ratio"),
            ):
                value = state.get(key)
                if isinstance(value, (int, float)):
                    self._sample(timestamp_ns, metric_id, float(value), unit, f"scheduler{index}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            timestamp = time.time_ns()
            try:
                self._process_snapshot(timestamp)
                self._gpu_snapshot(timestamp)
                self._load_snapshot(timestamp)
            except Exception as error:
                self.events.append(
                    {
                        "timestamp_ns": timestamp,
                        "event_type": "collector-error",
                        "details_json": json.dumps({"error": str(error)}),
                    }
                )
            self._stop.wait(self.interval_seconds)


def _fake_encoder(text: str) -> list[int]:
    return [128 + byte for byte in text.encode()]


def _load_tokenizer() -> tuple[Callable[[str], list[int]], int, set[int]]:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH, trust_remote_code=True, local_files_only=True
    )

    def encode(text: str) -> list[int]:
        return [int(value) for value in tokenizer.encode(text, add_special_tokens=False)]

    special = {int(value) for value in tokenizer.all_special_ids}
    return encode, int(tokenizer.vocab_size), special


def _rows(results: Iterable[RequestResult]) -> list[dict[str, Any]]:
    return [result.row for result in results]


def _responses(results: Iterable[RequestResult]) -> list[dict[str, Any]]:
    return [result.response for result in results]


def _warmup(
    *,
    base_url: str,
    factory: Callable[[int], RequestSpec],
    concurrency: int,
    count: int,
) -> None:
    specs = [factory(-(index + 1)) for index in range(count)]
    results = run_count(base_url, specs, concurrency=concurrency)
    if not all(result.row["outcome"] == "complete" for result in results):
        raise RuntimeError("A warm-up request failed")


def _scoped_breakdown(rows: Sequence[dict[str, Any]], metric_id: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cell = str(row["load_cell_id"])
        if row["outcome"] != "complete" or not cell.startswith(("context-", "prefix-")):
            continue
        key = (
            str(row["content_family"]),
            int(row["target_context_tokens"]),
            int(row["target_concurrency"]),
            "shared-50-percent" if cell.startswith("prefix-") else "unique",
        )
        grouped[key].append(row)
    breakdown = []
    for (family, context, concurrency, prefix_mode), values in sorted(grouped.items()):
        if metric_id == "MET010":
            value = fmean(float(row["ttft_client_ms"]) for row in values)
        elif metric_id == "MET013":
            value = fmean(float(row["tpot_ms"]) for row in values)
        elif metric_id == "MET014":
            value = fmean(float(row["itl_mean_ms"]) for row in values)
        elif metric_id == "MET019":
            start = min(int(row["t0_ns"]) for row in values)
            end = max(int(row["t5_ns"]) for row in values)
            value = sum(int(row["output_tokens"]) for row in values) / max(
                (end - start) / 1e9, 1e-9
            )
        else:
            raise ValueError(f"Unsupported scoped metric: {metric_id}")
        breakdown.append(
            {
                "scope": {
                    "content_family": family,
                    "context_tokens": context,
                    "concurrency": concurrency,
                    "prefix_mode": prefix_mode,
                },
                "value": value,
            }
        )
    return breakdown


def _summarize(
    rows: Sequence[dict[str, Any]],
    *,
    breakdown_rows: Sequence[dict[str, Any]] | None = None,
    elapsed_seconds: float,
    readiness_ms: float,
    kv_capacity: int,
    slo_capacity: float,
    warmup_requests: int,
) -> dict[str, Any]:
    completed = [row for row in rows if row["outcome"] == "complete"]
    failed = [row for row in rows if row["outcome"] != "complete"]
    timed_out = [row for row in failed if row["outcome"] == "timeout"]
    ttft = [float(row["ttft_client_ms"]) for row in completed]
    tpot = [float(row["tpot_ms"]) for row in completed]
    itl = [float(row["itl_mean_ms"]) for row in completed]
    e2e = [float(row["e2e_ms"]) for row in completed]
    input_tokens = sum(int(row["input_tokens"]) for row in completed)
    output_tokens = sum(int(row["output_tokens"]) for row in completed)
    elapsed = max(elapsed_seconds, 1e-9)
    metrics = {
        "MET001": _metric(len(rows), "count"),
        "MET002": _metric(len(completed), "count"),
        "MET003": _metric(len(failed), "count"),
        "MET004": _metric(len(timed_out), "count"),
        "MET005": _metric(0, "count"),
        "MET006": _metric(0, "count"),
        "MET007": _metric(input_tokens, "token"),
        "MET008": _metric(output_tokens, "token"),
        "MET009": _metric(input_tokens + output_tokens, "token"),
        "MET010": _metric(fmean(ttft) if ttft else 0, "ms", ttft),
        "MET011": _metric(fmean(ttft) if ttft else 0, "ms", ttft),
        "MET012": _metric(
            fmean(float(row["queue_ms"]) for row in completed) if completed else 0, "ms"
        ),
        "MET013": _metric(fmean(tpot) if tpot else 0, "ms/token", tpot),
        "MET014": _metric(fmean(itl) if itl else 0, "ms", itl),
        "MET015": _metric(fmean(e2e) if e2e else 0, "ms", e2e),
        "MET016": _metric(len(rows) / elapsed, "request/s"),
        "MET017": _metric(len(completed) / elapsed, "request/s"),
        "MET018": _metric(input_tokens / elapsed, "token/s"),
        "MET019": _metric(output_tokens / elapsed, "token/s"),
        "MET020": _metric((input_tokens + output_tokens) / elapsed, "token/s"),
        "MET021": _metric(slo_capacity, "request/s"),
        "MET023": _metric(0, "byte"),
        "MET024": _metric(0, "byte"),
        "MET025": _metric(0, "ratio"),
        "MET028": _metric(len(failed) / len(rows) if rows else 0, "ratio"),
        "MET029": _metric(len(completed) / len(rows) if rows else 0, "ratio"),
        "MET030": _metric(
            fmean(float(row["quality_passed"]) for row in rows) if rows else 0, "ratio"
        ),
        "MET097": _metric(kv_capacity, "token"),
        "MET098": _metric(readiness_ms, "ms"),
        "MET099": _metric(slo_capacity, "request/s"),
    }
    scoped_rows = rows if breakdown_rows is None else breakdown_rows
    for metric_id in ("MET010", "MET013", "MET014", "MET019"):
        metrics[metric_id]["breakdown"] = _scoped_breakdown(scoped_rows, metric_id)
    return {
        "profile": "full",
        "warmup_requests": warmup_requests,
        "measurement_requests": len(rows),
        "elapsed_seconds": elapsed_seconds,
        "metrics": metrics,
    }


def _apply_sample_summaries(summary: dict[str, Any], samples: Sequence[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["metric_id"])].append(sample)
    for metric_id, records in grouped.items():
        units = {str(record["unit"]) for record in records}
        if len(units) != 1:
            raise RuntimeError(f"Telemetry unit mismatch for {metric_id}: {sorted(units)}")
        values = [float(record["value"]) for record in records]
        value = max(values) if metric_id == "MET024" else fmean(values)
        summary["metrics"][metric_id] = _metric(value, units.pop(), values)


def _instrumentation_summary(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    locked_bytes = []
    numa_bytes: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.get("event_type") != "host-memory":
            continue
        details = json.loads(str(event["details_json"]))
        locked_bytes.append(int(details.get("locked_bytes", 0)))
        for node, value in details.get("numa_resident_bytes", {}).items():
            numa_bytes[str(node)].append(int(value))
    return {
        "maximum_locked_host_bytes": max(locked_bytes, default=0),
        "maximum_process_tree_numa_resident_bytes": {
            node: max(values) for node, values in sorted(numa_bytes.items())
        },
    }


def _unexpected_gpu_processes(server_pid: int) -> list[dict[str, Any]]:
    root = psutil.Process(server_pid)
    allowed = {server_pid, *(process.pid for process in root.children(recursive=True))}
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    unexpected = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3 or not fields[0].isdigit():
            continue
        if int(fields[0]) not in allowed:
            unexpected.append(
                {"pid": int(fields[0]), "process_name": fields[1], "used_memory_mib": fields[2]}
            )
    return unexpected


def _measurement_health(
    *,
    collector: TelemetryCollector,
    server_pid: int,
    server_log: Path,
    expected_power_limits_w: dict[int, float],
) -> dict[str, Any]:
    errors = []
    if set(expected_power_limits_w) != set(range(4)) or any(
        not math.isfinite(value) or value <= 0 for value in expected_power_limits_w.values()
    ):
        raise ValueError("Expected power limits must define finite positive values for GPUs 0-3")
    gpu_events = [event for event in collector.events if event.get("event_type") == "gpu-health"]
    collection_errors = [
        event for event in collector.events if event.get("event_type") == "collector-error"
    ]
    cycle_timestamps = {
        int(event["timestamp_ns"])
        for event in [*gpu_events, *collection_errors]
        if event.get("timestamp_ns") is not None
    }
    collection_error_ratio = (
        len(collection_errors) / len(cycle_timestamps) if cycle_timestamps else 1.0
    )
    if not gpu_events:
        errors.append("No GPU health samples were recorded")
    if collection_error_ratio > 0.01:
        errors.append(f"Telemetry collection error ratio was {collection_error_ratio:.6f}")
    gpu_sample_counts: dict[int, int] = defaultdict(int)
    cycle_gpu_counts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    software_power_cap_counts: dict[int, int] = defaultdict(int)
    observed_power_limits: dict[int, list[float]] = defaultdict(list)
    mismatched_power_limit_counts: dict[int, int] = defaultdict(int)
    missing_power_limit_counts: dict[int, int] = defaultdict(int)
    unreadable_power_limit_counts: dict[int, int] = defaultdict(int)
    invalidating_clock_events: dict[int, set[int]] = defaultdict(set)
    for event in gpu_events:
        details = json.loads(str(event["details_json"]))
        gpu_index = int(details.get("gpu_index", -1))
        gpu_sample_counts[gpu_index] += 1
        cycle_gpu_counts[int(event["timestamp_ns"])][gpu_index] += 1
        throttle = str(details.get("throttle_reasons", "")).strip().casefold()
        try:
            throttle_mask = 0 if throttle in {"0", "not active", "none"} else int(throttle, base=0)
        except ValueError:
            errors.append(
                f"GPU {details.get('gpu_index')} returned an unreadable throttle mask: {throttle}"
            )
        else:
            if throttle_mask & SOFTWARE_POWER_CAP_THROTTLE_MASK:
                software_power_cap_counts[gpu_index] += 1
            invalidating_mask = throttle_mask & INVALIDATING_GPU_CLOCK_EVENT_MASK
            if invalidating_mask:
                invalidating_clock_events[gpu_index].add(invalidating_mask)
        power_limit = details.get("power_limit_w")
        if power_limit is None:
            missing_power_limit_counts[gpu_index] += 1
        else:
            try:
                numeric_power_limit = float(power_limit)
            except (TypeError, ValueError):
                unreadable_power_limit_counts[gpu_index] += 1
            else:
                if not math.isfinite(numeric_power_limit):
                    unreadable_power_limit_counts[gpu_index] += 1
                else:
                    observed_power_limits[gpu_index].append(numeric_power_limit)
                    expected_power_limit = expected_power_limits_w.get(gpu_index)
                    if expected_power_limit is None or not math.isclose(
                        numeric_power_limit,
                        expected_power_limit,
                        rel_tol=0.0,
                        abs_tol=POWER_LIMIT_TOLERANCE_W,
                    ):
                        mismatched_power_limit_counts[gpu_index] += 1
        if int(details.get("uncorrected_volatile_ecc", 0)) != 0:
            errors.append(f"GPU {gpu_index} reported a volatile uncorrected ECC error")
    for gpu_index, masks in sorted(invalidating_clock_events.items()):
        formatted_masks = ", ".join(f"0x{mask:x}" for mask in sorted(masks))
        errors.append(
            f"GPU {gpu_index} reported an invalidating hardware/thermal clock event: "
            f"{formatted_masks}"
        )
    for gpu_index, count in sorted(missing_power_limit_counts.items()):
        errors.append(
            f"GPU {gpu_index} omitted the mandatory configured power limit in {count} samples"
        )
    for gpu_index, count in sorted(unreadable_power_limit_counts.items()):
        errors.append(
            f"GPU {gpu_index} returned an unreadable configured power limit in {count} samples"
        )
    for gpu_index, count in sorted(mismatched_power_limit_counts.items()):
        values = observed_power_limits[gpu_index]
        expected_power_limit = expected_power_limits_w.get(gpu_index)
        errors.append(
            f"GPU {gpu_index} configured power limit differed from the preregistered "
            f"{expected_power_limit} W limit in {count}/{len(values)} readable samples "
            f"(observed range {min(values):.1f}-{max(values):.1f} W)"
        )
    incomplete_gpu_health_cycles = 0
    expected_gpu_indices = set(expected_power_limits_w)
    for timestamp_ns in cycle_timestamps:
        counts = cycle_gpu_counts.get(timestamp_ns, {})
        if set(counts) != expected_gpu_indices or any(count != 1 for count in counts.values()):
            incomplete_gpu_health_cycles += 1
    if incomplete_gpu_health_cycles:
        errors.append(
            f"Mandatory four-GPU health telemetry was incomplete in "
            f"{incomplete_gpu_health_cycles}/{len(cycle_timestamps)} collection cycles"
        )
    if not psutil.pid_exists(server_pid):
        errors.append("Server process exited during measurement")
        unexpected = []
    else:
        unexpected = _unexpected_gpu_processes(server_pid)
        if unexpected:
            errors.append(f"Unexpected competing GPU processes: {unexpected}")
    log_text = server_log.read_text(errors="replace")
    if re.search(r"\bXid\b", log_text, re.IGNORECASE):
        errors.append("Server log contains an NVIDIA Xid event")
    software_power_cap_by_gpu = {
        str(gpu_index): {
            "observation_count": sample_count,
            "count": software_power_cap_counts[gpu_index],
            "incidence": (
                software_power_cap_counts[gpu_index] / sample_count if sample_count else 0.0
            ),
        }
        for gpu_index in sorted(expected_power_limits_w)
        for sample_count in [gpu_sample_counts[gpu_index]]
    }
    power_limit_by_gpu = {}
    for gpu_index in sorted(expected_power_limits_w):
        values = observed_power_limits[gpu_index]
        power_limit_by_gpu[str(gpu_index)] = {
            "readable_observation_count": len(values),
            "mismatch_count": mismatched_power_limit_counts[gpu_index],
            "missing_count": missing_power_limit_counts[gpu_index],
            "unreadable_count": unreadable_power_limit_counts[gpu_index],
            "minimum_w": min(values) if values else None,
            "maximum_w": max(values) if values else None,
        }
    total_software_power_cap_samples = sum(software_power_cap_counts.values())
    return {
        "valid": not errors,
        "errors": errors,
        "gpu_health_events": len(gpu_events),
        "collection_errors": len(collection_errors),
        "collection_error_ratio": collection_error_ratio,
        "unexpected_gpu_processes": unexpected,
        "software_power_cap": {
            "nvml_mask": "0x4",
            "observation_count": len(gpu_events),
            "count": total_software_power_cap_samples,
            "incidence": (
                total_software_power_cap_samples / len(gpu_events) if gpu_events else 0.0
            ),
            "by_gpu": software_power_cap_by_gpu,
        },
        "configured_power_limit": {
            "expected_w_by_gpu": {
                str(index): value for index, value in sorted(expected_power_limits_w.items())
            },
            "tolerance_w": POWER_LIMIT_TOLERANCE_W,
            "missing_sample_count": sum(missing_power_limit_counts.values()),
            "unreadable_sample_count": sum(unreadable_power_limit_counts.values()),
            "incomplete_gpu_health_cycle_count": incomplete_gpu_health_cycles,
            "by_gpu": power_limit_by_gpu,
        },
    }


def _server_log_diagnostics(server_log: Path) -> dict[str, Any]:
    text = server_log.read_text(errors="replace")
    batch_sizes = [
        int(match.group(1))
        for match in re.finditer(r"#running-req:\s*([0-9]+)", text, re.IGNORECASE)
    ]
    return {
        "maximum_reported_running_batch": max(batch_sizes, default=0),
        "reported_running_batch_observations": len(batch_sizes),
        "preemption_log_mentions": len(re.findall(r"\bpreempt(?:ion|ed|ing)?\b", text, re.I)),
        "fallback_log_mentions": len(re.findall(r"\bfallback\b", text, re.I)),
    }


def _server_kv_capacity(info: dict[str, Any]) -> int:
    value = info.get("max_total_num_tokens")
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError("/server_info did not expose a positive max_total_num_tokens")
    states = info.get("internal_states", [])
    if states:
        memory = states[0].get("memory_usage", {})
        if memory.get("token_capacity") not in {None, value}:
            raise RuntimeError("Server KV capacity fields disagree")
    return value


def _case_tokens(
    text: str,
    *,
    target: int,
    seed: int,
    ordinal: int,
    encode: Callable[[str], list[int]],
) -> tuple[int, ...]:
    prefix = encode(f" correctness request {seed}-{ordinal} ")
    content = encode(text)
    if not content:
        raise RuntimeError("Correctness seed encoded to no tokens")
    values = (prefix * (32 // max(len(prefix), 1) + 1))[:32]
    remaining = target - len(values)
    values.extend((content * (remaining // len(content) + 1))[:remaining])
    if len(values) != target:
        raise AssertionError("Correctness request length mismatch")
    return tuple(values)


def correctness_specs(
    study_root: Path,
    *,
    seed: int,
    encode: Callable[[str], list[int]],
) -> list[RequestSpec]:
    cases = [
        json.loads(line)
        for line in (study_root / "inputs/correctness-cases.jsonl").read_text().splitlines()
        if line
    ]
    specs = []
    ordinal = 0
    for context in (1024, 8192, 32768, 131072):
        for batch_shape in (1, 8):
            for case in cases:
                text = f"{case['instruction']}\n\n{case['seed_text']}"
                request_id = f"correctness-{seed}-{context}-batch{batch_shape}-{case['id']}"
                specs.append(
                    RequestSpec(
                        request_id=request_id,
                        input_ids=_case_tokens(
                            text, target=context, seed=seed, ordinal=ordinal, encode=encode
                        ),
                        output_tokens=32,
                        request_class=f"correctness-batch-{batch_shape}",
                        load_cell_id=f"correctness-context-{context}-batch-{batch_shape}",
                        content_family=str(case["content_family"]),
                        target_context_tokens=context,
                        target_concurrency=batch_shape,
                    )
                )
                ordinal += 1
    return specs


def _run_correctness(base_url: str, specs: Sequence[RequestSpec]) -> list[RequestResult]:
    results = []
    for batch_shape in (1, 8):
        selected = [spec for spec in specs if spec.target_concurrency == batch_shape]
        results.extend(run_count(base_url, selected, concurrency=batch_shape))
    reconcile_request_ids(specs, _rows(results))
    return results


def _run_matrix(
    *,
    base_url: str,
    seed: int,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_ids: set[int],
    quick: bool = False,
) -> tuple[list[RequestResult], int, float]:
    results: list[RequestResult] = []
    warmup_total = 0
    measurement_seconds = 0.0
    cells = (
        [(1024, 1)]
        if quick
        else [
            (context, concurrency)
            for context, concurrencies in CONTEXT_CONCURRENCY.items()
            for concurrency in concurrencies
        ]
    )
    for context, concurrency in cells:

        def factory(
            ordinal: int,
            context: int = context,
            concurrency: int = concurrency,
        ) -> RequestSpec:
            family = CONTENT_FAMILIES[abs(ordinal) % len(CONTENT_FAMILIES)]
            request = matrix_request(
                context_tokens=context,
                concurrency=concurrency,
                family=family,
                seed=seed,
                ordinal=ordinal,
                encode=encode,
                vocab_size=vocab_size,
                special_token_ids=special_ids,
            )
            if quick:
                return RequestSpec(**{**request.__dict__, "output_tokens": 4})
            return request

        warmup_count = 1 if quick else max(32, 2 * concurrency)
        _warmup(base_url=base_url, factory=factory, concurrency=concurrency, count=warmup_count)
        warmup_total += warmup_count
        cell_started = time.monotonic()
        cell_results = run_fixed_concurrency(
            base_url,
            concurrency=concurrency,
            request_factory=factory,
            duration_seconds=0.01 if quick else 120,
            minimum_completions=1 if quick else (30 if context >= 32768 else 0),
            maximum_seconds=0.1 if quick else (300 if context >= 32768 else 120),
        )
        measurement_seconds += time.monotonic() - cell_started
        results.extend(cell_results)
    return results, warmup_total, measurement_seconds


def _slo_result(results: Sequence[RequestResult]) -> dict[str, Any]:
    rows = _rows(results)
    thresholds = {
        "context-8k": (2500.0, 50.0),
        "context-32k": (6000.0, 50.0),
        "context-128k": (20000.0, 60.0),
    }
    classes = {}
    enough = True
    passed = True
    for request_class, (ttft_limit, tpot_limit) in thresholds.items():
        selected = [row for row in rows if row["request_class"] == request_class]
        complete = [row for row in selected if row["outcome"] == "complete"]
        if len(selected) < MINIMUM_SLO_CLASS_OBSERVATIONS:
            enough = False
            classes[request_class] = {
                "observations": len(selected),
                "minimum_observations": MINIMUM_SLO_CLASS_OBSERVATIONS,
                "status": "insufficient",
            }
            continue
        success_rate = len(complete) / len(selected)
        error_rate = 1 - success_rate
        timeout_rate = sum(row["outcome"] == "timeout" for row in selected) / len(selected)
        ttft_p95 = (
            _percentile([float(row["ttft_client_ms"]) for row in complete], 0.95)
            if complete
            else None
        )
        tpot_p95 = (
            _percentile([float(row["tpot_ms"]) for row in complete], 0.95) if complete else None
        )
        class_pass = (
            bool(complete)
            and success_rate >= 0.99
            and error_rate <= 0.01
            and timeout_rate <= 0.01
            and ttft_p95 is not None
            and ttft_p95 <= ttft_limit
            and tpot_p95 is not None
            and tpot_p95 <= tpot_limit
        )
        classes[request_class] = {
            "observations": len(selected),
            "success_rate": success_rate,
            "error_rate": error_rate,
            "timeout_rate": timeout_rate,
            "p95_ttft_ms": ttft_p95,
            "p95_tpot_ms": tpot_p95,
            "passed": class_pass,
        }
        passed = passed and class_pass
    lag_ratio = (
        sum(result.scheduling_lag_seconds > 0.01 for result in results) / len(results)
        if results
        else 1.0
    )
    passed = passed and enough and lag_ratio <= 0.01
    return {
        "status": "pass" if passed else ("insufficient" if not enough else "fail"),
        "passed": passed,
        "classes": classes,
        "load_generator_scheduling_lag_ratio": lag_ratio,
    }


def _wait_for_queue_recovery(base_url: str, *, timeout_seconds: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_snapshot: dict[str, Any] = {}
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            last_snapshot = load_snapshot(base_url, timeout=5)
            loads = [item for item in last_snapshot.get("loads", []) if isinstance(item, dict)]
            empty = bool(loads) and all(
                int(item.get("num_running_reqs", -1)) == 0
                and int(item.get("num_waiting_reqs", -1)) == 0
                for item in loads
            )
            if empty:
                healthcheck(base_url, timeout=10)
                return {"recovered": True, "snapshot": last_snapshot, "error": None}
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(1)
    return {"recovered": False, "snapshot": last_snapshot, "error": last_error}


def _capacity_seed(seed: int, rate: float, *, stabilization: bool) -> int:
    rate_key = round(rate * 100_000_000)
    return seed ^ rate_key ^ (0x51A8 if stabilization else 0)


def _capacity_bisection_rate(low: float, high: float) -> float:
    if low <= 0 or not math.isfinite(high) or high <= low:
        raise ValueError(f"Invalid positive capacity bracket: low={low} high={high}")
    return math.sqrt(low * high)


def _capacity_search(
    *,
    base_url: str,
    seed: int,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_ids: set[int],
    progress_path: Path,
) -> tuple[float, list[RequestResult], list[dict[str, Any]], dict[str, Any]]:
    rate = CAPACITY_INITIAL_RATE
    passing: list[float] = []
    failing: list[float] = []
    all_results: list[RequestResult] = []
    points = []
    consecutive_failures = 0
    bisecting = False
    low = 0.0
    high = math.inf
    evidence_root = progress_path.parent / "capacity-point-evidence"
    for point_index in range(8):
        flush_cache(base_url)
        # Stabilization is sent and retained separately from the measurement evidence.
        stabilization = capacity_trace(
            rate=rate,
            duration_seconds=60,
            seed=_capacity_seed(seed, rate, stabilization=True),
            encode=encode,
            vocab_size=vocab_size,
            special_token_ids=special_ids,
        )
        stabilization_results = run_open_loop(base_url, stabilization)
        reconcile_request_ids(stabilization, _rows(stabilization_results))
        point_root = evidence_root / f"point-{point_index + 1}-{rate:.8f}"
        _write_json(
            point_root / "stabilization.json",
            {
                "excluded_from_analysis": True,
                "trace_fingerprint": trace_fingerprint(stabilization),
                "trace": [spec.public_record() for spec in stabilization],
                "rows": _rows(stabilization_results),
                "responses": _responses(stabilization_results),
            },
        )
        measurement = capacity_trace(
            rate=rate,
            duration_seconds=120,
            seed=_capacity_seed(seed, rate, stabilization=False),
            encode=encode,
            vocab_size=vocab_size,
            special_token_ids=special_ids,
        )
        result = run_open_loop(base_url, measurement)
        reconcile_request_ids(measurement, _rows(result))
        _write_json(
            point_root / "measurement.json",
            {
                "excluded_from_analysis": False,
                "trace_fingerprint": trace_fingerprint(measurement),
                "trace": [spec.public_record() for spec in measurement],
                "rows": _rows(result),
                "responses": _responses(result),
            },
        )
        slo = _slo_result(result)
        recovery = _wait_for_queue_recovery(base_url)
        slo["queue_recovery"] = recovery
        if not recovery["recovered"]:
            slo["passed"] = False
            slo["status"] = "fail"
        points.append(
            {
                "rate_request_per_second": rate,
                "trace_fingerprint": trace_fingerprint(measurement),
                **slo,
            }
        )
        all_results.extend(result)
        _write_json(progress_path, points)
        if slo["load_generator_scheduling_lag_ratio"] > 0.01:
            raise RuntimeError(
                "Load-generator dispatch lag exceeded 1 percent of offered requests; "
                f"partial capacity evidence retained at {progress_path}"
            )
        if slo["status"] == "pass":
            passing.append(rate)
            if bisecting:
                low = max(low, rate)
            else:
                consecutive_failures = 0
        elif slo["status"] == "fail":
            failing.append(rate)
            if bisecting:
                high = min(high, rate)
            else:
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    if not passing:
                        break
                    bisecting = True
                    low = max(passing)
                    high = min(value for value in failing if value > low)
        elif bisecting:
            # A point without every SLO class cannot qualify as capacity.
            high = min(high, rate)
        else:
            consecutive_failures = 0
        if bisecting:
            if relative_boundary_width(low, high) <= 0.10:
                break
            rate = _capacity_bisection_rate(low, high)
        else:
            rate *= 2
    capacity = max(passing) if passing else 0.0
    upper_candidates = [value for value in failing if value > capacity]
    upper = min(upper_candidates) if upper_candidates else math.inf
    width = relative_boundary_width(capacity, upper)
    boundary_resolved = math.isfinite(width) and width <= 0.10
    search = {
        "status": (
            "resolved"
            if boundary_resolved
            else "right-censored"
            if passing and not upper_candidates
            else "left-censored"
            if not passing and failing
            else "unresolved"
        ),
        "highest_qualifying_rate_request_per_second": capacity,
        "lowest_nonqualifying_rate_above_capacity_request_per_second": (
            upper if math.isfinite(upper) else None
        ),
        "boundary_relative_width": width if math.isfinite(width) else None,
        "boundary_resolved_within_10_percent": boundary_resolved,
        "tested_points": len(points),
        "maximum_points": 8,
    }
    return capacity, all_results, points, search


def _collector_policy_metadata() -> dict[str, Any]:
    return {
        "hardware_health_policy_version": HARDWARE_HEALTH_POLICY_VERSION,
        "gpu_telemetry_query_fields": list(GPU_TELEMETRY_QUERY_FIELDS),
        "collector_implementation_sha256": lifecycle_sha256_file(Path(__file__)),
    }


def _validate_retained_collector_policy(policy: dict[str, Any]) -> None:
    for key, expected_value in _collector_policy_metadata().items():
        if policy.get(key) != expected_value:
            raise RuntimeError(f"Retained collector pilot has a stale {key}")


def _collector_pilot(
    *,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_ids: set[int],
    work_dir: Path,
    server_pid: int,
) -> dict[str, Any]:
    throughputs: dict[str, list[float]] = {"off": [], "on": []}
    sequence = ("off", "on", "on", "off", "off", "on")
    for index, state in enumerate(sequence):
        flush_cache(BASE_URL)

        def factory(ordinal: int, window: int = index) -> RequestSpec:
            return matrix_request(
                context_tokens=1024,
                concurrency=8,
                family=CONTENT_FAMILIES[abs(ordinal) % len(CONTENT_FAMILIES)],
                seed=20260910 + window,
                ordinal=ordinal,
                encode=encode,
                vocab_size=vocab_size,
                special_token_ids=special_ids,
            )

        _warmup(base_url=BASE_URL, factory=factory, concurrency=8, count=16)
        collector = (
            TelemetryCollector(
                work_dir / f"window-{index}-{state}.json",
                server_pid=server_pid,
                interval_seconds=1,
            )
            if state == "on"
            else None
        )
        if collector:
            collector.start()
        started = time.monotonic()
        try:
            rows = run_fixed_concurrency(
                BASE_URL,
                concurrency=8,
                request_factory=factory,
                duration_seconds=30,
            )
        finally:
            elapsed = time.monotonic() - started
            if collector:
                collector.stop()
        throughputs[state].append(sum(result.row["output_tokens"] for result in rows) / elapsed)
    off = median(throughputs["off"])
    on = median(throughputs["on"])
    relative = (on - off) / off if off else None
    result = {
        **_collector_policy_metadata(),
        "sequence": list(sequence),
        "output_token_throughput": throughputs,
        "median_off": off,
        "median_on": on,
        "relative_effect": relative,
        "headline_collector_enabled": relative is not None and abs(relative) <= 0.01,
        "decision_rule": (
            "use one-second telemetry only when absolute median throughput change "
            "is at most 1 percent"
        ),
    }
    _write_json(work_dir / "result.json", result)
    return result


def _attempt_state(path: Path, **values: Any) -> None:
    current = load_data(path) if path.is_file() else {}
    if not isinstance(current, dict):
        current = {}
    current.update(values)
    _write_json(path, current)


def _completed_attempt(work_dir: Path, block: int, configuration: str) -> Path | None:
    attempts = work_dir / "attempts"
    if not attempts.is_dir():
        return None
    for state_path in sorted(attempts.glob(f"block-{block}-{configuration}*/attempt.json")):
        state = load_data(state_path)
        if not isinstance(state, dict) or state.get("status") != "candidate-complete":
            continue
        candidate = state.get("candidate")
        if isinstance(candidate, str) and Path(candidate).is_dir():
            return state_path.parent
    return None


def _new_attempt_directory(work_dir: Path, block: int, configuration: str) -> Path:
    base = work_dir / "attempts" / f"block-{block}-{configuration}"
    if not base.exists():
        return base
    retry = 1
    while (candidate := base.with_name(f"{base.name}-retry-{retry}")).exists():
        retry += 1
    return candidate


def _run_optional_probe(
    *,
    root: Path,
    work_dir: Path,
    encode: Callable[[str], list[int]],
    vocab_size: int,
    special_ids: set[int],
) -> None:
    output = work_dir / "optional-256k-probe"
    output.mkdir(parents=True, exist_ok=True)
    if (output / "result.json").is_file():
        return
    preflight(root, output / "preflight.json", verify_weights=False)
    server = None
    try:
        server, _, treatment, readiness_ms = launch_server(
            configuration="CFG023", work_dir=output / "server", telemetry=False
        )
        spec = RequestSpec(
            request_id="optional-256k-host-prefetch",
            input_ids=exact_content_tokens(
                family="natural_language",
                target_tokens=262144,
                seed=20260910,
                ordinal=0,
                encode=encode,
                vocab_size=vocab_size,
                special_token_ids=special_ids,
            ),
            output_tokens=64,
            request_class="feasibility-256k",
            load_cell_id="optional-context-262144-concurrency-1",
            content_family="natural_language",
            target_context_tokens=262144,
            target_concurrency=1,
        )
        result = run_count(BASE_URL, [spec], concurrency=1)[0]
        _write_json(
            output / "result.json",
            {
                "status": "feasible" if result.row["outcome"] == "complete" else "failed",
                "confirmatory": False,
                "configuration": "CFG023",
                "treatment_resolution": treatment,
                "readiness_ms": readiness_ms,
                "request": spec.public_record(),
                "measurement": result.row,
                "response": result.response,
            },
        )
    finally:
        if server:
            server.stop()


def _revalidate_retained_treatment_pilot(
    configuration: str, result_path: Path
) -> dict[str, Any] | None:
    attempt_root = result_path.parent
    retained = load_data(result_path)
    if not isinstance(retained, dict) or retained.get("status") != "pass":
        return None
    preflight_path = attempt_root / "preflight.json"
    preflight_data = load_data(preflight_path) if preflight_path.is_file() else None
    server_root = attempt_root / "server"
    info_path = server_root / "server-info.json"
    info = load_data(info_path) if info_path.is_file() else None
    log_path = server_root / "server.log"
    errors: list[str] = []
    if retained.get("configuration") != configuration:
        errors.append("retained configuration identity mismatch")
    readiness_ms = retained.get("readiness_ms")
    valid_readiness_ms: float | None = None
    if not isinstance(readiness_ms, (int, float)) or not math.isfinite(readiness_ms):
        errors.append("retained readiness is missing or non-finite")
    else:
        valid_readiness_ms = float(readiness_ms)
    if not isinstance(preflight_data, dict):
        errors.append("missing retained preflight")
    else:
        for section in ("hardware", "model", "runtime"):
            value = preflight_data.get(section)
            if not isinstance(value, dict) or value.get("valid") is not True:
                errors.append(f"retained {section} preflight is not valid")
    if not isinstance(info, dict):
        errors.append("missing retained server info")
        info = {}
    if not log_path.is_file():
        errors.append("missing retained server log")
        log_text = ""
    else:
        log_text = log_path.read_text(errors="replace")
    treatment = resolve_treatment(configuration, log_text)
    server_configuration = resolved_server_configuration(info)
    if not treatment["valid"]:
        errors.append("retained treatment no longer passes the current resolver")
    if not server_configuration["valid"]:
        errors.append("retained server configuration no longer matches the frozen contract")
    validation = {
        "status": "pass" if not errors else "fail",
        "configuration": configuration,
        "errors": errors,
        "treatment_resolution": treatment,
        "server_configuration": server_configuration,
    }
    _write_json(attempt_root / "resume-validation.json", validation)
    if errors:
        return None
    assert valid_readiness_ms is not None
    return {
        "status": "pass",
        "configuration": configuration,
        "readiness_ms": valid_readiness_ms,
        "available_kv_cache_tokens": _server_kv_capacity(info),
        "treatment_resolution": treatment,
    }


def _run_treatment_resolution_pilots(root: Path, work_dir: Path) -> dict[str, Any]:
    pilot_root = work_dir / "treatment-resolution-pilots"
    summary_path = pilot_root / "summary.json"
    retained_passes = list(pilot_root.glob("*/attempt-*/result.json"))
    if retained_passes:
        preflight(root, pilot_root / "resume-preflight.json", verify_weights=False)

    results: list[dict[str, Any]] = []
    for configuration in ("CFG021", "CFG022", "CFG023"):
        configuration_root = pilot_root / configuration
        retained_result = None
        for prior_result_path in sorted(configuration_root.glob("attempt-*/result.json")):
            retained_result = _revalidate_retained_treatment_pilot(configuration, prior_result_path)
            if retained_result is not None:
                break
        if retained_result is not None:
            results.append(retained_result)
            continue

        attempt_number = 1
        while (attempt_root := configuration_root / f"attempt-{attempt_number}").exists():
            attempt_number += 1
        result_path = attempt_root / "result.json"

        server = None
        try:
            preflight(
                root,
                attempt_root / "preflight.json",
                verify_weights=False,
            )
            server, info, treatment, readiness_ms = launch_server(
                configuration=configuration,
                work_dir=attempt_root / "server",
                telemetry=False,
            )
            result = {
                "status": "pass",
                "configuration": configuration,
                "readiness_ms": readiness_ms,
                "available_kv_cache_tokens": _server_kv_capacity(info),
                "treatment_resolution": treatment,
            }
            _write_json(result_path, result)
            results.append(result)
        except BaseException as error:
            _write_json(
                result_path,
                {
                    "status": "fail",
                    "configuration": configuration,
                    "error": f"{type(error).__name__}: {error}",
                },
            )
            raise
        finally:
            if server:
                server.stop()

    summary = {
        "status": "pass",
        "policy": "all requested treatments must resolve before any measurement",
        "results": results,
    }
    _write_json(summary_path, summary)
    return summary


def _run_quick(work_dir: Path) -> Path:
    encode = _fake_encoder
    results, warmups, matrix_seconds = _run_matrix(
        base_url=BASE_URL,
        seed=41001,
        encode=encode,
        vocab_size=100_256,
        special_ids=set(),
        quick=True,
    )
    quality = evaluate_engram_equivalence(_responses(results), _responses(results))
    summary = _summarize(
        _rows(results),
        elapsed_seconds=max(matrix_seconds, 1e-3),
        readiness_ms=0.0,
        kv_capacity=1_000_000,
        slo_capacity=0.0,
        warmup_requests=warmups,
    )
    summary["profile"] = "quick"
    draft = RunDraft(
        run_id="R0000",
        directory_name="quick-fake-server",
        experiment="atlas://experiment/E0013@v1",
        configuration="atlas://configuration/CFG021@v1",
        runtime="atlas://runtime/RT004@v1",
        hardware="atlas://hardware/HW002@v1",
        quality_gate="Q0",
        replicate=1,
        seed=41001,
        started_at=utc_now(),
        ended_at=utc_now(),
        requests=_rows(results),
        samples=[process_sample("MET023", 0, "byte")],
        responses=_responses(results),
        quality_results=quality,
        quality_passed=bool(quality["passed"]),
        summary=summary,
        input_fingerprints={
            "synthetic-quick-trace": trace_fingerprint(
                [
                    matrix_request(
                        context_tokens=1024,
                        concurrency=1,
                        family="natural_language",
                        seed=41001,
                        ordinal=0,
                        encode=encode,
                        vocab_size=100_256,
                        special_token_ids=set(),
                    )
                ]
            )
        },
        artifact_checksums={
            "fake-server": lifecycle_sha256_file(Path(__file__).with_name("s004_fake_server.py"))
        },
        command=["atlas", "execution", "run", "S004", "sglang-b200", "--profile", "quick"],
        environment=[{"name": "backend", "value": "fake-server", "redacted": False}],
    )
    return write_run_draft(work_dir, draft)


def _run_full(work_dir: Path) -> None:
    aiperf_binary = Path(os.environ.get("ATLAS_S004_AIPERF_BIN", str(AIPERF_DEFAULT_BINARY)))
    aiperf_version = verify_aiperf(aiperf_binary)
    root = repository_root()
    preregistration = verify_preregistration_pushed(root)
    _write_json(work_dir / "preregistration-gate.json", preregistration)
    preflight_data = preflight(root, work_dir / "full-preflight.json", verify_weights=True)
    encode, vocab_size, special_ids = _load_tokenizer()
    study_root = root / "studies/S004-deepseek-v41-engram-placement/v1"
    fixed_correctness = correctness_specs(study_root, seed=20260910, encode=encode)
    _run_treatment_resolution_pilots(root, work_dir)

    # Preserve the original pilot, whose telemetry query did not sample
    # power.limit. The amendment changes the collector itself, so its overhead
    # decision must be established by a fresh, versioned pilot.
    pilot_root = work_dir / "collector-pilot-amendment-001"
    reference_path = pilot_root / "device-correctness-reference.json"
    pilot_result_path = pilot_root / "result.json"
    if reference_path.is_file() and pilot_result_path.is_file():
        global_reference = load_data(reference_path)
        collector_policy = load_data(pilot_result_path)
        if not isinstance(global_reference, list) or not isinstance(collector_policy, dict):
            raise RuntimeError("Retained collector pilot is malformed")
        _validate_retained_collector_policy(collector_policy)
    else:
        pilot_server, _, _, _ = launch_server(
            configuration="CFG021", work_dir=pilot_root / "server", telemetry=False
        )
        try:
            reference = _run_correctness(BASE_URL, fixed_correctness)
            global_reference = _responses(reference)
            reference_quality = evaluate_engram_equivalence(global_reference, global_reference)
            if not reference_quality["passed"]:
                raise RuntimeError("Device-mode correctness reference failed its self-check")
            _write_json(reference_path, global_reference)
            collector_policy = _collector_pilot(
                encode=encode,
                vocab_size=vocab_size,
                special_ids=special_ids,
                work_dir=pilot_root,
                server_pid=pilot_server.process.pid,
            )
        finally:
            pilot_server.stop()

    for block, (seed, order) in enumerate(zip(SEEDS, CONFIGURATION_ORDER, strict=True), start=1):
        block_correctness = fixed_correctness
        for configuration in order:
            completed = _completed_attempt(work_dir, block, configuration)
            if completed is not None:
                continue
            attempt = _new_attempt_directory(work_dir, block, configuration)
            attempt.mkdir(parents=True, exist_ok=False)
            state_path = attempt / "attempt.json"
            _attempt_state(
                state_path,
                status="starting",
                block=block,
                seed=seed,
                configuration=configuration,
                started_at=utc_now(),
            )
            server = None
            collector = None
            try:
                attempt_preflight = preflight(
                    root,
                    attempt / "preflight-before-server.json",
                    verify_weights=False,
                )
                server, info, treatment, readiness_ms = launch_server(
                    configuration=configuration,
                    work_dir=attempt / "server",
                    telemetry=False,
                )
                _attempt_state(
                    state_path,
                    status="treatment-resolved",
                    treatment=treatment,
                    readiness_ms=readiness_ms,
                )
                correctness = _run_correctness(BASE_URL, block_correctness)
                candidate_responses = _responses(correctness)
                quality = evaluate_engram_equivalence(candidate_responses, global_reference)
                _write_json(attempt / "quality.json", quality)
                if not quality["passed"]:
                    raise RuntimeError(
                        "Q0 exact-output equivalence failed before performance measurement"
                    )

                aiperf_validation: dict[str, Any] | None = None
                if block == 1:
                    crosscheck_specs = [
                        matrix_request(
                            context_tokens=32768,
                            concurrency=8,
                            family=CONTENT_FAMILIES[ordinal % len(CONTENT_FAMILIES)],
                            seed=seed,
                            ordinal=ordinal,
                            encode=encode,
                            vocab_size=vocab_size,
                            special_token_ids=special_ids,
                        )
                        for ordinal in range(CROSSCHECK_REQUESTS)
                    ]
                    flush_cache(BASE_URL)
                    atlas_crosscheck = run_count(
                        BASE_URL,
                        crosscheck_specs,
                        concurrency=CROSSCHECK_CONCURRENCY,
                    )
                    reconcile_request_ids(crosscheck_specs, _rows(atlas_crosscheck))
                    if any(result.row["outcome"] != "complete" for result in atlas_crosscheck):
                        raise RuntimeError(
                            "Atlas client failed the independent-driver cross-check trace"
                        )
                    flush_cache(BASE_URL)
                    try:
                        aiperf_result = run_aiperf(
                            binary=aiperf_binary,
                            base_url=BASE_URL,
                            model=MODEL_PATH,
                            specs=crosscheck_specs,
                            output_dir=attempt / "aiperf-crosscheck",
                            random_seed=20260910,
                        )
                    finally:
                        flush_cache(BASE_URL)
                    _write_json(
                        attempt / "aiperf-crosscheck" / "atlas-client-rows.json",
                        _rows(atlas_crosscheck),
                    )
                    aiperf_validation = compare_aiperf_summary(
                        _rows(atlas_crosscheck),
                        aiperf_result["summary"],
                    )
                    _write_json(
                        attempt / "aiperf-crosscheck" / "agreement.json",
                        aiperf_validation,
                    )
                    if not aiperf_validation["headline_eligible"]:
                        raise RuntimeError(
                            "Independent AIPerf validation disagreed with the Atlas client; "
                            "headline execution is blocked pending investigation"
                        )

                collector = TelemetryCollector(
                    attempt / "telemetry.json",
                    server_pid=server.process.pid,
                    interval_seconds=(1 if collector_policy["headline_collector_enabled"] else 10),
                )
                collector.start()
                telemetry_samples: list[dict[str, Any]] = []
                telemetry_events: list[dict[str, Any]] = []
                measurement_started_at = utc_now()
                matrix, warmups, matrix_seconds = _run_matrix(
                    base_url=BASE_URL,
                    seed=seed,
                    encode=encode,
                    vocab_size=vocab_size,
                    special_ids=special_ids,
                )

                def prefix_factory(ordinal: int, run_seed: int = seed) -> RequestSpec:
                    return matrix_request(
                        context_tokens=32768,
                        concurrency=8,
                        family=CONTENT_FAMILIES[abs(ordinal) % 3],
                        seed=run_seed,
                        ordinal=ordinal,
                        encode=encode,
                        vocab_size=vocab_size,
                        special_token_ids=special_ids,
                        repeated_prefix=True,
                    )

                flush_cache(BASE_URL)
                _warmup(base_url=BASE_URL, factory=prefix_factory, concurrency=8, count=32)
                prefix = run_fixed_concurrency(
                    BASE_URL,
                    concurrency=8,
                    request_factory=prefix_factory,
                    duration_seconds=120,
                )
                capacity, capacity_results, capacity_points, capacity_search = _capacity_search(
                    base_url=BASE_URL,
                    seed=seed,
                    encode=encode,
                    vocab_size=vocab_size,
                    special_ids=special_ids,
                    progress_path=attempt / "capacity-points.json",
                )
                if collector:
                    collector.stop()
                    telemetry_samples = collector.samples
                    telemetry_events = collector.events
                measurement_ended_at = utc_now()
                performance = matrix + prefix + capacity_results
                rows = _rows(performance)
                if not rows or any(not math.isfinite(float(row["e2e_ms"])) for row in rows):
                    raise RuntimeError("Mandatory request evidence is missing or non-finite")
                request_ids = [str(row["request_id"]) for row in rows]
                if len(request_ids) != len(set(request_ids)):
                    raise RuntimeError(
                        "Combined measurement evidence contains duplicate request IDs"
                    )
                summary = _summarize(
                    _rows(matrix),
                    breakdown_rows=_rows(matrix + prefix),
                    elapsed_seconds=matrix_seconds,
                    readiness_ms=readiness_ms,
                    kv_capacity=_server_kv_capacity(info),
                    slo_capacity=capacity,
                    warmup_requests=warmups + 32,
                )
                _apply_sample_summaries(summary, telemetry_samples)
                health = _measurement_health(
                    collector=collector,
                    server_pid=server.process.pid,
                    server_log=server.log_path,
                    expected_power_limits_w={
                        int(index): float(value)
                        for index, value in attempt_preflight["hardware"][
                            "expected_power_limits_w"
                        ].items()
                    },
                )
                if not health["valid"]:
                    raise RuntimeError(
                        "Measurement invalidation conditions were observed: "
                        + "; ".join(health["errors"])
                    )
                summary.update(
                    {
                        "capacity_points": capacity_points,
                        "capacity_search": capacity_search,
                        "evidence_request_counts": {
                            "controlled_matrix": len(matrix),
                            "repeated_prefix_probe": len(prefix),
                            "capacity_search": len(capacity_results),
                        },
                        "collector_policy": collector_policy,
                        "treatment_resolution": treatment,
                        "measurement_health": health,
                        "instrumentation": _instrumentation_summary(telemetry_events),
                        "server_log_diagnostics": _server_log_diagnostics(server.log_path),
                        "runtime_package_manifest_sha256": preflight_data["runtime"][
                            "package_manifest_sha256"
                        ],
                    }
                )
                if aiperf_validation is not None:
                    summary["independent_load_generator_validation"] = {
                        **aiperf_validation,
                        "payload_sha256": aiperf_result["payload_sha256"],
                        "aiperf_version_verified": aiperf_version,
                    }
                draft = RunDraft(
                    run_id="R0000",
                    directory_name=f"block-{block}-{configuration}",
                    experiment="atlas://experiment/E0013@v1",
                    configuration=f"atlas://configuration/{configuration}@v1",
                    runtime="atlas://runtime/RT004@v1",
                    hardware="atlas://hardware/HW002@v1",
                    quality_gate="Q0",
                    replicate=block,
                    seed=seed,
                    started_at=str(_attempt_state_time(state_path, "started_at")),
                    ended_at=utc_now(),
                    measurement_started_at=measurement_started_at,
                    measurement_ended_at=measurement_ended_at,
                    requests=rows,
                    samples=telemetry_samples,
                    events=telemetry_events,
                    responses=candidate_responses,
                    quality_results=quality,
                    quality_passed=True,
                    summary=summary,
                    input_fingerprints={
                        "trace-spec.yaml": sha256_file(study_root / "inputs/trace-spec.yaml"),
                        "correctness-cases.jsonl": sha256_file(
                            study_root / "inputs/correctness-cases.jsonl"
                        ),
                        "correctness-trace": trace_fingerprint(block_correctness),
                    },
                    artifact_checksums={
                        "model-manifest": str(preflight_data["model"]["aggregate_sha256"]),
                        "trace-generator": lifecycle_sha256_file(
                            Path(__file__).with_name("s004_trace.py")
                        ),
                        "sglang-treatment-source-files": str(
                            preflight_data["runtime"]["treatment_source_fingerprint"]
                        ),
                        "runtime-package-manifest": str(
                            preflight_data["runtime"]["package_manifest_sha256"]
                        ),
                    },
                    command=[
                        "atlas",
                        "execution",
                        "run",
                        "S004",
                        "sglang-b200",
                        "--profile",
                        "full",
                    ],
                    environment=[
                        {"name": name, "value": value, "redacted": False}
                        for name, value in {
                            **CONDITION_ENVIRONMENT[configuration],
                            "configuration": configuration,
                            "atlas_git_head": str(preregistration["head"]),
                        }.items()
                    ],
                )
                candidate = write_run_draft(work_dir / "candidates", draft)
                collector = None
                _attempt_state(
                    state_path,
                    status="candidate-complete",
                    candidate=str(candidate),
                    ended_at=utc_now(),
                )
            except BaseException as error:
                if collector:
                    collector.stop()
                _attempt_state(
                    state_path,
                    status="failed-or-invalid",
                    error=f"{type(error).__name__}: {error}",
                    ended_at=utc_now(),
                )
                raise
            finally:
                if server:
                    server.stop()

    _run_optional_probe(
        root=root,
        work_dir=work_dir,
        encode=encode,
        vocab_size=vocab_size,
        special_ids=special_ids,
    )


def _attempt_state_time(path: Path, key: str) -> str:
    data = load_data(path)
    if not isinstance(data, dict) or not isinstance(data.get(key), str):
        raise RuntimeError(f"Attempt state has no {key}")
    return str(data[key])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("quick", "full"), required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.profile == "quick":
        _run_quick(args.work_dir)
    else:
        _run_full(args.work_dir)


if __name__ == "__main__":
    main()
