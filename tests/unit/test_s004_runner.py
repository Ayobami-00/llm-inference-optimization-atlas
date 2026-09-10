from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from atlas.studies.runners.s004 import (
    MINIMUM_SLO_CLASS_OBSERVATIONS,
    THERMAL_OR_POWER_THROTTLE_MASK,
    _capacity_bisection_rate,
    _completed_attempt,
    _new_attempt_directory,
    _run_treatment_resolution_pilots,
    _scoped_breakdown,
    _slo_result,
)
from atlas.studies.runners.s004_aiperf import (
    AIPERF_VERSION,
    CROSSCHECK_REQUESTS,
    aiperf_payload,
    compare_aiperf_summary,
)
from atlas.studies.runners.s004_client import RequestResult
from atlas.studies.runners.s004_lifecycle import (
    EXPECTED_RUNTIME_FILES,
    EXPECTED_TREATMENT_SOURCE_FINGERPRINT,
    host_memory_snapshot,
    resolve_treatment,
    server_command,
    treatment_source_fingerprint,
    verify_model_manifest,
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


@pytest.mark.parametrize(
    ("configuration", "log_text", "valid"),
    [
        ("CFG021", "ordinary startup", True),
        ("CFG022", "Engram host table ready layout=shared, pinned", True),
        (
            "CFG023",
            "Engram host table ready layout=shared, pinned\n"
            "Engram layer 14 KV prefetch enabled for BS=1 decode",
            True,
        ),
        ("CFG022", "Engram host table ready layout=shared, unpinned (ATS)", False),
        ("CFG023", "Engram host table ready layout=shared, pinned", False),
        ("CFG021", "Engram host table ready layout=shared, pinned", False),
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
    assert command[command.index("--mem-fraction-static") + 1] == "0.80"
    assert command[command.index("--context-length") + 1] == "262400"
    assert command[command.index("--cuda-graph-max-bs-decode") + 1] == "64"
    assert command[command.index("--random-seed") + 1] == "20260910"
    assert command[command.index("--fp8-gemm-backend") + 1] == "flashinfer_cutedsl"
    assert command[command.index("--json-model-override-args") + 1] == '{"vision_config": null}'
    assert "--enable-metrics" in command


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

    def fake_preflight(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"valid": True}

    def fake_launch_server(
        *, configuration: str, work_dir: Path, telemetry: bool
    ) -> tuple[FakeServer, dict[str, object], dict[str, object], float]:
        del work_dir, telemetry
        launched.append(configuration)
        return (
            FakeServer(configuration),
            {"max_total_num_tokens": 1234, "internal_states": []},
            {"configuration": configuration, "valid": True},
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


def test_throttle_invalidation_mask_excludes_idle_and_includes_power_and_thermal() -> None:
    assert 0x1 & THERMAL_OR_POWER_THROTTLE_MASK == 0
    for reason in (0x4, 0x8, 0x20, 0x40, 0x80):
        assert reason & THERMAL_OR_POWER_THROTTLE_MASK


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
