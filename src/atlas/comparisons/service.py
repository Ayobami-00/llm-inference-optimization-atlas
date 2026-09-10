from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

import numpy as np

from atlas.experiment_analysis import ExperimentAnalysisError, planned_effect_metrics
from atlas.identities import next_identifier
from atlas.utilities.serialization import load_data, yaml_writer


class ComparisonError(RuntimeError):
    """A controlled comparison could not be produced."""


def _finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _find_experiment(root: Path, value: str) -> Path:
    candidates = []
    for path in sorted((root / "studies").glob("S*-*/v*/experiments/E*/experiment.yaml")):
        if value in {path.parent.name, path.parent.parent.parent.parent.name}:
            candidates.append(path.parent)
            continue
        data = load_data(path)
        if isinstance(data, dict) and value in {data.get("id"), data.get("slug")}:
            candidates.append(path.parent)
    unique = list(dict.fromkeys(candidates))
    if len(unique) != 1:
        raise ComparisonError(f"Expected one experiment matching {value!r}; found {len(unique)}")
    return unique[0]


def _artifact_for_reference(root: Path, reference: str) -> dict[str, Any]:
    match = re.fullmatch(
        r"atlas://[a-z][a-z0-9-]*/(?P<id>[A-Z][A-Z0-9-]*)@v(?P<version>[1-9][0-9]*)",
        reference,
    )
    if not match:
        raise ComparisonError(f"Malformed artifact reference: {reference}")
    identifier = match.group("id")
    for path in sorted(root.glob("**/*.yaml")):
        if any(part in {".atlas", "build", "reference"} for part in path.parts):
            continue
        data = load_data(path)
        if (
            isinstance(data, dict)
            and data.get("id") == identifier
            and data.get("version") == int(match.group("version"))
        ):
            return data
    raise ComparisonError(f"Unresolved comparison artifact: {reference}")


def _accepted_runs(experiment_root: Path) -> list[tuple[dict[str, Any], Path]]:
    values = []
    for path in sorted((experiment_root / "runs").glob("R*/run.yaml")):
        run = load_data(path)
        if not isinstance(run, dict):
            continue
        if (
            run.get("outcome") == "complete"
            and run.get("quality", {}).get("passed") is True
            and run.get("validation", {}).get("passed") is True
        ):
            values.append((run, path.parent))
    return values


def _scope_key(scope: dict[str, Any]) -> str:
    if not scope:
        raise ComparisonError("Metric breakdown scope must not be empty")
    if not all(isinstance(key, str) for key in scope):
        raise ComparisonError("Metric breakdown scope values must be scalar JSON values")
    for value in scope.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ComparisonError("Metric breakdown scope values must be finite")
        if not isinstance(value, (str, int, float, bool)):
            raise ComparisonError("Metric breakdown scope values must be scalar JSON values")
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _metric_observations(
    run_root: Path, metric: str
) -> tuple[float, str, dict[str, tuple[dict[str, Any], float]]]:
    summary = load_data(run_root / "metrics" / "summary.json")
    if not isinstance(summary, dict):
        raise ComparisonError(f"Summary must be an object: {run_root}")
    metrics = summary.get("metrics", {})
    value = metrics.get(metric) if isinstance(metrics, dict) else None
    if not isinstance(value, dict) or not _finite_number(value.get("value")):
        raise ComparisonError(f"Summary {run_root} has no numeric {metric} value")
    breakdown = value.get("breakdown", [])
    if not isinstance(breakdown, list):
        raise ComparisonError(f"Summary {run_root} has invalid {metric} breakdown")
    scoped: dict[str, tuple[dict[str, Any], float]] = {}
    for index, observation in enumerate(breakdown):
        if not isinstance(observation, dict):
            raise ComparisonError(
                f"Summary {run_root} {metric} breakdown {index} must be an object"
            )
        scope = observation.get("scope")
        scoped_value = observation.get("value")
        if not isinstance(scope, dict) or not _finite_number(scoped_value):
            raise ComparisonError(
                f"Summary {run_root} {metric} breakdown {index} requires scope and value"
            )
        key = _scope_key(scope)
        if key in scoped:
            raise ComparisonError(f"Summary {run_root} has duplicate {metric} scope {key}")
        scoped[key] = (scope, float(scoped_value))
    return float(value["value"]), str(value.get("unit", "1")), scoped


def _summary_slo_eligible(run_root: Path) -> bool:
    summary = load_data(run_root / "metrics" / "summary.json")
    if not isinstance(summary, dict):
        raise ComparisonError(f"Summary must be an object: {run_root}")
    if "slo_eligible" in summary:
        eligible = summary["slo_eligible"]
        if not isinstance(eligible, bool):
            raise ComparisonError(f"Summary {run_root} has non-boolean slo_eligible")
        return eligible
    passed = summary.get("slo_passed", False)
    if not isinstance(passed, bool):
        raise ComparisonError(f"Summary {run_root} has non-boolean slo_passed")
    return passed


def _bootstrap_interval(
    baseline: np.ndarray,
    candidate: np.ndarray,
    *,
    paired: bool,
    resamples: int,
    confidence: float,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    effects = np.empty(resamples, dtype=np.float64)
    if paired:
        differences = candidate - baseline
        for index in range(resamples):
            sample = rng.integers(0, len(differences), len(differences))
            effects[index] = float(np.mean(differences[sample]))
    else:
        for index in range(resamples):
            baseline_sample = rng.choice(baseline, len(baseline), replace=True)
            candidate_sample = rng.choice(candidate, len(candidate), replace=True)
            effects[index] = float(np.mean(candidate_sample) - np.mean(baseline_sample))
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(effects, [alpha, 1.0 - alpha])
    return float(lower), float(upper)


def _metric_direction(root: Path, metric_reference: str) -> str:
    metric_id = metric_reference.rsplit("/", 1)[-1].split("@", 1)[0]
    for path in sorted((root / "reference" / "ontology" / "v1" / "metrics").glob("*.yaml")):
        data = load_data(path)
        if not isinstance(data, dict):
            continue
        for entry in data.get("entries", []):
            if isinstance(entry, dict) and entry.get("id") == metric_id:
                return str(entry.get("direction", "informational"))
    raise ComparisonError(f"No metric definition for {metric_reference}")


def _comparison_result(direction: str, lower: float, upper: float) -> str:
    if direction == "lower_is_better":
        if upper < 0:
            return "improvement"
        if lower > 0:
            return "degradation"
    elif direction == "higher_is_better":
        if lower > 0:
            return "improvement"
        if upper < 0:
            return "degradation"
    return "no_significant_effect"


def _relative_effect(*, absolute: float, baseline: float) -> float | None:
    if baseline == 0.0:
        return None
    return absolute / baseline


def _reference_id(reference: str) -> str:
    return reference.rsplit("/", 1)[-1].split("@", 1)[0]


def _planned_contrasts(experiment: dict[str, Any]) -> list[dict[str, str]]:
    baseline = str(experiment["baseline"])
    candidates = [str(value) for value in experiment.get("candidates", [])]
    allowed = {baseline, *candidates}
    raw = experiment.get("analysis", {}).get("contrasts")
    if raw is None:
        return [
            {
                "id": f"{_reference_id(baseline).lower()}-vs-{_reference_id(candidate).lower()}",
                "baseline": baseline,
                "candidate": candidate,
            }
            for candidate in candidates
        ]
    if not isinstance(raw, list) or not raw:
        raise ComparisonError("Experiment analysis.contrasts must be a non-empty list")
    contrasts: list[dict[str, str]] = []
    identifiers: set[str] = set()
    pairs: set[frozenset[str]] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ComparisonError(f"Experiment contrast {index} must be an object")
        identifier = value.get("id")
        contrast_baseline = value.get("baseline")
        contrast_candidate = value.get("candidate")
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier
        ):
            raise ComparisonError(f"Experiment contrast {index} has an invalid id")
        if contrast_baseline not in allowed or contrast_candidate not in allowed:
            raise ComparisonError(
                f"Experiment contrast {identifier} references a configuration outside "
                "the experiment"
            )
        if contrast_baseline == contrast_candidate:
            raise ComparisonError(
                f"Experiment contrast {identifier} must compare different configurations"
            )
        pair = frozenset((str(contrast_baseline), str(contrast_candidate)))
        if identifier in identifiers or pair in pairs:
            raise ComparisonError(f"Experiment contrast {identifier} is duplicated")
        identifiers.add(identifier)
        pairs.add(pair)
        contrasts.append(
            {
                "id": identifier,
                "baseline": str(contrast_baseline),
                "candidate": str(contrast_candidate),
            }
        )
    return contrasts


def _analysis_settings(experiment: dict[str, Any]) -> tuple[int, float, int]:
    analysis = experiment.get("analysis", {})
    if not isinstance(analysis, dict):
        raise ComparisonError("Experiment analysis must be an object")
    resamples = analysis.get("resamples", 10000)
    confidence = analysis.get("confidence_level", 0.95)
    seed = analysis.get("seed", 20260825)
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 1:
        raise ComparisonError("Experiment analysis.resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or not 0 < confidence < 1:
        raise ComparisonError("Experiment analysis.confidence_level must be between zero and one")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ComparisonError("Experiment analysis.seed must be an integer")
    return resamples, float(confidence), seed


def _planned_effect_metrics(experiment: dict[str, Any]) -> list[str]:
    try:
        return planned_effect_metrics(experiment)
    except ExperimentAnalysisError as error:
        raise ComparisonError(str(error)) from error


def _pairing_key(run: dict[str, Any]) -> tuple[int, int]:
    return int(run["replicate"]), int(run["seed"])


def _runs_by_pairing_key(
    runs: list[tuple[dict[str, Any], Path]], configuration: str
) -> dict[tuple[int, int], tuple[dict[str, Any], Path]]:
    keyed: dict[tuple[int, int], tuple[dict[str, Any], Path]] = {}
    for run, path in runs:
        if run.get("configuration") != configuration:
            continue
        key = _pairing_key(run)
        if key in keyed:
            raise ComparisonError(
                f"Duplicate accepted replicate/seed pair {key} for {configuration}"
            )
        keyed[key] = (run, path)
    return keyed


def _effect(
    root: Path,
    metric_reference: str,
    baseline_values: np.ndarray,
    candidate_values: np.ndarray,
    *,
    unit: str,
    paired: bool,
    resamples: int,
    confidence: float,
    seed: int,
    scope: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    baseline_mean = float(np.mean(baseline_values))
    candidate_mean = float(np.mean(candidate_values))
    absolute = candidate_mean - baseline_mean
    lower, upper = _bootstrap_interval(
        baseline_values,
        candidate_values,
        paired=paired,
        resamples=resamples,
        confidence=confidence,
        seed=seed,
    )
    value: dict[str, Any] = {
        "metric": metric_reference,
        "baseline": baseline_mean,
        "candidate": candidate_mean,
        "absolute": absolute,
        "relative": _relative_effect(absolute=absolute, baseline=baseline_mean),
        "confidence_interval": {
            "lower": lower,
            "upper": upper,
            "level": confidence,
        },
        "unit": unit,
    }
    if scope is not None:
        value["scope"] = scope
    direction = _metric_direction(root, metric_reference)
    return value, _comparison_result(direction, lower, upper)


def _matching_scope_keys(
    baseline: list[dict[str, tuple[dict[str, Any], float]]],
    candidate: list[dict[str, tuple[dict[str, Any], float]]],
    *,
    metric: str,
    contrast: str,
) -> set[str]:
    expected = set(baseline[0])
    if any(set(scopes) != expected for scopes in baseline + candidate):
        raise ComparisonError(f"Metric breakdown scope mismatch for {metric} in {contrast}")
    return expected


def _consistent_unit(
    observations: list[tuple[float, str, dict[str, tuple[dict[str, Any], float]]]],
    metric: str,
) -> str:
    units = {unit for _, unit, _ in observations}
    if len(units) != 1:
        raise ComparisonError(f"Metric unit mismatch for {metric}: {sorted(units)}")
    return units.pop()


def _compatibility(
    baseline: dict[str, Any], candidate: dict[str, Any], changed_factors: list[str]
) -> list[str]:
    changed_text = " ".join(changed_factors).lower().replace("-", "_")
    checks = []
    for axis in ("workload", "quality", "slo", "model", "hardware", "runtime"):
        if baseline.get(axis) == candidate.get(axis):
            checks.append(f"{axis} identity is frozen")
        elif axis in changed_text:
            checks.append(f"{axis} is deliberately changed")
        else:
            raise ComparisonError(f"Incompatible configurations: unexpected {axis} change")
    return checks


def _existing_comparison(
    experiment_root: Path,
    baseline_runs: list[str],
    candidate_runs: list[str],
) -> Path | None:
    for path in sorted((experiment_root / "comparisons").glob("CMP*.yaml")):
        comparison = load_data(path)
        if not isinstance(comparison, dict):
            continue
        if (
            comparison.get("baseline_runs") == baseline_runs
            and comparison.get("candidate_runs") == candidate_runs
        ):
            return path
    return None


def _validate_existing_effect_plan(
    path: Path,
    planned_metrics: list[str],
    *,
    require_frozen_plan: bool,
) -> None:
    comparison = load_data(path)
    if not isinstance(comparison, dict):
        raise ComparisonError(f"Existing comparison is not an object: {path}")

    method = comparison.get("method")
    frozen_metrics = method.get("effect_metrics") if isinstance(method, dict) else None
    if frozen_metrics is not None and frozen_metrics != planned_metrics:
        raise ComparisonError(
            f"Existing comparison {path} has stale frozen effect metrics: "
            f"expected {planned_metrics}, found {frozen_metrics}"
        )
    if require_frozen_plan and frozen_metrics is None:
        raise ComparisonError(
            f"Existing comparison {path} lacks the frozen preregistered effect metrics"
        )

    effects = comparison.get("effects")
    if not isinstance(effects, list):
        raise ComparisonError(f"Existing comparison {path} has invalid effects")
    observed_metrics: list[str] = []
    for effect in effects:
        metric = effect.get("metric") if isinstance(effect, dict) else None
        if not isinstance(metric, str):
            raise ComparisonError(f"Existing comparison {path} has an effect without a metric")
        if metric not in observed_metrics:
            observed_metrics.append(metric)
    if observed_metrics != planned_metrics:
        raise ComparisonError(
            f"Existing comparison {path} has stale generated effects: "
            f"expected metric order {planned_metrics}, found {observed_metrics}"
        )


def _comparison_output_path(experiment_root: Path, comparison_id: str) -> Path:
    output = experiment_root / "comparisons" / f"{comparison_id}.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def compare_experiment(root: Path, value: str) -> list[Path]:
    experiment_root = _find_experiment(root, value)
    experiment = load_data(experiment_root / "experiment.yaml")
    if not isinstance(experiment, dict):
        raise ComparisonError(f"Invalid experiment: {experiment_root}")
    runs = _accepted_runs(experiment_root)
    resamples, confidence, analysis_seed = _analysis_settings(experiment)
    effect_metrics = _planned_effect_metrics(experiment)
    primary_metrics = set(experiment["metrics"]["primary"])
    analysis = experiment.get("analysis", {})
    requires_frozen_effect_plan = isinstance(analysis, dict) and "effect_metrics" in analysis

    outputs = []
    for contrast in _planned_contrasts(experiment):
        baseline_reference = contrast["baseline"]
        candidate_reference = contrast["candidate"]
        baseline_by_key = _runs_by_pairing_key(runs, baseline_reference)
        candidate_by_key = _runs_by_pairing_key(runs, candidate_reference)
        common_keys = sorted(set(baseline_by_key) & set(candidate_by_key))
        if len(common_keys) < 3:
            raise ComparisonError(
                f"Accepted comparison {contrast['id']} requires at least three paired "
                "replicate/seed runs"
            )
        selected_baseline = [baseline_by_key[key] for key in common_keys]
        selected_candidate = [candidate_by_key[key] for key in common_keys]
        paired = True
        baseline_config = _artifact_for_reference(root, baseline_reference)
        candidate_config = _artifact_for_reference(root, candidate_reference)
        checks = _compatibility(
            baseline_config, candidate_config, list(experiment.get("changed_factors", []))
        )

        baseline_references = [
            f"atlas://run/{run['id']}@v{run['version']}" for run, _ in selected_baseline
        ]
        candidate_references = [
            f"atlas://run/{run['id']}@v{run['version']}" for run, _ in selected_candidate
        ]
        existing = _existing_comparison(
            experiment_root,
            baseline_references,
            candidate_references,
        )
        if existing is not None:
            _validate_existing_effect_plan(
                existing,
                effect_metrics,
                require_frozen_plan=requires_frozen_effect_plan,
            )
            outputs.append(existing)
            continue

        effects = []
        overall_results = []
        for metric_reference in effect_metrics:
            metric_id = metric_reference.rsplit("/", 1)[-1].split("@", 1)[0]
            baseline_observations = [
                _metric_observations(path, metric_id) for _, path in selected_baseline
            ]
            candidate_observations = [
                _metric_observations(path, metric_id) for _, path in selected_candidate
            ]
            unit = _consistent_unit(baseline_observations + candidate_observations, metric_id)
            overall_effect, overall_result = _effect(
                root,
                metric_reference,
                np.array([value for value, _, _ in baseline_observations]),
                np.array([value for value, _, _ in candidate_observations]),
                unit=unit,
                paired=paired,
                resamples=resamples,
                confidence=confidence,
                seed=analysis_seed,
            )
            effects.append(overall_effect)
            if metric_reference in primary_metrics:
                overall_results.append(overall_result)

            expected_scopes = _matching_scope_keys(
                [scoped for _, _, scoped in baseline_observations],
                [scoped for _, _, scoped in candidate_observations],
                metric=metric_id,
                contrast=contrast["id"],
            )
            for scoped_index, key in enumerate(sorted(expected_scopes), start=1):
                scope = baseline_observations[0][2][key][0]
                scoped_effect, _ = _effect(
                    root,
                    metric_reference,
                    np.array([scoped[key][1] for _, _, scoped in baseline_observations]),
                    np.array([scoped[key][1] for _, _, scoped in candidate_observations]),
                    unit=unit,
                    paired=paired,
                    resamples=resamples,
                    confidence=confidence,
                    seed=analysis_seed + scoped_index,
                    scope=scope,
                )
                effects.append(scoped_effect)
        overall = overall_results[0] if len(set(overall_results)) == 1 else "mixed"
        comparison_id = next_identifier(root, "comparison")
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        comparison = {
            "$schema": (
                "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
                "schemas/v1/studies/comparison.schema.json"
            ),
            "schema_version": 1,
            "kind": "Comparison",
            "id": comparison_id,
            "version": 1,
            "slug": f"{experiment['slug']}-{contrast['id']}-{comparison_id.lower()}",
            "title": f"{experiment['title']}: {contrast['id']}",
            "description": (
                f"Controlled {contrast['id']} effects for {candidate_reference} "
                f"against {baseline_reference}."
            ),
            "status": "accepted",
            "authors": experiment["authors"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "license": experiment["license"],
            "citations": [],
            "provenance": {
                "method": "atlas compare paired-bootstrap effect estimation",
                "source_paths": [
                    str(path.relative_to(root))
                    for _, path in selected_baseline + selected_candidate
                ],
                "generated": True,
            },
            "extensions": {},
            "experiment": f"atlas://experiment/{experiment['id']}@v{experiment['version']}",
            "contrast": contrast,
            "baseline_runs": baseline_references,
            "candidate_runs": candidate_references,
            "changed_axes": experiment["changed_factors"],
            "compatibility": {"passed": True, "checks": checks},
            "method": {
                "paired": paired,
                "confidence_level": confidence,
                "bootstrap_resamples": resamples,
                "bootstrap_seed": analysis_seed,
                "pairing_keys": ["replicate", "seed"],
                "effect_metrics": effect_metrics,
            },
            "effects": effects,
            "quality_eligible": True,
            "slo_eligible": all(
                _summary_slo_eligible(path) for _, path in selected_baseline + selected_candidate
            ),
            "result": overall,
        }
        output = _comparison_output_path(experiment_root, comparison_id)
        with output.open("w") as stream:
            yaml_writer().dump(comparison, stream)
        outputs.append(output)
    return outputs


def compare_all(root: Path) -> list[Path]:
    outputs = []
    for path in sorted((root / "studies").glob("S*-*/v*/experiments/E*/experiment.yaml")):
        if not any((path.parent / "runs").glob("R*/run.yaml")):
            continue
        outputs.extend(compare_experiment(root, path.parent.name))
    return outputs
