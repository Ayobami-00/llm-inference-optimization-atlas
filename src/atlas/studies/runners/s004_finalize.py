from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from atlas.studies.evidence_writer import sha256_file
from atlas.studies.runners.s004_diagnostics import server_log_diagnostics
from atlas.utilities.serialization import load_data

SLO_DERIVATION_POLICY_VERSION = "E0013-SLO-DERIVATION-001"
ELIGIBLE_BOUNDARY_STATUSES = frozenset({"resolved", "left-censored", "right-censored"})
BOUNDARY_STATUSES = ELIGIBLE_BOUNDARY_STATUSES | {"unresolved"}


def _finite_number(value: Any, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def derive_slo_status(summary: dict[str, Any]) -> dict[str, Any]:
    """Derive S004 SLO flags from retained capacity-search evidence.

    ``slo_passed`` answers whether at least one offered load passed every
    preregistered class SLO. ``slo_eligible`` answers whether the search has a
    reportable boundary interpretation, including censored boundaries.
    """

    points = summary.get("capacity_points")
    search = summary.get("capacity_search")
    metrics = summary.get("metrics")
    if not isinstance(points, list) or not points:
        raise ValueError("capacity_points must be a non-empty list")
    if not isinstance(search, dict):
        raise ValueError("capacity_search must be an object")
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be an object")

    rates: set[float] = set()
    passing_rates: list[float] = []
    failing_rates: list[float] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError(f"capacity_points[{index}] must be an object")
        rate = _finite_number(
            point.get("rate_request_per_second"),
            name=f"capacity_points[{index}].rate_request_per_second",
            minimum=0.0,
        )
        if rate == 0:
            raise ValueError(f"capacity_points[{index}] has a zero offered rate")
        if rate in rates:
            raise ValueError(f"capacity_points contains duplicate offered rate {rate}")
        rates.add(rate)
        passed = point.get("passed")
        status = point.get("status")
        if not isinstance(passed, bool):
            raise ValueError(f"capacity_points[{index}].passed must be boolean")
        if status not in {"pass", "fail", "insufficient"}:
            raise ValueError(f"capacity_points[{index}].status is invalid: {status!r}")
        if passed != (status == "pass"):
            raise ValueError(f"capacity_points[{index}] has incoherent passed/status values")
        if passed:
            passing_rates.append(rate)
        elif status == "fail":
            failing_rates.append(rate)

    boundary_status = search.get("status")
    if boundary_status not in BOUNDARY_STATUSES:
        raise ValueError(f"capacity_search.status is invalid: {boundary_status!r}")
    tested_points = search.get("tested_points")
    if isinstance(tested_points, bool) or not isinstance(tested_points, int):
        raise ValueError("capacity_search.tested_points must be an integer")
    if tested_points != len(points):
        raise ValueError("capacity_search.tested_points does not match capacity_points")

    capacity = max(passing_rates, default=0.0)
    reported_capacity = _finite_number(
        search.get("highest_qualifying_rate_request_per_second"),
        name="capacity_search.highest_qualifying_rate_request_per_second",
        minimum=0.0,
    )
    if not math.isclose(reported_capacity, capacity, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("capacity_search highest qualifying rate disagrees with points")

    capacity_metric = metrics.get("MET099")
    if not isinstance(capacity_metric, dict) or capacity_metric.get("unit") != "request/s":
        raise ValueError("MET099 must be present with unit request/s")
    metric_capacity = _finite_number(
        capacity_metric.get("value"), name="metrics.MET099.value", minimum=0.0
    )
    if not math.isclose(metric_capacity, capacity, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("MET099 disagrees with the retained capacity-search points")

    upper_candidates = [rate for rate in failing_rates if rate > capacity]
    reported_upper = search.get("lowest_nonqualifying_rate_above_capacity_request_per_second")
    expected_upper = min(upper_candidates) if upper_candidates else None
    if reported_upper is None:
        if expected_upper is not None:
            raise ValueError("capacity_search omits an observed upper boundary")
    else:
        numeric_upper = _finite_number(
            reported_upper,
            name="capacity_search.lowest_nonqualifying_rate_above_capacity_request_per_second",
            minimum=0.0,
        )
        if expected_upper is None or not math.isclose(
            numeric_upper, expected_upper, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("capacity_search upper boundary disagrees with points")

    boundary_resolved = search.get("boundary_resolved_within_10_percent")
    if not isinstance(boundary_resolved, bool):
        raise ValueError("capacity_search.boundary_resolved_within_10_percent must be boolean")
    width = search.get("boundary_relative_width")
    expected_width = (
        (expected_upper - capacity) / capacity
        if capacity > 0 and expected_upper is not None
        else None
    )
    if width is None:
        if expected_width is not None:
            raise ValueError("capacity_search omits the observed boundary width")
    else:
        numeric_width = _finite_number(
            width, name="capacity_search.boundary_relative_width", minimum=0.0
        )
        if expected_width is None or not math.isclose(
            numeric_width, expected_width, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("capacity_search boundary width disagrees with points")
    if boundary_resolved != (expected_width is not None and expected_width <= 0.10):
        raise ValueError("capacity_search resolved flag disagrees with its boundary width")

    expected_status = (
        "resolved"
        if boundary_resolved
        else "right-censored"
        if passing_rates and not upper_candidates
        else "left-censored"
        if not passing_rates and failing_rates
        else "unresolved"
    )
    if boundary_status != expected_status:
        raise ValueError(
            f"capacity_search.status {boundary_status!r} disagrees with derived "
            f"status {expected_status!r}"
        )

    interpretation = {
        "resolved": "bounded estimate resolved within the preregistered 10 percent width",
        "right-censored": "lower bound at the highest tested qualifying offered rate",
        "left-censored": "no qualifying offered rate in the preregistered tested domain",
        "unresolved": "no reportable SLO-capacity boundary",
    }[boundary_status]
    return {
        "slo_passed": bool(passing_rates),
        "slo_eligible": boundary_status in ELIGIBLE_BOUNDARY_STATUSES,
        "slo_boundary_status": boundary_status,
        "slo_derivation": {
            "policy_version": SLO_DERIVATION_POLICY_VERSION,
            "source_fields": [
                "capacity_points[*].passed",
                "capacity_points[*].status",
                "capacity_search.status",
                "metrics.MET099.value",
            ],
            "tested_point_count": len(points),
            "qualifying_point_count": len(passing_rates),
            "interpretation": interpretation,
        },
    }


def apply_slo_status(summary: dict[str, Any]) -> dict[str, Any]:
    derived = derive_slo_status(summary)
    derived["slo_derivation"]["implementation"] = (
        "atlas.studies.runners.s004_finalize.derive_slo_status"
    )
    derived["slo_derivation"]["implementation_sha256"] = sha256_file(Path(__file__))
    for key, value in derived.items():
        if key in summary and summary[key] != value:
            raise ValueError(f"Existing {key} disagrees with retained capacity evidence")
        summary[key] = value
    return summary


def _reseal_draft(draft: Path) -> None:
    checksum_path = draft / "checksums.sha256"
    manifest_paths = sorted(
        path for path in draft.rglob("*") if path.is_file() and path != checksum_path
    )
    lines = [
        f"{sha256_file(path)}  {path.relative_to(draft).as_posix()}" for path in manifest_paths
    ]
    checksum_path.write_text("\n".join(lines) + "\n")


def _verify_existing_manifest(draft: Path) -> None:
    checksum_path = draft / "checksums.sha256"
    if checksum_path.is_symlink():
        raise ValueError("Draft checksum manifest must not be a symlink")
    if not checksum_path.is_file():
        raise ValueError("Draft has no existing checksums.sha256 manifest")
    expected: dict[str, str] = {}
    for line_number, line in enumerate(checksum_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            digest, relative = line.split(maxsplit=1)
        except ValueError as error:
            raise ValueError(f"checksums.sha256 line {line_number} is malformed") from error
        relative = relative.lstrip("*")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"checksums.sha256 line {line_number} has an invalid digest")
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise ValueError(f"checksums.sha256 line {line_number} has an unsafe path")
        if relative in expected:
            raise ValueError(f"checksums.sha256 contains duplicate path {relative}")
        expected[relative] = digest

    entries = list(draft.rglob("*"))
    symlinks = [path for path in entries if path.is_symlink()]
    if symlinks:
        raise ValueError(f"Draft evidence must not contain symlinks: {symlinks[0]}")
    actual_paths = sorted(path for path in entries if path.is_file() and path != checksum_path)
    actual = {path.relative_to(draft).as_posix(): path for path in actual_paths}
    missing = sorted(set(actual) - set(expected))
    unexpected = sorted(set(expected) - set(actual))
    if missing or unexpected:
        raise ValueError(
            "Existing checksum manifest does not exactly cover the draft: "
            f"missing={missing}, unexpected={unexpected}"
        )
    mismatched = [
        relative for relative, path in actual.items() if sha256_file(path) != expected[relative]
    ]
    if mismatched:
        raise ValueError(
            "Existing checksum manifest does not match the draft: " + ", ".join(mismatched)
        )


def _attach_server_log_diagnostics(summary: dict[str, Any], server_log: Path) -> None:
    diagnostics = server_log_diagnostics(server_log)
    existing = summary.get("server_log_diagnostics")
    if existing is not None:
        if not isinstance(existing, dict):
            raise ValueError("Existing server_log_diagnostics must be an object")
        for key in (
            "maximum_reported_running_batch",
            "reported_running_batch_observations",
            "preemption_log_mentions",
            "fallback_log_mentions",
        ):
            if key in existing and existing[key] != diagnostics[key]:
                raise ValueError(f"Server log does not match existing server_log_diagnostics.{key}")
    summary["server_log_diagnostics"] = diagnostics


def finalize_s004_draft(draft: Path, *, server_log: Path | None = None) -> dict[str, Any]:
    """Finalize mutable S004 draft metadata and reseal its checksum manifest."""

    if draft.is_symlink():
        raise ValueError("Draft root must not be a symlink")
    draft = draft.resolve()
    run = load_data(draft / "run.yaml")
    if not isinstance(run, dict):
        raise ValueError("Draft has no valid run.yaml")
    if run.get("id") != "R0000":
        raise ValueError("Only an unallocated R0000 draft may be finalized")
    if run.get("experiment") != "atlas://experiment/E0013@v1":
        raise ValueError("Draft is not an E0013 run")
    _verify_existing_manifest(draft)

    summary_path = draft / "metrics" / "summary.json"
    summary = load_data(summary_path)
    if not isinstance(summary, dict):
        raise ValueError("Draft has no valid metrics/summary.json")
    if server_log is not None:
        _attach_server_log_diagnostics(summary, server_log)
    apply_slo_status(summary)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _reseal_draft(draft)
    return {
        "draft": str(draft),
        "policy_version": SLO_DERIVATION_POLICY_VERSION,
        "slo_passed": summary["slo_passed"],
        "slo_eligible": summary["slo_eligible"],
        "slo_boundary_status": summary["slo_boundary_status"],
        "server_log_diagnostics_attached": server_log is not None,
        "summary_sha256": sha256_file(summary_path),
        "checksums_sha256": sha256_file(draft / "checksums.sha256"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive S004 SLO publication metadata and reseal a mutable run draft."
    )
    parser.add_argument("draft", type=Path)
    parser.add_argument(
        "--server-log",
        type=Path,
        help="Retained attempt server log used to attach privacy-safe memory-pressure counts.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            finalize_s004_draft(args.draft, server_log=args.server_log),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
