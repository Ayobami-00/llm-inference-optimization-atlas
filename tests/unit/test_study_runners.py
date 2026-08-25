from __future__ import annotations

from atlas.studies.runners.common import distribution, summarize_requests
from atlas.studies.runners.s001 import run_id
from atlas.studies.runners.s002 import run_id as s002_run_id
from atlas.studies.runners.s003 import run_id as s003_run_id


def test_s001_run_ids_are_stable_and_unique_across_experiments() -> None:
    assert run_id("E0001", "CFG001", 1) == "R1111"
    assert run_id("E0004", "CFG007", 3) == "R1473"


def test_s002_run_ids_are_stable_and_unique_across_experiments() -> None:
    assert s002_run_id("E0005", "CFG009", 1) == "R2121"
    assert s002_run_id("E0008", "CFG014", 3) == "R2473"


def test_s003_run_ids_are_stable_and_unique_across_experiments() -> None:
    assert s003_run_id("E0009", "CFG015", 1) == "R3111"
    assert s003_run_id("E0012", "CFG020", 3) == "R3463"


def test_distribution_reports_required_percentiles() -> None:
    result = distribution([1.0, 2.0, 3.0, 4.0])
    assert result["count"] == 4
    assert result["p50"] == 2.5
    assert set(result) == {"count", "mean", "p50", "p90", "p95"}


def test_request_summary_contains_mandatory_m0_metrics() -> None:
    row = {
        "outcome": "complete",
        "input_tokens": 10,
        "output_tokens": 2,
        "ttft_client_ms": 5.0,
        "tpot_ms": 2.0,
        "itl_mean_ms": 2.0,
        "e2e_ms": 7.0,
        "queue_ms": 0.0,
        "quality_passed": True,
    }
    summary = summarize_requests(
        [row],
        elapsed_seconds=1.0,
        rss_bytes=10,
        peak_rss_bytes=12,
        cpu_ratio=0.5,
        quality_rate=1.0,
    )
    optional = {22, 26, 27}
    assert all(f"MET{number:03d}" in summary for number in range(1, 31) if number not in optional)
