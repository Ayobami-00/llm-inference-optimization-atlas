from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import pairwise
from statistics import fmean
from typing import Any

from atlas.studies.runners.s004_trace import RequestSpec


@dataclass(frozen=True)
class RequestResult:
    row: dict[str, Any]
    response: dict[str, Any]
    token_timestamps_ns: tuple[int, ...]
    scheduling_lag_seconds: float


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read())
    if not isinstance(data, dict):
        raise ValueError(f"Expected object response from {url}")
    return data


def _status_request(url: str, *, timeout: float = 30) -> None:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # SGLang's health endpoint deliberately returns an empty 200 response.
        response.read()


def healthcheck(base_url: str, *, timeout: float = 30) -> dict[str, Any]:
    _status_request(f"{base_url}/health_generate", timeout=timeout)
    return _json_request(f"{base_url}/server_info", timeout=timeout)


def load_snapshot(base_url: str, *, timeout: float = 30) -> dict[str, Any]:
    return _json_request(f"{base_url}/v1/loads?include=core,memory", timeout=timeout)


def flush_cache(base_url: str, *, timeout: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/flush_cache?timeout={timeout}",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout + 5) as response:
        body = response.read().decode(errors="replace")
        return {"status": int(response.status), "body": body}


def _token_ids(payload: dict[str, Any]) -> list[int]:
    direct = payload.get("output_ids")
    if isinstance(direct, list):
        return [int(value) for value in direct]
    meta = payload.get("meta_info")
    if isinstance(meta, dict):
        values = meta.get("output_token_logprobs")
        if isinstance(values, list):
            result = []
            for value in values:
                if isinstance(value, (list, tuple)) and len(value) > 1:
                    result.append(int(value[1]))
            return result
    return []


def _append_new_token_times(
    current: list[int], observed: list[int], timestamps: list[int], timestamp_ns: int
) -> list[int]:
    if len(observed) < len(current) or observed[: len(current)] != current:
        # Some endpoints stream token deltas instead of cumulative output IDs.
        current = current + observed
        timestamps.extend([timestamp_ns] * len(observed))
        return current
    added = len(observed) - len(current)
    if added:
        timestamps.extend([timestamp_ns] * added)
    return observed


def send_request(base_url: str, spec: RequestSpec, *, timeout: float = 360) -> RequestResult:
    payload = {
        "rid": spec.request_id,
        "input_ids": list(spec.input_ids),
        "sampling_params": {
            "temperature": 0,
            "top_p": 1,
            "top_k": 1,
            "max_new_tokens": spec.output_tokens,
            "ignore_eos": True,
        },
        "stream": True,
    }
    request = urllib.request.Request(
        f"{base_url}/generate",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    t0_ns = time.monotonic_ns()
    token_times: list[int] = []
    output_ids: list[int] = []
    final: dict[str, Any] = {}
    error: str | None = None
    timed_out = False
    status = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type:
                final = json.loads(response.read())
                output_ids = _token_ids(final)
                token_times = [time.monotonic_ns()] * len(output_ids)
            else:
                for raw in response:
                    line = raw.decode(errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    body = line.removeprefix("data:").strip()
                    if body == "[DONE]":
                        break
                    chunk = json.loads(body)
                    if not isinstance(chunk, dict):
                        continue
                    now_ns = time.monotonic_ns()
                    observed = _token_ids(chunk)
                    output_ids = _append_new_token_times(output_ids, observed, token_times, now_ns)
                    final = chunk
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        timed_out = isinstance(exc, TimeoutError) or isinstance(
            getattr(exc, "reason", None), TimeoutError
        )
    t5_ns = time.monotonic_ns()

    meta = final.get("meta_info", {}) if isinstance(final, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    completion_tokens = int(meta.get("completion_tokens", len(output_ids)))
    complete = (
        error is None
        and status == 200
        and completion_tokens == spec.output_tokens
        and len(output_ids) == spec.output_tokens
    )
    ttft_ms = (token_times[0] - t0_ns) / 1e6 if token_times else None
    itls_ms = [(right - left) / 1e6 for left, right in pairwise(token_times)]
    e2e_ms = (t5_ns - t0_ns) / 1e6
    tpot_ms = fmean(itls_ms) if itls_ms else 0.0
    ordered_itls = sorted(itls_ms)
    itl_p95 = (
        ordered_itls[min(len(ordered_itls) - 1, math.ceil(0.95 * len(ordered_itls)) - 1)]
        if ordered_itls
        else 0.0
    )
    queue_ms = float(meta.get("queue_time", 0.0)) * 1000
    outcome = "complete" if complete else "failed"
    if timed_out:
        outcome = "timeout"
    row = {
        "request_id": spec.request_id,
        "request_class": spec.request_class,
        "outcome": outcome,
        "t0_ns": t0_ns,
        "t5_ns": t5_ns,
        "input_tokens": len(spec.input_ids),
        "output_tokens": len(output_ids),
        "ttft_client_ms": ttft_ms,
        "tpot_ms": tpot_ms,
        "itl_mean_ms": tpot_ms,
        "itl_p95_ms": itl_p95,
        "e2e_ms": e2e_ms,
        "queue_ms": queue_ms,
        "quality_passed": complete,
        "retry_count": 0,
        "slo_eligible": spec.target_offered_rate is not None,
        "token_timestamps_ns": token_times,
        "load_cell_id": spec.load_cell_id,
        "content_family": spec.content_family,
        "target_context_tokens": spec.target_context_tokens,
        "target_concurrency": spec.target_concurrency,
        "target_offered_rate": spec.target_offered_rate,
    }
    response_record = {
        "request_id": spec.request_id,
        "outcome": row["outcome"],
        "output_token_ids": output_ids,
        "completion_tokens": completion_tokens,
        "finish_reason": meta.get("finish_reason"),
        "cached_tokens": meta.get("cached_tokens", 0),
        "finite": all(math.isfinite(value) for value in (e2e_ms,)) and bool(token_times),
        "malformed": not isinstance(final, dict) or not output_ids,
        "unexpected_fallback": False,
        "http_status": status,
        "error": error,
    }
    return RequestResult(row, response_record, tuple(token_times), 0.0)


def run_fixed_concurrency(
    base_url: str,
    *,
    concurrency: int,
    request_factory: Callable[[int], RequestSpec],
    duration_seconds: float,
    minimum_completions: int = 0,
    maximum_seconds: float | None = None,
    timeout: float = 360,
) -> list[RequestResult]:
    if concurrency < 1:
        raise ValueError("Concurrency must be positive")
    maximum = maximum_seconds or duration_seconds
    started = time.monotonic()
    ordinal = 0
    futures: set[Future[RequestResult]] = set()
    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(concurrency):
            futures.add(
                pool.submit(send_request, base_url, request_factory(ordinal), timeout=timeout)
            )
            ordinal += 1
        while futures:
            future = next(as_completed(futures))
            futures.remove(future)
            results.append(future.result())
            elapsed = time.monotonic() - started
            continue_measurement = elapsed < duration_seconds or (
                len(results) < minimum_completions and elapsed < maximum
            )
            if continue_measurement:
                futures.add(
                    pool.submit(send_request, base_url, request_factory(ordinal), timeout=timeout)
                )
                ordinal += 1
    return results


def run_count(
    base_url: str,
    specs: Sequence[RequestSpec],
    *,
    concurrency: int,
    timeout: float = 360,
) -> list[RequestResult]:
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(send_request, base_url, spec, timeout=timeout) for spec in specs]
        return [future.result() for future in futures]


def run_open_loop(
    base_url: str,
    specs: Sequence[RequestSpec],
    *,
    timeout: float = 360,
    maximum_workers: int = 1024,
) -> list[RequestResult]:
    started = time.monotonic()
    future_deadlines: dict[Future[RequestResult], float] = {}
    workers = max(1, min(maximum_workers, len(specs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for spec in specs:
            offset = float(spec.scheduled_offset_seconds or 0.0)
            deadline = started + offset
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            future_deadlines[pool.submit(send_request, base_url, spec, timeout=timeout)] = deadline
        results = []
        for future in as_completed(future_deadlines):
            item = future.result()
            actual_start = int(item.row["t0_ns"]) / 1e9
            lag = max(0.0, actual_start - future_deadlines[future])
            row = {**item.row, "scheduling_lag_ms": lag * 1000}
            results.append(RequestResult(row, item.response, item.token_timestamps_ns, lag))
    return sorted(results, key=lambda item: item.row["t0_ns"])
