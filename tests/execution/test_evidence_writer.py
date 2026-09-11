from __future__ import annotations

from pathlib import Path

from atlas.execution.evidence import promote_evidence, validate_evidence
from atlas.studies.evidence_writer import RunDraft, write_run_draft

ROOT = Path(__file__).parents[2]


def test_writer_emits_promotable_evidence_shape(tmp_path: Path) -> None:
    draft = RunDraft(
        run_id="R0001",
        experiment="atlas://experiment/E0001@v1",
        configuration="atlas://configuration/CFG001@v1",
        runtime="atlas://runtime/RT001@v1",
        replicate=1,
        seed=101,
        started_at="2026-08-25T12:00:00Z",
        ended_at="2026-08-25T12:00:01Z",
        measurement_started_at="2026-08-25T12:00:00.250Z",
        measurement_ended_at="2026-08-25T12:00:00.750Z",
        requests=[
            {
                "request_id": "request-1",
                "request_class": "short",
                "outcome": "complete",
                "t0_ns": 1,
                "t5_ns": 1_000_001,
                "input_tokens": 10,
                "output_tokens": 2,
                "ttft_client_ms": 0.5,
                "tpot_ms": 0.25,
                "itl_mean_ms": 0.25,
                "itl_p95_ms": 0.25,
                "e2e_ms": 1.0,
                "queue_ms": 0.0,
                "quality_passed": True,
            }
        ],
        samples=[
            {
                "timestamp_ns": 1,
                "metric_id": "MET025",
                "value": 50.0,
                "unit": "%",
                "scope": "process",
            }
        ],
        responses=[{"request_id": "request-1", "text": "ok"}],
        quality_results={"passed": True},
        quality_passed=True,
        summary={"warmup_requests": 1},
        input_fingerprints={"fixture": "a" * 64},
        artifact_checksums={"model": "b" * 64},
        command=["run.sh"],
        hardware="atlas://hardware/HW002@v1",
        quality_gate="Q0",
    )

    output = write_run_draft(tmp_path, draft)
    report = validate_evidence(ROOT, output)

    assert report.ok, report.errors
    run = (output / "run.yaml").read_text()
    assert "hardware_snapshot: atlas://hardware/HW002@v1" in run
    assert "gate: Q0" in run
    assert "start: '2026-08-25T12:00:00.250Z'" in run
    assert "end: '2026-08-25T12:00:00.750Z'" in run


def test_writer_preserves_optional_workload_dimensions(tmp_path: Path) -> None:
    draft = RunDraft(
        run_id="R0001",
        experiment="atlas://experiment/E0001@v1",
        configuration="atlas://configuration/CFG001@v1",
        runtime="atlas://runtime/RT001@v1",
        replicate=1,
        seed=101,
        started_at="2026-08-25T12:00:00Z",
        ended_at="2026-08-25T12:00:01Z",
        requests=[
            {
                "request_id": "request-1",
                "request_class": "long",
                "outcome": "complete",
                "t0_ns": 1,
                "t5_ns": 1_000_001,
                "input_tokens": 32768,
                "output_tokens": 2,
                "ttft_client_ms": 0.5,
                "tpot_ms": 0.25,
                "itl_mean_ms": 0.25,
                "itl_p95_ms": 0.25,
                "e2e_ms": 1.0,
                "queue_ms": 0.0,
                "quality_passed": True,
                "retry_count": 0,
                "scheduling_lag_ms": 0.125,
                "slo_eligible": True,
                "token_timestamps_ns": [100, 200],
                "load_cell_id": "context-32768-concurrency-8",
                "content_family": "code",
                "target_context_tokens": 32768,
                "target_concurrency": 8,
                "target_offered_rate": 0.5,
            }
        ],
        samples=[],
        responses=[],
        quality_results={"passed": True},
        quality_passed=True,
        summary={"warmup_requests": 0},
        input_fingerprints={"fixture": "a" * 64},
        artifact_checksums={"model": "b" * 64},
        command=["run.sh"],
    )

    output = write_run_draft(tmp_path, draft)
    import pyarrow.parquet as pq

    row = pq.read_table(output / "metrics/requests.parquet").to_pylist()[0]
    assert row["load_cell_id"] == "context-32768-concurrency-8"
    assert row["content_family"] == "code"
    assert row["target_context_tokens"] == 32768
    assert row["target_concurrency"] == 8
    assert row["target_offered_rate"] == 0.5
    assert row["retry_count"] == 0
    assert row["scheduling_lag_ms"] == 0.125
    assert row["slo_eligible"] is True
    assert row["token_timestamps_ns"] == [100, 200]


def test_promotion_allocates_and_rewrites_a_provisional_run_id(tmp_path: Path) -> None:
    import shutil

    repository = tmp_path / "repository"
    shutil.copytree(ROOT / "reference/schemas", repository / "reference/schemas")
    (repository / "studies/S999-fixture/v1/experiments/E9999").mkdir(parents=True)
    draft = RunDraft(
        run_id="R0000",
        directory_name="block-1-CFG001",
        experiment="atlas://experiment/E9999@v1",
        configuration="atlas://configuration/CFG001@v1",
        runtime="atlas://runtime/RT001@v1",
        replicate=1,
        seed=101,
        started_at="2026-08-25T12:00:00Z",
        ended_at="2026-08-25T12:00:01Z",
        requests=[],
        samples=[],
        responses=[],
        quality_results={"passed": True},
        quality_passed=True,
        summary={"warmup_requests": 0},
        input_fingerprints={"fixture": "a" * 64},
        artifact_checksums={"model": "b" * 64},
        command=["run.sh"],
    )
    candidate = write_run_draft(tmp_path / "draft", draft)

    promoted = promote_evidence(repository, candidate)

    assert promoted.name == "R0001"
    assert "id: R0001" in (promoted / "run.yaml").read_text()
    assert validate_evidence(repository, promoted).ok
