from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def yaml_loader() -> YAML:
    loader = YAML(typ="safe")
    loader.version = (1, 2)
    return loader


def yaml_writer() -> YAML:
    writer = YAML()
    writer.version = (1, 2)
    writer.default_flow_style = False
    writer.indent(mapping=2, sequence=4, offset=2)
    return writer


def load_data(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml_loader().load(path.read_text())
    raise ValueError(f"Unsupported data file: {path}")


def dump_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
