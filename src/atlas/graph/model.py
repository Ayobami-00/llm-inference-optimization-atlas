from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Entity:
    reference: str
    node: dict[str, Any]
    artifact: dict[str, Any]
    path: Path


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    relation: str
    assertion_level: str = "structural"
    evidence: tuple[str, ...] = ()
    scope: dict[str, Any] | None = None
    confidence: str = "none"
    source_path: str = ""
    derived: bool = True
