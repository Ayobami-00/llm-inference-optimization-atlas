from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.utilities.serialization import load_data
from atlas.validation import ValidationIssue, Validator


@dataclass(frozen=True)
class OntologyReport:
    catalogs: int
    entries: int
    coverage: dict[str, int]
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "catalogs": self.catalogs,
            "entries": self.entries,
            "coverage": self.coverage,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def _category(identifier: str) -> str | None:
    if identifier.startswith("OPT"):
        return "optimizations"
    if identifier.startswith("MET"):
        return "metrics"
    if identifier.startswith("WC"):
        return "workload_characteristics"
    if identifier.startswith("REL-"):
        return "relations"
    if identifier.startswith("PHASE-"):
        return "lifecycle_phases"
    if identifier.startswith("B") and identifier[1:].isdigit():
        return "bottlenecks"
    if identifier.startswith("W") and identifier[1:].isdigit():
        return "workloads"
    if identifier.startswith("T") and identifier[1:].isdigit():
        return "traffic_regimes"
    return None


def check_ontology(root: Path) -> OntologyReport:
    ontology_root = root / "reference" / "ontology" / "v1"
    validator = Validator(root)
    local_report = validator.validate_path(ontology_root)
    strict_report = validator.validate_path(root, strict=True)
    issues = list(local_report.issues)
    issues.extend(
        issue for issue in strict_report.issues if issue.path.startswith("reference/ontology/")
    )

    identifiers: list[tuple[str, Path]] = []
    counts: Counter[str] = Counter()
    catalogs = 0
    for path in sorted(ontology_root.rglob("*.yaml")):
        data = load_data(path)
        if not isinstance(data, dict) or data.get("kind") != "OntologyCatalog":
            continue
        catalogs += 1
        for entry in data.get("entries", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            identifier = entry["id"]
            identifiers.append((identifier, path))
            category = _category(identifier)
            if category:
                counts[category] += 1

    duplicates = sorted(
        identifier
        for identifier, count in Counter(identifier for identifier, _ in identifiers).items()
        if count > 1
    )
    for identifier in duplicates:
        path = next(path for candidate, path in identifiers if candidate == identifier)
        issues.append(
            ValidationIssue("error", "duplicate-ontology-id", str(path), "/entries", identifier)
        )

    minimums = {
        "workloads": 6,
        "traffic_regimes": 8,
        "workload_characteristics": 30,
        "lifecycle_phases": 17,
        "bottlenecks": 25,
        "optimizations": 100,
        "metrics": 90,
        "relations": 30,
    }
    for category, minimum in minimums.items():
        actual = counts[category]
        if actual < minimum:
            issues.append(
                ValidationIssue(
                    "error",
                    "ontology-coverage",
                    "reference/ontology/v1",
                    "/",
                    f"{category} requires at least {minimum} entries; found {actual}",
                )
            )
    return OntologyReport(catalogs, len(identifiers), dict(sorted(counts.items())), issues)
