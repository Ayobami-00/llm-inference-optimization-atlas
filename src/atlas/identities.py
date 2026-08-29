from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.utilities.serialization import load_data
from atlas.validation.discovery import discover_data_files


@dataclass(frozen=True)
class IdentitySpec:
    kind: str
    prefix: str
    width: int


IDENTITY_SPECS = (
    IdentitySpec("source", "SRC", 4),
    IdentitySpec("dataset", "DS", 3),
    IdentitySpec("evaluator", "EV", 3),
    IdentitySpec("workload-characteristic", "WC", 3),
    IdentitySpec("workload", "W", 3),
    IdentitySpec("workload-spec", "WS", 3),
    IdentitySpec("traffic", "T", 3),
    IdentitySpec("metric", "MET", 3),
    IdentitySpec("optimization", "OPT", 3),
    IdentitySpec("bottleneck", "B", 3),
    IdentitySpec("study", "S", 3),
    IdentitySpec("quality-contract", "QC", 3),
    IdentitySpec("slo", "SLO", 3),
    IdentitySpec("model", "M", 3),
    IdentitySpec("hardware", "HW", 3),
    IdentitySpec("runtime", "RT", 3),
    IdentitySpec("runtime-configuration", "RTCFG", 3),
    IdentitySpec("configuration", "CFG", 3),
    IdentitySpec("hypothesis", "HYP", 3),
    IdentitySpec("experiment", "E", 4),
    IdentitySpec("run", "R", 4),
    IdentitySpec("comparison", "CMP", 4),
    IdentitySpec("finding", "F", 4),
    IdentitySpec("decision", "DEC", 4),
    IdentitySpec("replication", "REP", 4),
)


def _aliases(spec: IdentitySpec) -> set[str]:
    return {
        spec.kind,
        spec.kind.replace("-", "_"),
        spec.prefix.lower(),
        spec.prefix,
    }


def identity_spec(value: str) -> IdentitySpec:
    normalized = value.strip()
    for spec in IDENTITY_SPECS:
        if normalized in _aliases(spec) or normalized.lower() in _aliases(spec):
            return spec
    choices = ", ".join(spec.kind for spec in IDENTITY_SPECS)
    raise ValueError(f"Unknown artifact identity kind {value!r}; choose one of: {choices}")


def next_identifiers(root: Path, kind: str, *, count: int = 1) -> list[str]:
    """Return the next monotonically increasing canonical identities."""

    if count < 1:
        raise ValueError("Identity count must be at least one")
    spec = identity_spec(kind)
    pattern = re.compile(rf"^{re.escape(spec.prefix)}(?P<number>\d{{{spec.width}}})$")
    maximum = 0
    for path in discover_data_files(root, root):
        try:
            data: Any = load_data(path)
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            continue
        match = pattern.fullmatch(data["id"])
        if match:
            maximum = max(maximum, int(match.group("number")))
    limit = 10**spec.width - 1
    if maximum + count > limit:
        raise ValueError(f"The {spec.kind} identity namespace is exhausted")
    return [
        f"{spec.prefix}{number:0{spec.width}d}"
        for number in range(maximum + 1, maximum + count + 1)
    ]


def next_identifier(root: Path, kind: str) -> str:
    return next_identifiers(root, kind)[0]
