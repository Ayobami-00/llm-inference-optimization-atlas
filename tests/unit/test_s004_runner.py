from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import atlas.studies.runners.s004_client as s004_client
import atlas.studies.runners.s004_lifecycle as s004_lifecycle
from atlas.studies.runners.s004 import (
    EXPECTED_GPU_POWER_LIMIT_W,
    INVALIDATING_GPU_CLOCK_EVENT_MASK,
    MINIMUM_SLO_CLASS_OBSERVATIONS,
    SOFTWARE_POWER_CAP_THROTTLE_MASK,
    THERMAL_OR_POWER_THROTTLE_MASK,
    TelemetryCollector,
    _capacity_bisection_rate,
    _collector_policy_metadata,
    _completed_attempt,
    _measurement_health,
    _new_attempt_directory,
    _run_treatment_resolution_pilots,
    _scoped_breakdown,
    _slo_result,
    _validate_retained_collector_policy,
)
from atlas.studies.runners.s004_aiperf import (
    AIPERF_VERSION,
    CROSSCHECK_REQUESTS,
    aiperf_payload,
    compare_aiperf_summary,
)
from atlas.studies.runners.s004_client import RequestResult, run_open_loop
from atlas.studies.runners.s004_client import healthcheck as client_healthcheck
from atlas.studies.runners.s004_lifecycle import (
    EXPECTED_RUNTIME_FILES,
    EXPECTED_SERVER_CONFIGURATION,
    EXPECTED_TREATMENT_SOURCE_FINGERPRINT,
    expected_gpu_power_limits,
    hardware_snapshot,
    host_memory_snapshot,
    resolve_treatment,
    resolved_server_configuration,
    server_command,
    treatment_source_fingerprint,
    verify_model_manifest,
    wait_for_gpu_release,
)
from atlas.studies.runners.s004_trace import (
    capacity_trace,
    exact_content_tokens,
    matrix_request,
    poisson_offsets,
    reconcile_request_ids,
    trace_fingerprint,
)
from atlas.utilities.serialization import yaml_writer

_PINNED_HOST_LOG = "\n".join(
    f"[test TP{rank} EP{rank}] engram host table layer {layer}: "
    "layout=shared, 1 MiB resident, pinned"
    for rank in range(4)
    for layer in (1, 14)
)
_PREFETCH_LOG = "\n".join(
    f"[test TP{rank} EP{rank}] Engram layer 14 KV prefetch enabled for BS=1 decode"
    for rank in range(4)
)


def _encode(text: str) -> list[int]:
    return [128 + (value % 97) for value in text.encode()]


def test_exact_content_is_deterministic_exact_and_special_token_free() -> None:
    first = exact_content_tokens(
        family="high_entropy",
        target_tokens=1024,
        seed=41001,
        ordinal=7,
        encode=_encode,
        vocab_size=1024,
        special_token_ids={999, 1000},
    )
    second = exact_content_tokens(
        family="high_entropy",
        target_tokens=1024,
        seed=41001,
        ordinal=7,
        encode=_encode,
        vocab_size=1024,
        special_token_ids={999, 1000},
    )

    assert len(first) == 1024
    assert first == second
    assert not {999, 1000}.intersection(first)


def test_unique_and_repeated_prefix_contracts() -> None:
    unique_a = matrix_request(
        context_tokens=1024,
        concurrency=1,
        family="natural_language",
        seed=41001,
        ordinal=1,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    unique_b = matrix_request(
        context_tokens=1024,
        concurrency=1,
        family="natural_language",
        seed=41001,
        ordinal=2,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    repeated_a = matrix_request(
        context_tokens=32768,
        concurrency=8,
        family="natural_language",
        seed=41001,
        ordinal=1,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
        repeated_prefix=True,
    )
    repeated_b = matrix_request(
        context_tokens=32768,
        concurrency=8,
        family="code",
        seed=41001,
        ordinal=2,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
        repeated_prefix=True,
    )

    assert unique_a.input_ids[:32] != unique_b.input_ids[:32]
    assert unique_a.request_id != repeated_a.request_id
    assert repeated_a.input_ids[:16384] == repeated_b.input_ids[:16384]
    assert repeated_a.input_ids[16384:] != repeated_b.input_ids[16384:]


def test_primary_prefixes_are_unique_across_matrix_cells() -> None:
    short = matrix_request(
        context_tokens=1024,
        concurrency=1,
        family="natural_language",
        seed=41001,
        ordinal=1,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    long = matrix_request(
        context_tokens=8192,
        concurrency=8,
        family="natural_language",
        seed=41001,
        ordinal=1,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )

    assert short.input_ids[:32] != long.input_ids[:32]


def test_poisson_and_capacity_traces_are_reproducible() -> None:
    assert poisson_offsets(2.0, 10.0, 17) == poisson_offsets(2.0, 10.0, 17)
    trace = capacity_trace(
        rate=1.0,
        duration_seconds=5.0,
        seed=41001,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    replay = capacity_trace(
        rate=1.0,
        duration_seconds=5.0,
        seed=41001,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )

    assert trace_fingerprint(trace) == trace_fingerprint(replay)
    assert all(len(request.input_ids) == request.target_context_tokens for request in trace)
    assert all(request.output_tokens == 256 for request in trace)


def test_capacity_trace_balances_content_within_each_context_class() -> None:
    trace = capacity_trace(
        rate=50.0,
        duration_seconds=10.0,
        seed=41001,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for request in trace:
        counts[request.target_context_tokens][request.content_family] += 1

    assert set(counts) == {8192, 32768, 131072}
    for family_counts in counts.values():
        values = [family_counts[family] for family in ("natural_language", "code", "high_entropy")]
        assert max(values) - min(values) <= 1

    total = len(trace)
    context_counts = Counter(request.target_context_tokens for request in trace)
    for tokens, weight in ((8192, 0.50), (32768, 0.35), (131072, 0.15)):
        assert abs(context_counts[tokens] - total * weight) <= 1


def test_capacity_trace_includes_every_slo_class_when_three_arrivals_exist() -> None:
    seed = next(value for value in range(10_000) if len(poisson_offsets(0.02, 120, value)) == 3)
    trace = capacity_trace(
        rate=0.02,
        duration_seconds=120,
        seed=seed,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )

    assert {request.request_class for request in trace} == {
        "context-8k",
        "context-32k",
        "context-128k",
    }


def test_request_accounting_rejects_missing_duplicate_and_unexpected_rows() -> None:
    request = matrix_request(
        context_tokens=1024,
        concurrency=1,
        family="code",
        seed=41001,
        ordinal=1,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    reconcile_request_ids([request], [{"request_id": request.request_id}])

    with pytest.raises(ValueError, match="Request accounting mismatch"):
        reconcile_request_ids([request], [])
    with pytest.raises(ValueError, match="duplicates"):
        reconcile_request_ids(
            [request],
            [{"request_id": request.request_id}, {"request_id": request.request_id}],
        )
    with pytest.raises(ValueError, match="unexpected"):
        reconcile_request_ids([request], [{"request_id": "other"}])


def test_healthcheck_accepts_sglang_empty_health_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    responses = iter((Response(b""), Response(b'{"version":"test"}')))
    monkeypatch.setattr(
        s004_client.urllib.request, "urlopen", lambda *_args, **_kwargs: next(responses)
    )

    assert client_healthcheck("http://127.0.0.1:30000") == {"version": "test"}


def test_open_loop_lag_uses_prestarted_worker_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = matrix_request(
        context_tokens=1024,
        concurrency=1,
        family="natural_language",
        seed=41001,
        ordinal=0,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )
    spec = type(spec)(**{**spec.__dict__, "scheduled_offset_seconds": 0.0})

    def fake_send_request(_base_url: str, _spec: object, *, timeout: float) -> RequestResult:
        del timeout
        worker_started_ns = time.monotonic_ns()
        return RequestResult(
            row={"t0_ns": worker_started_ns + 5_000_000_000},
            response={},
            token_timestamps_ns=(),
            scheduling_lag_seconds=0,
            worker_started_ns=worker_started_ns,
        )

    monkeypatch.setattr(s004_client, "send_request", fake_send_request)
    result = run_open_loop("http://unused", [spec])

    assert result[0].scheduling_lag_seconds < 0.05
    assert result[0].row["scheduling_lag_ms"] < 50


@pytest.mark.parametrize(
    ("configuration", "log_text", "valid"),
    [
        ("CFG021", "ordinary startup", True),
        ("CFG022", _PINNED_HOST_LOG, True),
        (
            "CFG023",
            _PINNED_HOST_LOG + "\n" + _PREFETCH_LOG,
            True,
        ),
        ("CFG022", "Engram host table ready layout=shared, unpinned (ATS)", False),
        (
            "CFG022",
            _PINNED_HOST_LOG.replace(
                "[test TP3 EP3] engram host table layer 14: layout=shared, 1 MiB resident, pinned",
                "[test TP3 EP3] engram host table layer 14: "
                "layout=shared, 1 MiB resident, unpinned (ATS)",
            ),
            False,
        ),
        ("CFG022", "\n".join(_PINNED_HOST_LOG.splitlines()[:-1]), False),
        ("CFG023", _PINNED_HOST_LOG + "\n" + "\n".join(_PREFETCH_LOG.splitlines()[:-1]), False),
        ("CFG023", _PINNED_HOST_LOG, False),
        ("CFG021", _PINNED_HOST_LOG, False),
    ],
)
def test_treatment_resolution_is_machine_checked(
    configuration: str, log_text: str, valid: bool
) -> None:
    assert resolve_treatment(configuration, log_text)["valid"] is valid


def test_server_command_freezes_the_confirmatory_shape() -> None:
    command = server_command(model_path=Path("/model"), telemetry=True)

    assert command[command.index("--tp-size") + 1] == "4"
    assert command[command.index("--ep-size") + 1] == "4"
    assert command[command.index("--pp-size") + 1] == "1"
    assert command[command.index("--dp-size") + 1] == "1"
    assert command[command.index("--mem-fraction-static") + 1] == "0.80"
    assert command[command.index("--max-running-requests") + 1] == "64"
    assert command[command.index("--schedule-policy") + 1] == "fcfs"
    assert command[command.index("--num-continuous-decode-steps") + 1] == "1"
    assert command[command.index("--context-length") + 1] == "262400"
    assert command[command.index("--cuda-graph-max-bs-decode") + 1] == "64"
    assert command[command.index("--random-seed") + 1] == "20260910"
    assert command[command.index("--fp8-gemm-backend") + 1] == "flashinfer_cutedsl"
    assert command[command.index("--json-model-override-args") + 1] == '{"vision_n_layers": 0}'
    assert "--enable-metrics" in command


def test_resolved_server_configuration_is_machine_checked() -> None:
    expected = {
        "tp_size": 4,
        "ep_size": 4,
        "pp_size": 1,
        "dp_size": 1,
        "mem_fraction_static": 0.8,
        "max_running_requests": 64,
        "cuda_graph_max_bs_decode": 64,
        "schedule_policy": "fcfs",
        "num_continuous_decode_steps": 1,
        "context_length": 262400,
        "random_seed": 20260910,
        "fp8_gemm_runner_backend": "flashinfer_cutedsl",
        "json_model_override_args": '{"vision_n_layers": 0}',
        "enable_dp_attention": False,
        "speculative_algorithm": None,
        "enable_hierarchical_cache": False,
    }

    assert resolved_server_configuration(expected)["valid"] is True
    expected["max_running_requests"] = 256
    mismatch = resolved_server_configuration(expected)
    assert mismatch["valid"] is False
    assert mismatch["mismatches"]["max_running_requests"] == {
        "expected": 64,
        "actual": 256,
    }


def test_gpu_release_waits_until_all_child_processes_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        (
            SimpleNamespace(stdout="1234, scheduler, 100\n", stderr="", returncode=0),
            SimpleNamespace(stdout="", stderr="", returncode=0),
        )
    )
    monkeypatch.setattr(s004_lifecycle.subprocess, "run", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(s004_lifecycle.time, "sleep", lambda _seconds: None)

    wait_for_gpu_release(timeout=1)


def test_treatment_source_aggregate_is_canonical_and_frozen() -> None:
    records = {
        path: {"actual_sha256": sha256, "actual_size_bytes": size}
        for path, (sha256, size) in reversed(EXPECTED_RUNTIME_FILES.items())
    }

    assert treatment_source_fingerprint(records) == EXPECTED_TREATMENT_SOURCE_FINGERPRINT


def _result(
    request_class: str,
    *,
    ttft_ms: float = 10,
    lag: float = 0,
    outcome: str = "complete",
) -> RequestResult:
    return RequestResult(
        row={
            "request_id": request_class,
            "request_class": request_class,
            "outcome": outcome,
            "ttft_client_ms": ttft_ms,
            "tpot_ms": 10.0,
        },
        response={},
        token_timestamps_ns=(),
        scheduling_lag_seconds=lag,
    )


def test_slo_gate_requires_every_context_class_and_load_generator_health() -> None:
    passing = [
        _result(name)
        for name in ("context-8k", "context-32k", "context-128k")
        for _ in range(MINIMUM_SLO_CLASS_OBSERVATIONS)
    ]
    assert _slo_result(passing)["status"] == "pass"
    assert _slo_result(passing[:-1])["status"] == "insufficient"
    lagged = [*passing, _result("context-8k", lag=0.02)]
    assert _slo_result(lagged)["status"] == "fail"


def test_geometric_capacity_bisection_resolves_a_factor_two_bracket_in_three_steps() -> None:
    low = 1.0
    high = 2.0
    for _ in range(3):
        high = _capacity_bisection_rate(low, high)

    assert (high - low) / low < 0.10


def test_treatment_resolution_pilots_cover_all_modes_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[str] = []
    stopped: list[str] = []

    class FakeServer:
        def __init__(self, configuration: str) -> None:
            self.configuration = configuration

        def stop(self) -> None:
            stopped.append(self.configuration)

    def fake_preflight(_root: Path, output: Path, **_kwargs: object) -> dict[str, object]:
        result = {
            "hardware": {"valid": True},
            "model": {"valid": True},
            "runtime": {"valid": True},
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result))
        return result

    def fake_launch_server(
        *, configuration: str, work_dir: Path, telemetry: bool
    ) -> tuple[FakeServer, dict[str, object], dict[str, object], float]:
        del telemetry
        launched.append(configuration)
        log_text = {
            "CFG021": "ordinary startup",
            "CFG022": _PINNED_HOST_LOG,
            "CFG023": _PINNED_HOST_LOG + "\n" + _PREFETCH_LOG,
        }[configuration]
        info: dict[str, object] = {
            **EXPECTED_SERVER_CONFIGURATION,
            "max_total_num_tokens": 1234,
            "internal_states": [],
        }
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "server.log").write_text(log_text)
        (work_dir / "server-info.json").write_text(json.dumps(info))
        treatment = resolve_treatment(configuration, log_text)
        return (
            FakeServer(configuration),
            info,
            treatment,
            10.0,
        )

    monkeypatch.setattr("atlas.studies.runners.s004.preflight", fake_preflight)
    monkeypatch.setattr("atlas.studies.runners.s004.launch_server", fake_launch_server)

    first = _run_treatment_resolution_pilots(tmp_path, tmp_path / "work")
    second = _run_treatment_resolution_pilots(tmp_path, tmp_path / "work")

    assert first == second
    assert first["status"] == "pass"
    assert launched == ["CFG021", "CFG022", "CFG023"]
    assert stopped == launched


def test_treatment_pilot_retry_preserves_failed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    class FakeServer:
        def stop(self) -> None:
            return None

    def fake_preflight(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"valid": True}

    def fake_launch_server(
        *, configuration: str, work_dir: Path, telemetry: bool
    ) -> tuple[FakeServer, dict[str, object], dict[str, object], float]:
        nonlocal calls
        del work_dir, telemetry
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic startup failure")
        return (
            FakeServer(),
            {"max_total_num_tokens": 1234, "internal_states": []},
            {"configuration": configuration, "valid": True},
            10.0,
        )

    monkeypatch.setattr("atlas.studies.runners.s004.preflight", fake_preflight)
    monkeypatch.setattr("atlas.studies.runners.s004.launch_server", fake_launch_server)
    work = tmp_path / "work"

    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        _run_treatment_resolution_pilots(tmp_path, work)
    result = _run_treatment_resolution_pilots(tmp_path, work)

    first = json.loads(
        (work / "treatment-resolution-pilots/CFG021/attempt-1/result.json").read_text()
    )
    second = json.loads(
        (work / "treatment-resolution-pilots/CFG021/attempt-2/result.json").read_text()
    )
    assert first["status"] == "fail"
    assert second["status"] == "pass"
    assert result["status"] == "pass"


def test_slo_gate_reports_and_enforces_timeout_rate() -> None:
    rows = [
        _result(name) for name in ("context-8k", "context-32k", "context-128k") for _ in range(100)
    ]
    rows.append(_result("context-8k", outcome="timeout"))

    result = _slo_result(rows)

    assert result["classes"]["context-8k"]["timeout_rate"] == pytest.approx(1 / 101)
    assert result["status"] == "pass"

    rows.append(_result("context-8k", outcome="timeout"))
    assert _slo_result(rows)["status"] == "fail"


def test_slo_failure_without_completions_serializes_without_nan() -> None:
    failed = [
        _result(name, outcome="timeout")
        for name in ("context-8k", "context-32k", "context-128k")
        for _ in range(MINIMUM_SLO_CLASS_OBSERVATIONS)
    ]

    result = _slo_result(failed)

    assert result["classes"]["context-8k"]["p95_ttft_ms"] is None
    json.dumps(result, allow_nan=False)


def test_throttle_invalidation_mask_excludes_idle_and_software_power_cap() -> None:
    assert 0x1 & THERMAL_OR_POWER_THROTTLE_MASK == 0
    assert SOFTWARE_POWER_CAP_THROTTLE_MASK & THERMAL_OR_POWER_THROTTLE_MASK == 0
    assert THERMAL_OR_POWER_THROTTLE_MASK == INVALIDATING_GPU_CLOCK_EVENT_MASK
    for reason in (0x8, 0x20, 0x40, 0x80):
        assert reason & THERMAL_OR_POWER_THROTTLE_MASK


def _gpu_health_event(
    gpu_index: int,
    throttle_reasons: str,
    *,
    timestamp_ns: int = 1,
    power_limit_w: float | None = EXPECTED_GPU_POWER_LIMIT_W,
    ecc_errors: int = 0,
) -> dict[str, object]:
    details: dict[str, object] = {
        "gpu_index": gpu_index,
        "temperature_c": 55.0,
        "sm_clock_mhz": 1_800.0,
        "throttle_reasons": throttle_reasons,
        "uncorrected_volatile_ecc": ecc_errors,
    }
    if power_limit_w is not None:
        details["power_limit_w"] = power_limit_w
    return {
        "timestamp_ns": timestamp_ns,
        "event_type": "gpu-health",
        "details_json": json.dumps(details),
    }


def _measurement_health_for_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, object]],
    *,
    server_log_text: str = "",
) -> dict[str, object]:
    server_log = tmp_path / "server.log"
    server_log.write_text(server_log_text)
    monkeypatch.setattr("atlas.studies.runners.s004.psutil.pid_exists", lambda _pid: True)
    monkeypatch.setattr("atlas.studies.runners.s004._unexpected_gpu_processes", lambda _pid: [])
    collector = SimpleNamespace(events=events)
    return _measurement_health(
        collector=collector,
        server_pid=123,
        server_log=server_log,
        expected_power_limits_w={gpu: EXPECTED_GPU_POWER_LIMIT_W for gpu in range(4)},
    )


def test_gpu_snapshot_records_configured_power_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "pcie.rx_util" in command[1]:
            return SimpleNamespace(stdout="".join(f"{gpu}, 10, 20\n" for gpu in range(4)))
        return SimpleNamespace(
            stdout="".join(f"{gpu}, 75, 1024, 900, 1000, 55, 1800, 0x4, 0\n" for gpu in range(4))
        )

    monkeypatch.setattr("atlas.studies.runners.s004.subprocess.run", fake_run)
    collector = TelemetryCollector(tmp_path / "telemetry.json", server_pid=123)

    collector._gpu_snapshot(1)

    details = json.loads(collector.events[0]["details_json"])
    assert details["power_limit_w"] == 1_000.0
    assert details["temperature_c"] == 55.0
    assert details["sm_clock_mhz"] == 1_800.0


def test_collector_shutdown_failure_cannot_yield_eligible_evidence(tmp_path: Path) -> None:
    class StuckThread:
        def join(self, *, timeout: float) -> None:
            assert timeout > 10

        def is_alive(self) -> bool:
            return True

    output = tmp_path / "telemetry.json"
    collector = TelemetryCollector(output, server_pid=123)
    collector._thread = StuckThread()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="did not finish"):
        collector.stop()

    retained = json.loads(output.read_text())
    assert retained["events"][-1]["event_type"] == "collector-error"
    assert json.loads(retained["events"][-1]["details_json"])["terminal"] is True
    assert collector._shutdown_failure is not None
    collector.stop()


def test_software_power_cap_is_reported_per_gpu_without_invalidating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _gpu_health_event(
            gpu,
            "0x4" if sample <= gpu else "0x0",
            timestamp_ns=sample + 1,
        )
        for sample in range(2)
        for gpu in range(4)
    ]

    result = _measurement_health_for_events(tmp_path, monkeypatch, events)

    assert result["valid"] is True
    assert result["errors"] == []
    software_power_cap = result["software_power_cap"]
    assert software_power_cap["observation_count"] == 8
    assert software_power_cap["count"] == 7
    assert software_power_cap["incidence"] == pytest.approx(7 / 8)
    assert software_power_cap["by_gpu"]["0"] == {
        "observation_count": 2,
        "count": 1,
        "incidence": 0.5,
    }
    assert software_power_cap["by_gpu"]["3"]["incidence"] == 1.0


@pytest.mark.parametrize("mask", (0x8, 0x20, 0x40, 0x80))
def test_hardware_and_thermal_clock_events_still_invalidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mask: int
) -> None:
    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        [_gpu_health_event(gpu, hex(mask) if gpu == 0 else "0x0") for gpu in range(4)],
    )

    assert result["valid"] is False
    assert any("invalidating hardware/thermal clock event" in error for error in result["errors"])


def test_configured_power_limit_change_invalidates_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        [
            _gpu_health_event(
                gpu,
                "0x4" if gpu == 0 else "0x0",
                timestamp_ns=timestamp_ns,
                power_limit_w=950.0 if gpu == 0 and timestamp_ns == 2 else 1_000.0,
            )
            for timestamp_ns in (1, 2)
            for gpu in range(4)
        ],
    )

    assert result["valid"] is False
    assert any("differed from the preregistered" in error for error in result["errors"])
    assert result["configured_power_limit"]["by_gpu"]["0"] == {
        "readable_observation_count": 2,
        "mismatch_count": 1,
        "missing_count": 0,
        "unreadable_count": 0,
        "minimum_w": 950.0,
        "maximum_w": 1_000.0,
    }


def test_measurement_health_invalidates_missing_mandatory_power_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        [
            _gpu_health_event(
                gpu,
                "0x0",
                power_limit_w=None if gpu == 0 else EXPECTED_GPU_POWER_LIMIT_W,
            )
            for gpu in range(4)
        ],
    )

    assert result["valid"] is False
    assert result["configured_power_limit"]["missing_sample_count"] == 1
    assert any("omitted the mandatory" in error for error in result["errors"])


def test_measurement_health_invalidates_unreadable_power_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [_gpu_health_event(gpu, "0x0") for gpu in range(4)]
    first_details = json.loads(str(events[0]["details_json"]))
    first_details["power_limit_w"] = "[Not Supported]"
    events[0]["details_json"] = json.dumps(first_details)

    result = _measurement_health_for_events(tmp_path, monkeypatch, events)

    assert result["valid"] is False
    assert result["configured_power_limit"]["unreadable_sample_count"] == 1
    assert any("unreadable configured power limit" in error for error in result["errors"])


def test_measurement_health_requires_all_four_gpus_in_each_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [_gpu_health_event(gpu, "0x0") for gpu in range(3)]

    result = _measurement_health_for_events(tmp_path, monkeypatch, events)

    assert result["valid"] is False
    assert result["configured_power_limit"]["incomplete_gpu_health_cycle_count"] == 1
    assert any("four-GPU health telemetry was incomplete" in error for error in result["errors"])


def test_software_power_cap_mixed_with_thermal_event_still_invalidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        [_gpu_health_event(gpu, "0x24" if gpu == 0 else "0x0") for gpu in range(4)],
    )

    assert result["valid"] is False
    assert result["software_power_cap"]["count"] == 1
    assert any("0x20" in error for error in result["errors"])


def test_measurement_health_invalidates_nonfinite_power_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        [
            _gpu_health_event(
                gpu,
                "0x0",
                power_limit_w=math.nan if gpu == 0 else EXPECTED_GPU_POWER_LIMIT_W,
            )
            for gpu in range(4)
        ],
    )

    assert result["valid"] is False
    assert result["configured_power_limit"]["unreadable_sample_count"] == 1


def test_measurement_health_invalidates_duplicate_gpu_in_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [_gpu_health_event(gpu, "0x0") for gpu in range(4)]
    events.append(_gpu_health_event(0, "0x0"))

    result = _measurement_health_for_events(tmp_path, monkeypatch, events)

    assert result["valid"] is False
    assert result["configured_power_limit"]["incomplete_gpu_health_cycle_count"] == 1


def test_collection_error_ratio_counts_unique_cycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [
        _gpu_health_event(gpu, "0x0", timestamp_ns=timestamp_ns)
        for timestamp_ns in range(1, 100)
        for gpu in range(4)
    ]
    events.append(
        {
            "timestamp_ns": 1,
            "event_type": "collector-error",
            "details_json": json.dumps({"error": "load snapshot failed after GPU sampling"}),
        }
    )

    result = _measurement_health_for_events(tmp_path, monkeypatch, events)

    assert result["collection_error_ratio"] == pytest.approx(1 / 99)
    assert result["valid"] is False
    assert any("collection error ratio" in error for error in result["errors"])


def test_measurement_health_requires_explicit_four_gpu_expected_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_log = tmp_path / "server.log"
    server_log.write_text("")
    monkeypatch.setattr("atlas.studies.runners.s004.psutil.pid_exists", lambda _pid: True)
    collector = SimpleNamespace(events=[_gpu_health_event(gpu, "0x0") for gpu in range(4)])

    with pytest.raises(ValueError, match="GPUs 0-3"):
        _measurement_health(
            collector=collector,
            server_pid=123,
            server_log=server_log,
            expected_power_limits_w={0: EXPECTED_GPU_POWER_LIMIT_W},
        )


def test_ecc_and_xid_events_remain_invalidating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [_gpu_health_event(gpu, "0x0", ecc_errors=1 if gpu == 2 else 0) for gpu in range(4)]

    result = _measurement_health_for_events(
        tmp_path,
        monkeypatch,
        events,
        server_log_text="NVRM: Xid 79, GPU has fallen off the bus",
    )

    assert result["valid"] is False
    assert any("uncorrected ECC" in error for error in result["errors"])
    assert any("Xid" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("hardware_health_policy_version", "pre-amendment"),
        ("gpu_telemetry_query_fields", ["index"]),
        ("collector_implementation_sha256", "0" * 64),
    ),
)
def test_retained_collector_policy_requires_exact_provenance(
    field: str, replacement: object
) -> None:
    policy = _collector_policy_metadata()
    _validate_retained_collector_policy(policy)
    policy[field] = replacement

    with pytest.raises(RuntimeError, match=f"stale {field}"):
        _validate_retained_collector_policy(policy)


def test_scoped_breakdown_separates_unique_and_shared_prefix_cells() -> None:
    common = {
        "outcome": "complete",
        "content_family": "code",
        "target_context_tokens": 32768,
        "target_concurrency": 8,
        "ttft_client_ms": 100.0,
        "tpot_ms": 10.0,
        "itl_mean_ms": 10.0,
        "t0_ns": 0,
        "t5_ns": 1_000_000_000,
        "output_tokens": 64,
    }
    rows = [
        {**common, "load_cell_id": "context-32768-concurrency-8"},
        {**common, "load_cell_id": "prefix-context-32768-concurrency-8"},
        {**common, "load_cell_id": "capacity-rate-0.50000000"},
    ]

    breakdown = _scoped_breakdown(rows, "MET010")

    assert [item["scope"]["prefix_mode"] for item in breakdown] == [
        "shared-50-percent",
        "unique",
    ]


def test_aiperf_payload_preserves_exact_token_ids_and_greedy_decoding() -> None:
    request = matrix_request(
        context_tokens=32768,
        concurrency=8,
        family="code",
        seed=41001,
        ordinal=7,
        encode=_encode,
        vocab_size=1024,
        special_token_ids=set(),
    )

    payload = aiperf_payload(request, model="/model")

    assert payload["messages"] == []
    assert payload["prompt"] == list(request.input_ids)
    assert payload["max_tokens"] == 64
    assert payload["temperature"] == 0
    assert payload["ignore_eos"] is True
    assert payload["stream_options"] == {"include_usage": True}


def _aiperf_summary(*, ttft: float = 100.0) -> dict[str, object]:
    return {
        "aiperf_version": AIPERF_VERSION,
        "request_count": {"avg": CROSSCHECK_REQUESTS, "unit": "requests"},
        "error_request_count": {"avg": 0, "unit": "requests"},
        "input_sequence_length": {"avg": 32768, "unit": "tokens"},
        "output_sequence_length": {"avg": 64, "unit": "tokens"},
        "time_to_first_token": {"avg": ttft, "unit": "ms"},
        "inter_token_latency": {"avg": 10.0, "unit": "ms"},
        "output_token_throughput": {
            "avg": CROSSCHECK_REQUESTS * 64,
            "unit": "tokens/sec",
        },
    }


def test_aiperf_crosscheck_is_diagnostic_and_enforces_frozen_tolerance() -> None:
    rows = [
        {
            "outcome": "complete",
            "load_cell_id": "context-32768-concurrency-8",
            "ttft_client_ms": 100.0,
            "itl_mean_ms": 10.0,
            "output_tokens": 64,
            "t0_ns": 0,
            "t5_ns": 1_000_000_000,
        }
        for _ in range(CROSSCHECK_REQUESTS)
    ]

    passing = compare_aiperf_summary(rows, _aiperf_summary())
    disagreeing = compare_aiperf_summary(rows, _aiperf_summary(ttft=1000.0))

    assert passing["status"] == "pass"
    assert passing["headline_eligible"] is True
    assert disagreeing["status"] == "disagreement"
    assert disagreeing["headline_eligible"] is False


def test_full_runner_resume_skips_only_retained_complete_candidates(tmp_path: Path) -> None:
    attempt = tmp_path / "attempts/block-1-CFG021"
    candidate = tmp_path / "candidates/runs/block-1-CFG021"
    attempt.mkdir(parents=True)
    candidate.mkdir(parents=True)
    (attempt / "attempt.json").write_text(
        json.dumps({"status": "candidate-complete", "candidate": str(candidate)})
    )

    assert _completed_attempt(tmp_path, 1, "CFG021") == attempt
    assert _completed_attempt(tmp_path, 1, "CFG022") is None
    assert _new_attempt_directory(tmp_path, 1, "CFG021").name == "block-1-CFG021-retry-1"

    retry = tmp_path / "attempts/block-1-CFG021-retry-1"
    retry.mkdir()
    assert _new_attempt_directory(tmp_path, 1, "CFG021").name == "block-1-CFG021-retry-2"


def test_pre_amendment_invalid_attempt_cannot_be_requalified(tmp_path: Path) -> None:
    attempt = tmp_path / "attempts/block-1-CFG021"
    attempt.mkdir(parents=True)
    (attempt / "attempt.json").write_text(
        json.dumps({"status": "failed-or-invalid", "error": "pre-amendment invalidation"})
    )

    assert _completed_attempt(tmp_path, 1, "CFG021") is None
    assert _new_attempt_directory(tmp_path, 1, "CFG021").name == "block-1-CFG021-retry-1"


def test_model_manifest_verifier_checks_canonical_metadata_and_file_bytes(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    model = tmp_path / "model"
    manifest_path = (
        repository / "studies/S004-deepseek-v41-engram-placement/v1/inputs/model-manifest.yaml"
    )
    manifest_path.parent.mkdir(parents=True)
    model.mkdir()
    payload = b"pinned"
    (model / "config.json").write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    canonical = f"config.json\t{len(payload)}\t{sha}\n"
    manifest = {
        "file_count": 1,
        "total_size_bytes": len(payload),
        "aggregate_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "files": [{"path": "config.json", "size_bytes": len(payload), "sha256": sha}],
    }
    with manifest_path.open("w") as stream:
        yaml_writer().dump(manifest, stream)

    assert verify_model_manifest(repository, model)["valid"] is True
    (model / "config.json").write_bytes(b"changed")
    assert verify_model_manifest(repository, model)["valid"] is False


def test_expected_gpu_power_limits_are_loaded_from_hw002(tmp_path: Path) -> None:
    hardware_path = tmp_path / "registry/hardware/HW002-four-nvidia-b200.yaml"
    hardware_path.parent.mkdir(parents=True)
    record = {
        "nodes": [
            {
                "accelerators": [
                    {"id": f"gpu{gpu}", "power": {"limit_watts": 1_000}} for gpu in range(4)
                ]
            }
        ]
    }
    with hardware_path.open("w") as stream:
        yaml_writer().dump(record, stream)

    assert expected_gpu_power_limits(tmp_path) == {
        0: 1_000.0,
        1: 1_000.0,
        2: 1_000.0,
        3: 1_000.0,
    }


def test_hardware_snapshot_rejects_power_limit_that_differs_from_hw002(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "--query-compute-apps" in command[1]:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(
            stdout="".join(
                f"{gpu}, NVIDIA B200, 183360, 595.91.07, 55, 900, "
                f"{950 if gpu == 2 else 1000}, 0x0, 0\n"
                for gpu in range(4)
            )
        )

    monkeypatch.setattr(s004_lifecycle.subprocess, "run", fake_run)
    monkeypatch.setattr(s004_lifecycle.platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(s004_lifecycle.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(s004_lifecycle, "host_memory_snapshot", lambda: {})
    monkeypatch.setattr(s004_lifecycle, "host_memory_policy_snapshot", lambda: {})

    result = hardware_snapshot({gpu: 1_000.0 for gpu in range(4)})

    assert result["valid"] is False
    assert result["power_limit_mismatches"] == [
        {"gpu_index": 2, "expected_w": 1_000.0, "actual_w": 950.0}
    ]


def test_hardware_snapshot_requires_unique_gpu_indices_zero_through_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "--query-compute-apps" in command[1]:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(
            stdout="".join(
                f"{gpu}, NVIDIA B200, 183360, 595.91.07, 55, 900, 1000, 0x0, 0\n"
                for gpu in (0, 0, 1, 2)
            )
        )

    monkeypatch.setattr(s004_lifecycle.subprocess, "run", fake_run)
    monkeypatch.setattr(s004_lifecycle.platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(s004_lifecycle.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(s004_lifecycle, "host_memory_snapshot", lambda: {})
    monkeypatch.setattr(s004_lifecycle, "host_memory_policy_snapshot", lambda: {})

    result = hardware_snapshot({gpu: 1_000.0 for gpu in range(4)})

    assert result["valid"] is False
    assert result["gpu_indices_valid"] is False
    assert result["observed_gpu_indices"] == [0, 0, 1, 2]


def test_host_memory_snapshot_normalizes_kibibytes_to_bytes(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       1000 kB\n"
        "MemAvailable:    750 kB\n"
        "Cached:          500 kB\n"
        "HugePages_Total:   12\n"
        "Ignored:           99 kB\n"
    )

    assert host_memory_snapshot(meminfo) == {
        "MemTotal": 1_024_000,
        "MemAvailable": 768_000,
        "Cached": 512_000,
        "HugePages_Total": 12,
    }
