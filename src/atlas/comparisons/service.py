from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from atlas.identities import next_identifier
from atlas.utilities.serialization import load_data, yaml_writer


class ComparisonError(RuntimeError):
    """A controlled comparison could not be produced."""


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


def _metric_value(run_root: Path, metric: str) -> tuple[float, str]:
    summary = load_data(run_root / "metrics" / "summary.json")
    if not isinstance(summary, dict):
        raise ComparisonError(f"Summary must be an object: {run_root}")
    metrics = summary.get("metrics", {})
    value = metrics.get(metric) if isinstance(metrics, dict) else None
    if not isinstance(value, dict) or not isinstance(value.get("value"), (int, float)):
        raise ComparisonError(f"Summary {run_root} has no numeric {metric} value")
    return float(value["value"]), str(value.get("unit", "1"))


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
    baseline_reference = experiment["baseline"]
    baseline_runs = [
        (run, path) for run, path in runs if run.get("configuration") == baseline_reference
    ]
    if len(baseline_runs) < 3:
        raise ComparisonError("Accepted comparisons require at least three eligible baseline runs")
    baseline_config = _artifact_for_reference(root, baseline_reference)

    outputs = []
    for candidate_reference in experiment.get("candidates", []):
        candidate_runs = [
            (run, path) for run, path in runs if run.get("configuration") == candidate_reference
        ]
        if len(candidate_runs) < 3:
            raise ComparisonError(
                f"Accepted comparisons require three eligible runs for {candidate_reference}"
            )
        candidate_config = _artifact_for_reference(root, candidate_reference)
        checks = _compatibility(
            baseline_config, candidate_config, list(experiment.get("changed_factors", []))
        )
        baseline_by_seed = {run["seed"]: (run, path) for run, path in baseline_runs}
        candidate_by_seed = {run["seed"]: (run, path) for run, path in candidate_runs}
        common_seeds = sorted(set(baseline_by_seed) & set(candidate_by_seed))
        paired = len(common_seeds) >= 3
        if paired:
            selected_baseline = [baseline_by_seed[seed] for seed in common_seeds]
            selected_candidate = [candidate_by_seed[seed] for seed in common_seeds]
        else:
            selected_baseline = baseline_runs
            selected_candidate = candidate_runs

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
            outputs.append(existing)
            continue

        effects = []
        results = []
        for metric_reference in experiment["metrics"]["primary"]:
            metric_id = metric_reference.rsplit("/", 1)[-1].split("@", 1)[0]
            baseline_values_and_units = [
                _metric_value(path, metric_id) for _, path in selected_baseline
            ]
            candidate_values_and_units = [
                _metric_value(path, metric_id) for _, path in selected_candidate
            ]
            units = {unit for _, unit in baseline_values_and_units + candidate_values_and_units}
            if len(units) != 1:
                raise ComparisonError(f"Metric unit mismatch for {metric_id}: {sorted(units)}")
            baseline_values = np.array([value for value, _ in baseline_values_and_units])
            candidate_values = np.array([value for value, _ in candidate_values_and_units])
            baseline_mean = float(np.mean(baseline_values))
            candidate_mean = float(np.mean(candidate_values))
            absolute = candidate_mean - baseline_mean
            relative = absolute / baseline_mean if baseline_mean else 0.0
            lower, upper = _bootstrap_interval(
                baseline_values,
                candidate_values,
                paired=paired,
                resamples=10000,
                confidence=0.95,
                seed=20260825,
            )
            direction = _metric_direction(root, metric_reference)
            results.append(_comparison_result(direction, lower, upper))
            effects.append(
                {
                    "metric": metric_reference,
                    "baseline": baseline_mean,
                    "candidate": candidate_mean,
                    "absolute": absolute,
                    "relative": relative,
                    "confidence_interval": {
                        "lower": lower,
                        "upper": upper,
                        "level": 0.95,
                    },
                    "unit": units.pop(),
                }
            )
        overall = results[0] if len(set(results)) == 1 else "mixed"
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
            "slug": f"{experiment['slug']}-{comparison_id.lower()}",
            "title": f"{experiment['title']} comparison",
            "description": (
                f"Controlled effects for {candidate_reference} against {baseline_reference}."
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
            "baseline_runs": baseline_references,
            "candidate_runs": candidate_references,
            "changed_axes": experiment["changed_factors"],
            "compatibility": {"passed": True, "checks": checks},
            "method": {
                "paired": paired,
                "confidence_level": 0.95,
                "bootstrap_resamples": 10000,
            },
            "effects": effects,
            "quality_eligible": True,
            "slo_eligible": all(
                bool(load_data(path / "metrics" / "summary.json").get("slo_passed", False))
                for _, path in selected_baseline + selected_candidate
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
