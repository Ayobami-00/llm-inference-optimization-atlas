from __future__ import annotations

from pathlib import Path

from atlas.execution.evidence import validate_evidence
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
    )

    output = write_run_draft(tmp_path, draft)
    report = validate_evidence(ROOT, output)

    assert report.ok, report.errors
