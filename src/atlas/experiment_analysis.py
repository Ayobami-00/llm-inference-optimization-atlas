from __future__ import annotations

from typing import Any


class ExperimentAnalysisError(ValueError):
    """An experiment's cross-field analysis contract is inconsistent."""


def planned_effect_metrics(experiment: dict[str, Any]) -> list[str]:
    """Return and validate the experiment's ordered comparison-effect metrics."""
    metrics = experiment.get("metrics")
    if not isinstance(metrics, dict):
        raise ExperimentAnalysisError("Experiment metrics must be an object")

    groups: dict[str, list[str]] = {}
    for name in ("primary", "secondary", "guardrails"):
        references = metrics.get(name, [])
        if not isinstance(references, list) or not all(
            isinstance(reference, str) for reference in references
        ):
            raise ExperimentAnalysisError(f"Experiment metrics.{name} must be a list of references")
        groups[name] = references

    primary = groups["primary"]
    if not primary:
        raise ExperimentAnalysisError("Experiment metrics.primary must be non-empty")

    analysis = experiment.get("analysis", {})
    if not isinstance(analysis, dict):
        raise ExperimentAnalysisError("Experiment analysis must be an object")
    planned = analysis.get("effect_metrics")
    if planned is None:
        return list(primary)
    if not isinstance(planned, list) or not planned:
        raise ExperimentAnalysisError("Experiment analysis.effect_metrics must be a non-empty list")
    if not all(isinstance(reference, str) for reference in planned):
        raise ExperimentAnalysisError(
            "Experiment analysis.effect_metrics must contain only metric references"
        )
    if len(planned) != len(set(planned)):
        raise ExperimentAnalysisError(
            "Experiment analysis.effect_metrics must not contain duplicates"
        )

    declared = set(groups["primary"] + groups["secondary"] + groups["guardrails"])
    undeclared = [reference for reference in planned if reference not in declared]
    if undeclared:
        raise ExperimentAnalysisError(
            "Experiment analysis.effect_metrics contains undeclared metrics: "
            + ", ".join(undeclared)
        )
    missing_primary = [reference for reference in primary if reference not in planned]
    if missing_primary:
        raise ExperimentAnalysisError(
            "Experiment analysis.effect_metrics must include every primary metric; missing: "
            + ", ".join(missing_primary)
        )
    return list(planned)
