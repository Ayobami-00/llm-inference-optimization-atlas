from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

ATLAS_REFERENCE_PATTERN = re.compile(
    r"^atlas://(?P<kind>[a-z][a-z0-9-]*)/(?P<id>[A-Z][A-Z0-9-]*)@v(?P<version>[1-9][0-9]*)$"
)

ID_KIND_PREFIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^SRC\d{4}$"), "source"),
    (re.compile(r"^DS\d{3}$"), "dataset"),
    (re.compile(r"^EV\d{3}$"), "evaluator"),
    (re.compile(r"^WC\d{3}$"), "workload-characteristic"),
    (re.compile(r"^W\d{3}$"), "workload"),
    (re.compile(r"^WS\d{3}$"), "workload-spec"),
    (re.compile(r"^T\d{3}$"), "traffic"),
    (re.compile(r"^MET\d{3}$"), "metric"),
    (re.compile(r"^OPT\d{3}$"), "optimization"),
    (re.compile(r"^B\d{3}$"), "bottleneck"),
    (re.compile(r"^S\d{3}$"), "study"),
    (re.compile(r"^QC\d{3}$"), "quality-contract"),
    (re.compile(r"^SLO\d{3}$"), "slo"),
    (re.compile(r"^M\d{3}$"), "model"),
    (re.compile(r"^HW\d{3}$"), "hardware"),
    (re.compile(r"^RT\d{3}$"), "runtime"),
    (re.compile(r"^RTCFG\d{3}$"), "runtime-configuration"),
    (re.compile(r"^CFG\d{3}$"), "configuration"),
    (re.compile(r"^HYP\d{3}$"), "hypothesis"),
    (re.compile(r"^E\d{4}$"), "experiment"),
    (re.compile(r"^R\d{4}$"), "run"),
    (re.compile(r"^CMP\d{4}$"), "comparison"),
    (re.compile(r"^F\d{4}$"), "finding"),
    (re.compile(r"^DEC\d{4}$"), "decision"),
    (re.compile(r"^REP\d{4}$"), "replication"),
    (re.compile(r"^P\d{4}$"), "proposal"),
)

KIND_NAMES = {
    "Source": "source",
    "DatasetRevision": "dataset",
    "Evaluator": "evaluator",
    "WorkloadArchetype": "workload",
    "WorkloadSpec": "workload-spec",
    "TrafficProfile": "traffic",
    "QualityContract": "quality-contract",
    "SLOProfile": "slo",
    "ModelRevision": "model",
    "HardwareTopology": "hardware",
    "RuntimeBuild": "runtime",
    "RuntimeConfiguration": "runtime-configuration",
    "Optimization": "optimization",
    "Bottleneck": "bottleneck",
    "Hypothesis": "hypothesis",
    "Study": "study",
    "Configuration": "configuration",
    "Experiment": "experiment",
    "RunRecord": "run",
    "Comparison": "comparison",
    "Finding": "finding",
    "DeploymentDecision": "decision",
    "Replication": "replication",
    "Proposal": "proposal",
}


def iter_references(
    value: Any, location: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, str) and value.startswith("atlas://"):
        yield location, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_references(child, (*location, index))
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_references(child, (*location, key))


def infer_uri_kind(identifier: str, declared_kind: str | None = None) -> str | None:
    if declared_kind and declared_kind in KIND_NAMES:
        return KIND_NAMES[declared_kind]
    for pattern, kind in ID_KIND_PREFIXES:
        if pattern.fullmatch(identifier):
            return kind
    return None


def canonical_reference(
    identifier: str, version: int, declared_kind: str | None = None
) -> str | None:
    kind = infer_uri_kind(identifier, declared_kind)
    return f"atlas://{kind}/{identifier}@v{version}" if kind else None
