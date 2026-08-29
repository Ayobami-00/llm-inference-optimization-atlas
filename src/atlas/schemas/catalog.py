from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


@dataclass(frozen=True)
class SchemaError:
    path: str
    message: str


class SchemaCatalog:
    def __init__(self, schema_root: Path) -> None:
        self.schema_root = schema_root
        self._schemas: dict[str, dict[str, Any]] = {}
        for path in sorted(schema_root.rglob("*.json")):
            schema = json.loads(path.read_text())
            identifier = schema.get("$id")
            if not isinstance(identifier, str):
                raise ValueError(f"Schema has no $id: {path}")
            if identifier in self._schemas:
                raise ValueError(f"Duplicate schema $id: {identifier}")
            self._schemas[identifier] = schema
        resources = [
            (identifier, Resource.from_contents(schema))
            for identifier, schema in self._schemas.items()
        ]
        self.registry: Registry[Any] = Registry().with_resources(resources)

    @property
    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas))

    def check(self) -> list[SchemaError]:
        errors: list[SchemaError] = []
        for identifier, schema in sorted(self._schemas.items()):
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as error:  # jsonschema exposes several schema error subclasses
                errors.append(SchemaError(identifier, str(error)))
        return errors

    def schema(self, identifier: str) -> dict[str, Any]:
        try:
            return self._schemas[identifier]
        except KeyError as error:
            raise KeyError(f"Unknown Atlas schema: {identifier}") from error

    def validate(self, instance: Any, schema_identifier: str) -> list[SchemaError]:
        schema = self.schema(schema_identifier)
        validator = Draft202012Validator(
            schema,
            registry=self.registry,
            format_checker=FormatChecker(),
        )
        errors = []
        for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.path)):
            location = "/" + "/".join(str(part) for part in error.absolute_path)
            errors.append(SchemaError(location or "/", error.message))
        return errors
