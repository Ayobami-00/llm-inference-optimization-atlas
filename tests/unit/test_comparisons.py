from __future__ import annotations

from pathlib import Path

from atlas.comparisons import service


def _experiment(root: Path, study: str, experiment: str) -> Path:
    path = root / "studies" / study / "v1" / "experiments" / experiment
    path.mkdir(parents=True)
    (path / "experiment.yaml").write_text("kind: Experiment\n")
    return path


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
