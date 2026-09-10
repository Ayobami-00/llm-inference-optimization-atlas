from __future__ import annotations

from pathlib import Path

from atlas.utilities.serialization import load_data, yaml_writer
from atlas.validation import Validator


def test_targeted_strict_validation_uses_repository_wide_identity_index() -> None:
    root = Path(__file__).resolve().parents[2]
    target = (
        root / "studies" / "S001-cpu-interactive-chat" / "v1" / "configurations" / "CFG001.yaml"
    )

    report = Validator(root).validate_path(target, strict=True)

    assert report.ok, report.issues
    assert report.checked_files == 1


def test_strict_validation_rejects_effect_plan_missing_a_primary_metric(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root
        / "studies"
        / "S004-deepseek-v41-engram-placement"
        / "v1"
        / "experiments"
        / "E0013"
        / "experiment.yaml"
    )
    experiment = load_data(source)
    assert isinstance(experiment, dict)
    experiment["analysis"]["effect_metrics"] = ["atlas://metric/MET010@v1"]
    target = tmp_path / "experiment.yaml"
    with target.open("w") as stream:
        yaml_writer().dump(experiment, stream)

    report = Validator(root).validate_path(target, strict=True)

    matching = [issue for issue in report.errors if issue.code == "experiment-analysis"]
    assert len(matching) == 1
    assert matching[0].location == "/analysis/effect_metrics"
    assert "include every primary metric" in matching[0].message
