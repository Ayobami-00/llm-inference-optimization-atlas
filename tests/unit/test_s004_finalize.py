from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from atlas.studies.runners.s004_finalize import (
    SLO_DERIVATION_POLICY_VERSION,
    apply_slo_status,
    derive_slo_status,
    finalize_s004_draft,
)


def _summary(
    points: list[tuple[float, str]],
    *,
    boundary_status: str,
    upper: float | None,
    width: float | None,
    resolved: bool,
) -> dict[str, Any]:
    capacity = max((rate for rate, status in points if status == "pass"), default=0.0)
    return {
        "capacity_points": [
            {
                "rate_request_per_second": rate,
                "status": status,
                "passed": status == "pass",
            }
            for rate, status in points
        ],
        "capacity_search": {
            "status": boundary_status,
            "highest_qualifying_rate_request_per_second": capacity,
            "lowest_nonqualifying_rate_above_capacity_request_per_second": upper,
            "boundary_relative_width": width,
            "boundary_resolved_within_10_percent": resolved,
            "tested_points": len(points),
            "maximum_points": 8,
        },
        "metrics": {"MET099": {"value": capacity, "unit": "request/s"}},
    }


def _seal(draft: Path) -> None:
    checksum_path = draft / "checksums.sha256"
    paths = sorted(path for path in draft.rglob("*") if path.is_file() and path != checksum_path)
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(draft).as_posix()}"
        for path in paths
    ]
    (draft / "checksums.sha256").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize(
    ("summary", "passed", "eligible", "status"),
    [
        (
            _summary(
                [(0.2, "pass"), (0.4, "pass"), (0.44, "fail")],
                boundary_status="resolved",
                upper=0.44,
                width=0.1,
                resolved=True,
            ),
            True,
            True,
            "resolved",
        ),
        (
            _summary(
                [(0.2, "pass"), (0.4, "pass")],
                boundary_status="right-censored",
                upper=None,
                width=None,
                resolved=False,
            ),
            True,
            True,
            "right-censored",
        ),
        (
            _summary(
                [(0.2, "fail"), (0.4, "fail")],
                boundary_status="left-censored",
                upper=0.2,
                width=None,
                resolved=False,
            ),
            False,
            True,
            "left-censored",
        ),
        (
            _summary(
                [(0.2, "insufficient")],
                boundary_status="unresolved",
                upper=None,
                width=None,
                resolved=False,
            ),
            False,
            False,
            "unresolved",
        ),
    ],
)
def test_derive_slo_status_separates_pass_from_boundary_eligibility(
    summary: dict[str, Any], passed: bool, eligible: bool, status: str
) -> None:
    result = derive_slo_status(summary)

    assert result["slo_passed"] is passed
    assert result["slo_eligible"] is eligible
    assert result["slo_boundary_status"] == status


def test_apply_slo_status_rejects_conflicting_existing_metadata() -> None:
    summary = _summary(
        [(0.2, "fail")],
        boundary_status="left-censored",
        upper=0.2,
        width=None,
        resolved=False,
    )
    summary["slo_passed"] = True

    with pytest.raises(ValueError, match="Existing slo_passed disagrees"):
        apply_slo_status(summary)


def test_derive_slo_status_rejects_incoherent_capacity_metric() -> None:
    summary = _summary(
        [(0.2, "pass"), (0.4, "fail")],
        boundary_status="unresolved",
        upper=0.4,
        width=1.0,
        resolved=False,
    )
    summary["metrics"]["MET099"]["value"] = 0.3

    with pytest.raises(ValueError, match="MET099 disagrees"):
        derive_slo_status(summary)


def test_finalize_s004_draft_is_idempotent_and_reseals_checksums(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    summary_path = draft / "metrics" / "summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            _summary(
                [(0.2, "pass"), (0.4, "pass")],
                boundary_status="right-censored",
                upper=None,
                width=None,
                resolved=False,
            )
        )
    )
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R0000", "experiment": "atlas://experiment/E0013@v1"})
    )
    _seal(draft)

    first = finalize_s004_draft(draft)
    second = finalize_s004_draft(draft)

    assert first == second
    finalized = json.loads(summary_path.read_text())
    assert finalized["slo_passed"] is True
    assert finalized["slo_eligible"] is True
    assert finalized["slo_derivation"]["policy_version"] == SLO_DERIVATION_POLICY_VERSION
    manifest = (draft / "checksums.sha256").read_text().splitlines()
    expected_digest = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    assert f"{expected_digest}  metrics/summary.json" in manifest


def test_finalize_s004_draft_refuses_allocated_evidence(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    (draft / "metrics").mkdir(parents=True)
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R4001", "experiment": "atlas://experiment/E0013@v1"})
    )

    with pytest.raises(ValueError, match="Only an unallocated R0000 draft"):
        finalize_s004_draft(draft)


def test_finalize_s004_draft_rejects_tampered_non_summary_artifact(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    summary_path = draft / "metrics" / "summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            _summary(
                [(0.2, "fail")],
                boundary_status="left-censored",
                upper=0.2,
                width=None,
                resolved=False,
            )
        )
    )
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R0000", "experiment": "atlas://experiment/E0013@v1"})
    )
    _seal(draft)
    (draft / "run.yaml").write_text(
        json.dumps(
            {
                "id": "R0000",
                "experiment": "atlas://experiment/E0013@v1",
                "tampered": True,
            }
        )
    )

    with pytest.raises(ValueError, match=r"does not match the draft: run\.yaml"):
        finalize_s004_draft(draft)


@pytest.mark.parametrize("manifest", [None, "stale\n"])
def test_finalize_s004_draft_rejects_missing_or_malformed_manifest(
    tmp_path: Path, manifest: str | None
) -> None:
    draft = tmp_path / "draft"
    summary_path = draft / "metrics" / "summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("{}\n")
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R0000", "experiment": "atlas://experiment/E0013@v1"})
    )
    if manifest is not None:
        (draft / "checksums.sha256").write_text(manifest)

    with pytest.raises(ValueError, match=r"checksums\.sha256"):
        finalize_s004_draft(draft)


@pytest.mark.parametrize("kind", ["file", "directory", "broken"])
def test_finalize_s004_draft_rejects_any_symlink(tmp_path: Path, kind: str) -> None:
    draft = tmp_path / "draft"
    metrics = draft / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "summary.json").write_text("{}\n")
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R0000", "experiment": "atlas://experiment/E0013@v1"})
    )
    _seal(draft)
    if kind == "file":
        (draft / "linked-file").symlink_to(draft / "run.yaml")
    elif kind == "directory":
        outside = tmp_path / "outside"
        outside.mkdir()
        (draft / "linked-directory").symlink_to(outside, target_is_directory=True)
    else:
        (draft / "broken-link").symlink_to(tmp_path / "missing")

    with pytest.raises(ValueError, match="must not contain symlinks"):
        finalize_s004_draft(draft)


def test_finalize_s004_draft_rejects_symlinked_manifest(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    (draft / "metrics").mkdir(parents=True)
    (draft / "metrics" / "summary.json").write_text("{}\n")
    (draft / "run.yaml").write_text(
        json.dumps({"id": "R0000", "experiment": "atlas://experiment/E0013@v1"})
    )
    external_manifest = tmp_path / "external-checksums.sha256"
    external_manifest.write_text("stale\n")
    (draft / "checksums.sha256").symlink_to(external_manifest)

    with pytest.raises(ValueError, match="manifest must not be a symlink"):
        finalize_s004_draft(draft)
