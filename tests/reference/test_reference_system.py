from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from ruamel.yaml import YAML

ROOT = Path(__file__).parents[2]
SCHEMA_ROOT = ROOT / "reference" / "schemas" / "v1"
ONTOLOGY_ROOT = ROOT / "reference" / "ontology" / "v1"
SOURCE_ROOT = ROOT / "reference" / "sources" / "v1"
TEMPLATE_ROOT = ROOT / "reference" / "templates" / "v1"
ATLAS_REFERENCE = re.compile(
    r"^atlas://(?P<kind>[a-z][a-z0-9-]*)/(?P<id>[A-Z][A-Z0-9-]*)@v(?P<version>[1-9][0-9]*)$"
)


def yaml_loader() -> YAML:
    loader = YAML(typ="safe")
    loader.version = (1, 2)
    return loader


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml_loader().load(path.read_text())
    assert isinstance(value, dict), path
    return value


def schema_registry() -> Registry[Any]:
    resources = []
    for path in sorted(SCHEMA_ROOT.rglob("*.json")):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def iter_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in iter_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in iter_strings(child)]
    return []


def ontology_catalogs() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, load_yaml(path)) for path in sorted(ONTOLOGY_ROOT.rglob("*.yaml"))]


def source_records() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, load_yaml(path)) for path in sorted(SOURCE_ROOT.rglob("*.yaml"))]


def artifact_templates() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, load_yaml(path)) for path in sorted(TEMPLATE_ROOT.rglob("*.yaml"))]


@pytest.mark.parametrize(("path", "record"), source_records(), ids=lambda value: str(value))
def test_source_records_validate(path: Path, record: dict[str, Any]) -> None:
    schema = json.loads((SCHEMA_ROOT / "common" / "source.schema.json").read_text())
    errors = list(
        Draft202012Validator(
            schema,
            registry=schema_registry(),
            format_checker=FormatChecker(),
        ).iter_errors(record)
    )
    assert errors == [], f"{path}: {errors}"


@pytest.mark.parametrize(("path", "catalog"), ontology_catalogs(), ids=lambda value: str(value))
def test_ontology_catalogs_validate(path: Path, catalog: dict[str, Any]) -> None:
    schema = json.loads((SCHEMA_ROOT / "common" / "ontology-catalog.schema.json").read_text())
    errors = list(Draft202012Validator(schema, registry=schema_registry()).iter_errors(catalog))
    assert errors == [], f"{path}: {errors}"


def test_source_ids_are_complete_and_unique() -> None:
    identifiers = [record["id"] for _, record in source_records()]
    assert len(identifiers) >= 100
    assert len(identifiers) == len(set(identifiers))
    assert sorted(identifiers) == [f"SRC{number:04d}" for number in range(1, len(identifiers) + 1)]


def test_ontology_ids_are_globally_unique() -> None:
    identifiers = [
        entry["id"] for _, catalog in ontology_catalogs() for entry in catalog["entries"]
    ]
    duplicates = [identifier for identifier, count in Counter(identifiers).items() if count > 1]
    assert duplicates == []


def test_v1_ontology_meets_minimum_coverage() -> None:
    counts: Counter[str] = Counter()
    for _, catalog in ontology_catalogs():
        for entry in catalog["entries"]:
            identifier = entry["id"]
            if identifier.startswith("OPT"):
                counts["optimizations"] += 1
            elif identifier.startswith("MET"):
                counts["metrics"] += 1
            elif identifier.startswith("WC"):
                counts["characteristics"] += 1
            elif identifier.startswith("B") and identifier[1:].isdigit():
                counts["bottlenecks"] += 1
            elif identifier.startswith("REL-"):
                counts["relations"] += 1
            elif identifier.startswith("PHASE-"):
                counts["lifecycle"] += 1

    assert counts["optimizations"] >= 100
    assert counts["metrics"] >= 90
    assert counts["characteristics"] >= 30
    assert counts["bottlenecks"] >= 25
    assert counts["relations"] >= 30
    assert counts["lifecycle"] >= 17


def test_all_ontology_references_resolve() -> None:
    known_ids = {record["id"] for _, record in source_records()}
    known_ids.update(
        entry["id"] for _, catalog in ontology_catalogs() for entry in catalog["entries"]
    )

    unresolved: list[tuple[Path, str]] = []
    for path, catalog in ontology_catalogs():
        for value in iter_strings(catalog):
            match = ATLAS_REFERENCE.match(value)
            if match and match.group("id") not in known_ids:
                unresolved.append((path, value))

    assert unresolved == []


def test_sources_are_passive_records() -> None:
    forbidden = {"supports", "supported_by", "referenced_by"}
    for path, record in source_records():
        assert forbidden.isdisjoint(record), path


@pytest.mark.parametrize(("path", "template"), artifact_templates(), ids=lambda value: str(value))
def test_artifact_templates_match_their_declared_schema(
    path: Path, template: dict[str, Any]
) -> None:
    registry = schema_registry()
    schema_uri = template["$schema"]
    schema = registry.contents(schema_uri)
    errors = list(
        Draft202012Validator(
            schema,
            registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(template)
    )
    assert errors == [], f"{path}: {errors}"
