from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).parents[2]
SCHEMA_ROOT = ROOT / "reference" / "schemas" / "v1"


def load_schemas() -> list[tuple[Path, dict[str, Any]]]:
    return [(path, json.loads(path.read_text())) for path in sorted(SCHEMA_ROOT.rglob("*.json"))]


def schema_registry() -> Registry[Any]:
    resources = [(schema["$id"], Resource.from_contents(schema)) for _, schema in load_schemas()]
    return Registry().with_resources(resources)


@pytest.mark.parametrize(("path", "schema"), load_schemas(), ids=lambda value: str(value))
def test_schema_is_valid_draft_2020_12(path: Path, schema: dict[str, Any]) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", path
    Draft202012Validator.check_schema(schema)


def test_schema_ids_are_unique_and_canonical() -> None:
    identifiers = [schema["$id"] for _, schema in load_schemas()]
    assert len(identifiers) == len(set(identifiers))
    assert all(
        identifier.startswith(
            "https://ayobami-00.github.io/llm-inference-optimization-atlas/schemas/v1/"
        )
        for identifier in identifiers
    )


def test_valid_source_fixture() -> None:
    source_schema = json.loads((SCHEMA_ROOT / "common" / "source.schema.json").read_text())
    instance = json.loads((ROOT / "tests" / "fixtures" / "valid" / "source.json").read_text())
    validator = Draft202012Validator(
        source_schema,
        registry=schema_registry(),
        format_checker=FormatChecker(),
    )
    assert list(validator.iter_errors(instance)) == []


def test_invalid_source_fixture() -> None:
    source_schema = json.loads((SCHEMA_ROOT / "common" / "source.schema.json").read_text())
    instance = json.loads((ROOT / "tests" / "fixtures" / "invalid" / "source.json").read_text())
    validator = Draft202012Validator(
        source_schema,
        registry=schema_registry(),
        format_checker=FormatChecker(),
    )
    assert list(validator.iter_errors(instance))
