from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas.schemas import SchemaCatalog
from atlas.utilities.serialization import load_data

ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "registry"


def _records() -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(REGISTRY.rglob("*.yaml")):
        value = load_data(path)
        assert isinstance(value, dict)
        records.append((path, value))
    return records


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


def test_registry_records_validate_against_declared_schemas() -> None:
    catalog = SchemaCatalog(ROOT / "reference" / "schemas" / "v1")
    records = _records()
    assert records
    for path, record in records:
        assert catalog.validate(record, record["$schema"]) == [], path


def test_bootstrap_registry_identities_are_unique() -> None:
    identifiers = [record["id"] for _, record in _records()]
    assert len(identifiers) == len(set(identifiers))
    assert {identifier for identifier in identifiers if identifier.startswith("M")} == {
        "M001",
        "M002",
        "M003",
        "M004",
        "M005",
    }
    assert {identifier for identifier in identifiers if identifier.startswith("RT")} == {
        "RT001",
        "RT002",
        "RT003",
    }


def test_models_and_runtimes_are_immutably_pinned() -> None:
    for _, record in _records():
        if record["kind"] == "ModelRevision":
            assert re.fullmatch(r"[0-9a-f]{40}", record["revision"])
            for artifact in record["artifacts"]:
                assert record["revision"] in artifact["url"]
                assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        if record["kind"] == "RuntimeBuild":
            assert re.fullmatch(r"[0-9a-f]{40}", record["upstream"]["commit"])
            assert re.fullmatch(r"[0-9a-f]{64}", record["build"]["artifact_sha256"])


def test_hardware_inventory_contains_no_private_identifier_fields() -> None:
    hardware = load_data(REGISTRY / "hardware" / "HW001-local-apple-m3.yaml")
    assert isinstance(hardware, dict)
    forbidden = {
        "serial",
        "serial_number",
        "uuid",
        "hostname",
        "username",
        "mac_address",
        "private_ip",
        "cloud_account",
    }
    present = _keys({key: value for key, value in hardware.items() if key != "redactions"})
    assert not (forbidden & present)
    assert set(hardware["redactions"]) == {
        "serial_number",
        "uuid",
        "mac_address",
        "hostname",
        "username",
        "private_ip",
        "cloud_account",
    }
