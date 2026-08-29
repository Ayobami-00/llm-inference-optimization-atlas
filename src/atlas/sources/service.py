from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.utilities.serialization import dump_json, load_data
from atlas.validation import ValidationIssue, Validator


@dataclass(frozen=True)
class SourceReport:
    records: int
    by_type: dict[str, int]
    issues: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "records": self.records,
            "by_type": self.by_type,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def load_sources(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    records = []
    for path in sorted((root / "reference" / "sources" / "v1").rglob("*.yaml")):
        data = load_data(path)
        if isinstance(data, dict):
            records.append((path, data))
    return records


def check_sources(root: Path) -> SourceReport:
    source_root = root / "reference" / "sources" / "v1"
    report = Validator(root).validate_path(source_root)
    records = load_sources(root)
    issues = list(report.issues)
    identifiers = [record.get("id") for _, record in records]
    for identifier, count in Counter(identifiers).items():
        if count > 1:
            issues.append(
                ValidationIssue(
                    "error", "duplicate-source-id", "reference/sources/v1", "/id", str(identifier)
                )
            )
    if len(records) < 100:
        issues.append(
            ValidationIssue(
                "error",
                "source-coverage",
                "reference/sources/v1",
                "/",
                f"V1 requires at least 100 records; found {len(records)}",
            )
        )
    by_type = Counter(str(record.get("type")) for _, record in records)
    return SourceReport(len(records), dict(sorted(by_type.items())), issues)


def _bibtex_text(records: list[tuple[Path, dict[str, Any]]]) -> str:
    entries = []
    for _, record in records:
        source_type = record.get("type")
        entry_type = "article" if source_type == "paper" else "misc"
        authors = " and ".join(record.get("source_authors", []))
        title = str(record.get("title", "")).replace("{", "").replace("}", "")
        published = record.get("published", {})
        fields = [
            f"  title = {{{title}}}",
            f"  author = {{{authors}}}",
            f"  url = {{{record.get('url', '')}}}",
        ]
        if published.get("year"):
            fields.append(f"  year = {{{published['year']}}}")
        if published.get("venue"):
            fields.append(f"  howpublished = {{{published['venue']}}}")
        identifiers = record.get("identifiers", {})
        if identifiers.get("doi"):
            fields.append(f"  doi = {{{identifiers['doi']}}}")
        if identifiers.get("arxiv"):
            fields.append(f"  eprint = {{{identifiers['arxiv']}}}")
        entries.append(f"@{entry_type}{{{record['id']},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + "\n"


def build_source_catalog(root: Path) -> tuple[Path, Path]:
    records = load_sources(root)
    output_root = root / "build" / "sources"
    catalog_path = output_root / "catalog.json"
    bibliography_path = output_root / "bibliography.bib"
    catalog = {
        "schema_version": 1,
        "records": [record for _, record in sorted(records, key=lambda item: item[1]["id"])],
        "indexes": {
            "by_id": {
                record["id"]: index
                for index, (_, record) in enumerate(sorted(records, key=lambda item: item[1]["id"]))
            },
            "by_topic": _topic_index(records),
        },
    }
    dump_json(catalog, catalog_path)
    bibliography_path.parent.mkdir(parents=True, exist_ok=True)
    bibliography_path.write_text(_bibtex_text(records))
    return catalog_path, bibliography_path


def _topic_index(records: list[tuple[Path, dict[str, Any]]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for _, record in records:
        for topic in record.get("topics", []):
            normalized = re.sub(r"[^a-z0-9]+", "-", str(topic).lower()).strip("-")
            index.setdefault(normalized, []).append(record["id"])
    return {topic: sorted(identifiers) for topic, identifiers in sorted(index.items())}
