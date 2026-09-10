from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from atlas.comparisons import service
from atlas.schemas import SchemaCatalog
from atlas.utilities.serialization import load_data, yaml_writer

ROOT = Path(__file__).resolve().parents[2]


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        yaml_writer().dump(value, stream)


def _experiment(root: Path, study: str, experiment: str) -> Path:
    path = root / "studies" / study / "v1" / "experiments" / experiment
    path.mkdir(parents=True)
    (path / "experiment.yaml").write_text("kind: Experiment\n")
    return path


def test_relative_effect_is_unavailable_for_a_zero_baseline() -> None:
    assert service._relative_effect(absolute=5.0, baseline=0.0) is None
    assert service._relative_effect(absolute=5.0, baseline=-0.0) is None


def test_relative_effect_uses_the_baseline_as_denominator() -> None:
    assert service._relative_effect(absolute=5.0, baseline=20.0) == 0.25


def test_compare_all_skips_experiments_without_accepted_runs(tmp_path: Path, monkeypatch) -> None:
    _experiment(tmp_path, "S001-test", "E0001")
    called = []
    monkeypatch.setattr(service, "compare_experiment", lambda root, value: called.append(value))

    assert service.compare_all(tmp_path) == []
    assert called == []


def test_compare_all_processes_experiments_that_have_accepted_runs(
    tmp_path: Path, monkeypatch
) -> None:
    experiment = _experiment(tmp_path, "S001-test", "E0001")
    run = experiment / "runs" / "R0001"
    run.mkdir(parents=True)
    (run / "run.yaml").write_text("kind: RunRecord\n")
    output = experiment / "comparisons" / "CMP0001.yaml"
    monkeypatch.setattr(service, "compare_experiment", lambda root, value: [output])

    assert service.compare_all(tmp_path) == [output]


def test_existing_comparison_matches_exact_run_sets(tmp_path: Path) -> None:
    comparisons = tmp_path / "comparisons"
    comparisons.mkdir()
    existing = comparisons / "CMP0001.yaml"
    existing.write_text(
        "baseline_runs: [atlas://run/R0001@v1]\ncandidate_runs: [atlas://run/R0002@v1]\n"
    )

    assert (
        service._existing_comparison(
            tmp_path,
            ["atlas://run/R0001@v1"],
            ["atlas://run/R0002@v1"],
        )
        == existing
    )
    assert (
        service._existing_comparison(
            tmp_path,
            ["atlas://run/R0001@v1"],
            ["atlas://run/R0003@v1"],
        )
        is None
    )


def test_comparison_output_path_creates_generated_directory(tmp_path: Path) -> None:
    output = service._comparison_output_path(tmp_path, "CMP0001")

    assert output == tmp_path / "comparisons" / "CMP0001.yaml"
    assert output.parent.is_dir()


def test_default_contrasts_preserve_baseline_to_candidate_behavior() -> None:
    experiment = {
        "baseline": "atlas://configuration/CFG001@v1",
        "candidates": [
            "atlas://configuration/CFG002@v1",
            "atlas://configuration/CFG003@v1",
        ],
        "analysis": {},
    }

    assert service._planned_contrasts(experiment) == [
        {
            "id": "cfg001-vs-cfg002",
            "baseline": "atlas://configuration/CFG001@v1",
            "candidate": "atlas://configuration/CFG002@v1",
        },
        {
            "id": "cfg001-vs-cfg003",
            "baseline": "atlas://configuration/CFG001@v1",
            "candidate": "atlas://configuration/CFG003@v1",
        },
    ]


def test_registered_contrasts_allow_candidate_to_candidate_comparison() -> None:
    experiment = {
        "baseline": "atlas://configuration/CFG001@v1",
        "candidates": [
            "atlas://configuration/CFG002@v1",
            "atlas://configuration/CFG003@v1",
        ],
        "analysis": {
            "contrasts": [
                {
                    "id": "host-sync-vs-prefetch",
                    "baseline": "atlas://configuration/CFG002@v1",
                    "candidate": "atlas://configuration/CFG003@v1",
                }
            ]
        },
    }

    assert service._planned_contrasts(experiment) == experiment["analysis"]["contrasts"]


@pytest.mark.parametrize(
    "contrast, message",
    [
        (
            {
                "id": "self",
                "baseline": "atlas://configuration/CFG001@v1",
                "candidate": "atlas://configuration/CFG001@v1",
            },
            "different configurations",
        ),
        (
            {
                "id": "foreign",
                "baseline": "atlas://configuration/CFG001@v1",
                "candidate": "atlas://configuration/CFG999@v1",
            },
            "outside the experiment",
        ),
    ],
)
def test_invalid_registered_contrasts_are_rejected(contrast: dict[str, str], message: str) -> None:
    experiment = {
        "baseline": "atlas://configuration/CFG001@v1",
        "candidates": ["atlas://configuration/CFG002@v1"],
        "analysis": {"contrasts": [contrast]},
    }

    with pytest.raises(service.ComparisonError, match=message):
        service._planned_contrasts(experiment)


def test_duplicate_contrast_identifiers_and_reversed_pairs_are_rejected() -> None:
    references = [
        "atlas://configuration/CFG001@v1",
        "atlas://configuration/CFG002@v1",
        "atlas://configuration/CFG003@v1",
    ]
    base = {"baseline": references[0], "candidates": references[1:]}
    duplicate_id = {
        **base,
        "analysis": {
            "contrasts": [
                {"id": "same", "baseline": references[0], "candidate": references[1]},
                {"id": "same", "baseline": references[0], "candidate": references[2]},
            ]
        },
    }
    reversed_pair = {
        **base,
        "analysis": {
            "contrasts": [
                {"id": "forward", "baseline": references[0], "candidate": references[1]},
                {"id": "reverse", "baseline": references[1], "candidate": references[0]},
            ]
        },
    }

    for experiment in (duplicate_id, reversed_pair):
        with pytest.raises(service.ComparisonError, match="duplicated"):
            service._planned_contrasts(experiment)


def test_analysis_settings_are_read_from_the_experiment() -> None:
    assert service._analysis_settings(
        {"analysis": {"resamples": 1234, "confidence_level": 0.9, "seed": 17}}
    ) == (1234, 0.9, 17)


def test_metric_breakdowns_require_unique_canonical_scopes(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    summary = {
        "metrics": {
            "MET019": {
                "value": 100,
                "unit": "token/s",
                "breakdown": [
                    {"scope": {"concurrency": 8, "context_tokens": 32768}, "value": 90},
                    {"scope": {"context_tokens": 32768, "concurrency": 8}, "value": 91},
                ],
            }
        }
    }
    (metrics / "summary.json").write_text(json.dumps(summary))

    with pytest.raises(service.ComparisonError, match="duplicate MET019 scope"):
        service._metric_observations(tmp_path, "MET019")


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_metric_breakdowns_reject_non_finite_or_boolean_values(
    tmp_path: Path, value: object
) -> None:
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (metrics / "summary.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "MET019": {
                        "value": 100,
                        "unit": "token/s",
                        "breakdown": [{"scope": {"concurrency": 8}, "value": value}],
                    }
                }
            }
        )
    )

    with pytest.raises(service.ComparisonError, match="requires scope and value"):
        service._metric_observations(tmp_path, "MET019")


def test_scope_sets_must_match_exactly() -> None:
    left = {'{"concurrency":8}': ({"concurrency": 8}, 10.0)}
    right = {'{"concurrency":16}': ({"concurrency": 16}, 11.0)}

    with pytest.raises(service.ComparisonError, match="scope mismatch"):
        service._matching_scope_keys([left], [right], metric="MET019", contrast="test")


def test_scoped_effect_retains_scope_and_configured_confidence(monkeypatch) -> None:
    monkeypatch.setattr(service, "_metric_direction", lambda *_: "higher_is_better")
    effect, result = service._effect(
        Path("."),
        "atlas://metric/MET019@v1",
        np.array([10.0, 11.0, 12.0]),
        np.array([12.0, 13.0, 14.0]),
        unit="token/s",
        paired=True,
        resamples=100,
        confidence=0.9,
        seed=7,
        scope={"context_tokens": 32768, "concurrency": 8},
    )

    assert effect["scope"] == {"context_tokens": 32768, "concurrency": 8}
    assert effect["confidence_interval"]["level"] == 0.9
    assert result == "improvement"


def test_metric_units_must_match_across_runs(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    for path, unit in ((left, "token/s"), (right, "request/s")):
        metrics = path / "metrics"
        metrics.mkdir(parents=True)
        (metrics / "summary.json").write_text(
            json.dumps({"metrics": {"MET019": {"value": 1, "unit": unit}}})
        )

    with pytest.raises(service.ComparisonError, match="Metric unit mismatch"):
        service._consistent_unit(
            [
                service._metric_observations(left, "MET019"),
                service._metric_observations(right, "MET019"),
            ],
            "MET019",
        )


def test_compare_experiment_generates_paired_scoped_contrast(tmp_path: Path) -> None:
    study_root = tmp_path / "studies" / "S999-test" / "v1"
    experiment_root = study_root / "experiments" / "E9999"
    configuration_references = [
        "atlas://configuration/CFG001@v1",
        "atlas://configuration/CFG002@v1",
        "atlas://configuration/CFG003@v1",
    ]
    common_axes = {
        "workload": "atlas://workload-spec/WS001@v1",
        "quality": "atlas://quality-contract/QC001@v1",
        "slo": "atlas://slo/SLO001@v1",
        "model": "atlas://model/M001@v1",
        "hardware": "atlas://hardware/HW001@v1",
        "runtime": "atlas://runtime/RT001@v1",
    }
    for index, _reference in enumerate(configuration_references, start=1):
        _write_yaml(
            study_root / "configurations" / f"CFG00{index}.yaml",
            {"id": f"CFG00{index}", "version": 1, **common_axes},
        )

    _write_yaml(
        tmp_path / "reference" / "ontology" / "v1" / "metrics" / "throughput.yaml",
        {"entries": [{"id": "MET019", "direction": "higher_is_better"}]},
    )
    _write_yaml(
        experiment_root / "experiment.yaml",
        {
            "id": "E9999",
            "version": 1,
            "slug": "engram-placement",
            "title": "Engram placement",
            "authors": [{"name": "Test", "roles": ["software"], "conflicts": []}],
            "license": "Apache-2.0",
            "baseline": configuration_references[0],
            "candidates": configuration_references[1:],
            "changed_factors": ["engram placement"],
            "metrics": {"primary": ["atlas://metric/MET019@v1"]},
            "analysis": {
                "resamples": 100,
                "confidence_level": 0.9,
                "seed": 17,
                "contrasts": [
                    {
                        "id": "host-sync-vs-host-prefetch",
                        "baseline": configuration_references[1],
                        "candidate": configuration_references[2],
                    }
                ],
            },
        },
    )
    values = {
        configuration_references[0]: [100.0, 101.0, 99.0],
        configuration_references[1]: [89.0, 90.0, 91.0],
        configuration_references[2]: [110.0, 111.0, 112.0],
    }
    run_number = 1
    for configuration, replicate_values in values.items():
        for replicate, value in enumerate(replicate_values, start=1):
            run_id = f"R{run_number:04d}"
            run_root = experiment_root / "runs" / run_id
            _write_yaml(
                run_root / "run.yaml",
                {
                    "id": run_id,
                    "version": 1,
                    "configuration": configuration,
                    "replicate": replicate,
                    "seed": replicate * 101,
                    "outcome": "complete",
                    "quality": {"passed": True},
                    "validation": {"passed": True},
                },
            )
            summary = {
                "slo_passed": True,
                "metrics": {
                    "MET019": {
                        "value": value,
                        "unit": "token/s",
                        "breakdown": [
                            {
                                "scope": {
                                    "content_family": "code",
                                    "context_tokens": 32768,
                                    "concurrency": 8,
                                },
                                "value": value - 5,
                            },
                            {
                                "scope": {
                                    "content_family": "natural_language",
                                    "context_tokens": 8192,
                                    "concurrency": 1,
                                },
                                "value": value + 5,
                            },
                        ],
                    }
                },
            }
            metrics = run_root / "metrics"
            metrics.mkdir(parents=True)
            (metrics / "summary.json").write_text(json.dumps(summary))
            run_number += 1

    outputs = service.compare_experiment(tmp_path, "E9999")

    assert len(outputs) == 1
    comparison = load_data(outputs[0])
    assert comparison["contrast"] == {
        "id": "host-sync-vs-host-prefetch",
        "baseline": configuration_references[1],
        "candidate": configuration_references[2],
    }
    assert comparison["baseline_runs"] == [
        "atlas://run/R0004@v1",
        "atlas://run/R0005@v1",
        "atlas://run/R0006@v1",
    ]
    assert comparison["candidate_runs"] == [
        "atlas://run/R0007@v1",
        "atlas://run/R0008@v1",
        "atlas://run/R0009@v1",
    ]
    assert comparison["method"] == {
        "paired": True,
        "confidence_level": 0.9,
        "bootstrap_resamples": 100,
        "bootstrap_seed": 17,
        "pairing_keys": ["replicate", "seed"],
    }
    assert len(comparison["effects"]) == 3
    assert comparison["effects"][0]["absolute"] == 21.0
    scoped_effects = {
        effect["scope"]["content_family"]: effect
        for effect in comparison["effects"]
        if "scope" in effect
    }
    assert scoped_effects["code"]["scope"] == {
        "concurrency": 8,
        "content_family": "code",
        "context_tokens": 32768,
    }
    catalog = SchemaCatalog(ROOT / "reference" / "schemas" / "v1")
    assert catalog.validate(comparison, comparison["$schema"]) == []
