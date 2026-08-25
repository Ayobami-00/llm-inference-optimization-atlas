from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.schemas import SchemaCatalog
from atlas.utilities.repository import repository_relative
from atlas.utilities.serialization import load_data
from atlas.validation.discovery import discover_data_files
from atlas.validation.references import canonical_reference, iter_references


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    location: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "location": self.location,
            "message": self.message,
        }


@dataclass
class LoadedArtifact:
    path: Path
    data: dict[str, Any]


@dataclass
class ValidationReport:
    checked_files: int = 0
    artifacts: list[LoadedArtifact] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_files": self.checked_files,
            "artifacts": len(self.artifacts),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [issue.as_dict() for issue in self.issues],
        }


class Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.schemas = SchemaCatalog(root / "reference" / "schemas" / "v1")

    def validate_path(
        self,
        target: Path,
        *,
        strict: bool = False,
        include_templates: bool = False,
    ) -> ValidationReport:
        report = ValidationReport()
        for path in discover_data_files(target, self.root, include_templates=include_templates):
            report.checked_files += 1
            relative = repository_relative(path, self.root)
            try:
                data = load_data(path)
            except Exception as load_error:
                report.issues.append(
                    ValidationIssue("error", "parse", relative, "/", str(load_error))
                )
                continue
            if not isinstance(data, dict):
                continue
            schema_identifier = data.get("$schema")
            if not isinstance(schema_identifier, str):
                continue
            if schema_identifier == "https://json-schema.org/draft/2020-12/schema":
                continue
            try:
                errors = self.schemas.validate(data, schema_identifier)
            except KeyError as schema_error:
                report.issues.append(
                    ValidationIssue(
                        "error", "unknown-schema", relative, "/$schema", str(schema_error)
                    )
                )
                continue
            report.artifacts.append(LoadedArtifact(path, data))
            for validation_error in errors:
                report.issues.append(
                    ValidationIssue(
                        "error",
                        "schema",
                        relative,
                        validation_error.path,
                        validation_error.message,
                    )
                )

        if strict:
            self._validate_ids_and_references(report)
        return report

    def _validate_ids_and_references(self, report: ValidationReport) -> None:
        known: dict[str, Path] = {}
        identifiers: list[tuple[str, Path]] = []
        for artifact in report.artifacts:
            data = artifact.data
            identifier = data.get("id")
            version = data.get("version")
            if isinstance(identifier, str) and isinstance(version, int):
                reference = canonical_reference(identifier, version, data.get("kind"))
                if reference:
                    identifiers.append((reference, artifact.path))
            if data.get("kind") == "OntologyCatalog" and isinstance(version, int):
                for entry in data.get("entries", []):
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                        continue
                    reference = canonical_reference(entry["id"], version)
                    if reference:
                        identifiers.append((reference, artifact.path))

        counts = Counter(reference for reference, _ in identifiers)
        for reference, path in identifiers:
            if counts[reference] > 1:
                report.issues.append(
                    ValidationIssue(
                        "error",
                        "duplicate-id",
                        repository_relative(path, self.root),
                        "/id",
                        f"Duplicate canonical identity: {reference}",
                    )
                )
            known[reference] = path

        # GitHub issues are the canonical proposal records. A validated contribution
        # manifest acts as their repository-local identity proxy for strict resolution.
        for artifact in report.artifacts:
            data = artifact.data
            schema = data.get("$schema")
            proposal = data.get("proposal")
            issue_url = data.get("issue_url")
            if (
                isinstance(schema, str)
                and schema.endswith("/contributions/contribution-manifest.schema.json")
                and isinstance(proposal, str)
                and proposal.startswith("atlas://proposal/")
                and isinstance(issue_url, str)
                and issue_url.startswith("https://github.com/")
            ):
                known.setdefault(proposal, artifact.path)

        for artifact in report.artifacts:
            for location, reference in iter_references(artifact.data):
                if reference not in known:
                    pointer = "/" + "/".join(str(part) for part in location)
                    report.issues.append(
                        ValidationIssue(
                            "error",
                            "unresolved-reference",
                            repository_relative(artifact.path, self.root),
                            pointer,
                            f"Unresolved reference: {reference}",
                        )
                    )
