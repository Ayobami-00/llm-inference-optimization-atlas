from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atlas.studies.service import (
    StudyError,
    new_experiment,
    new_study,
    resolve_configurations,
)
from atlas.utilities.serialization import load_data, yaml_writer

ROOT = Path(__file__).parents[2]


def _write_proposal(tmp_path: Path, *, study_id: str = "S001", slug: str = "cpu-chat") -> Path:
    proposal = {
        "kind": "Proposal",
        "id": "P0002",
        "version": 1,
        "slug": "cpu-chat-proposal",
        "title": "CPU chat",
        "summary": "Measure CPU chat inference.",
        "authors": [
            {
                "name": "Contributor",
                "github": "contributor",
                "roles": ["proposer"],
                "conflicts": [],
            }
        ],
        "proposal_type": "study",
        "scope": {
            "study_id": study_id,
            "slug": slug,
            "archetype": "atlas://workload/W001@v1",
            "models": ["atlas://model/M001@v1"],
            "hardware": ["atlas://hardware/HW001@v1"],
            "runtimes": ["atlas://runtime/RT001@v1"],
            "research_questions": ["Where is the CPU batching crossover?"],
            "included": ["Apple M3 CPU"],
            "excluded": ["GPU execution"],
        },
        "approval": {
            "state": "approved",
            "issue_url": "https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/2",
        },
    }
    proposal_path = tmp_path / ".atlas" / "work" / "proposal.yaml"
    proposal_path.parent.mkdir(parents=True)
    with proposal_path.open("w") as stream:
        yaml_writer().dump(proposal, stream)
    return proposal_path


def _copy_study_template(tmp_path: Path) -> None:
    destination = tmp_path / "reference" / "templates" / "v1" / "study"
    destination.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "reference" / "templates" / "v1" / "study", destination)


def test_study_scaffold_honors_approved_identity_and_copies_proposal(tmp_path: Path) -> None:
    _copy_study_template(tmp_path)
    proposal_path = _write_proposal(tmp_path)

    study_root = new_study(tmp_path, str(proposal_path))

    assert study_root == tmp_path / "studies" / "S001-cpu-chat" / "v1"
    assert load_data(study_root / "study.yaml")["id"] == "S001"
    assert load_data(study_root / "study.yaml")["contracts"] == {
        "workload": "atlas://workload-spec/WS001@v1",
        "quality": "atlas://quality-contract/QC001@v1",
        "slo": "atlas://slo/SLO001@v1",
    }
    assert load_data(study_root / "study.yaml")["maintainers"] == ["contributor"]
    assert load_data(study_root / "proposal.yaml")["id"] == "P0002"
    assert load_data(study_root / "contribution.yaml")["artifacts"] == [
        "README.md",
        "proposal.yaml",
        "study.yaml",
        "workload.yaml",
        "quality.yaml",
        "slo.yaml",
        "inputs",
        "execution",
        "configurations",
        "hypotheses",
        "experiments",
        "findings",
        "decisions",
    ]
    assert load_data(study_root / "workload.yaml")["id"] == "WS001"
    assert load_data(study_root / "quality.yaml")["id"] == "QC001"
    assert load_data(study_root / "slo.yaml")["id"] == "SLO001"
    assert (study_root / "inputs" / "README.md").is_file()
    assert (study_root / "execution" / "README.md").is_file()


def test_study_scaffold_rejects_invalid_requested_identity(tmp_path: Path) -> None:
    _copy_study_template(tmp_path)
    proposal_path = _write_proposal(tmp_path, study_id="study-one")

    with pytest.raises(StudyError, match="S###"):
        new_study(tmp_path, str(proposal_path))


def test_experiment_scaffold_uses_approved_proposal_and_allocates_related_ids(
    tmp_path: Path,
) -> None:
    _copy_study_template(tmp_path)
    experiment_templates = tmp_path / "reference" / "templates" / "v1" / "experiment"
    shutil.copytree(
        ROOT / "reference" / "templates" / "v1" / "experiment",
        experiment_templates,
    )
    shutil.copytree(ROOT / "registry", tmp_path / "registry")
    study_root = new_study(tmp_path, str(_write_proposal(tmp_path)))
    experiment_proposal = {
        "kind": "Proposal",
        "id": "P0017",
        "version": 1,
        "slug": "cpu-thread-budget",
        "title": "CPU thread budget",
        "summary": "Compare one and four CPU inference threads.",
        "motivation": "The practical crossover is unknown.",
        "authors": [
            {
                "name": "Contributor",
                "github": "contributor",
                "roles": ["proposer"],
                "conflicts": [],
            }
        ],
        "proposal_type": "experiment",
        "scope": {
            "study": "atlas://study/S001@v1",
            "hypothesis": "Four threads reduce server TTFT.",
            "changed_factors": ["inference thread budget"],
            "frozen_factors": ["workload", "model", "hardware", "runtime"],
            "quality_gate": "Q1",
            "replicates": 3,
            "primary_metric": "atlas://metric/MET001@v1",
        },
        "approval": {
            "state": "approved",
            "issue_url": (
                "https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/17"
            ),
        },
    }
    proposal_path = tmp_path / ".atlas" / "work" / "P0017.yaml"
    with proposal_path.open("w") as stream:
        yaml_writer().dump(experiment_proposal, stream)

    experiment_root = new_experiment(tmp_path, "S001", str(proposal_path))

    assert experiment_root == study_root / "experiments" / "E0001"
    experiment = load_data(experiment_root / "experiment.yaml")
    assert experiment["hypothesis"] == "atlas://hypothesis/HYP001@v1"
    assert experiment["baseline"] == "atlas://configuration/CFG001@v1"
    assert experiment["candidates"] == ["atlas://configuration/CFG002@v1"]
    assert (study_root / "hypotheses" / "HYP001.yaml").is_file()
    assert (study_root / "configurations" / "RTCFG001.yaml").is_file()
    assert (study_root / "configurations" / "RTCFG002.yaml").is_file()
    assert (study_root / "configurations" / "CFG001.yaml").is_file()
    assert (study_root / "configurations" / "CFG002.yaml").is_file()
    contribution = load_data(experiment_root / "contribution.yaml")
    assert contribution["proposal"] == "atlas://proposal/P0017@v1"
    assert all(path.startswith("studies/") for path in contribution["artifacts"])

    configuration_path = study_root / "configurations" / "CFG001.yaml"
    runtime_path = study_root / "configurations" / "RTCFG001.yaml"
    original_hash = load_data(configuration_path)["resolved_hashes"]["runtime_configuration"]
    runtime = load_data(runtime_path)
    runtime["threads"] = {"generation": 8}
    with runtime_path.open("w") as stream:
        yaml_writer().dump(runtime, stream)

    resolved = resolve_configurations(tmp_path, "S001")

    assert configuration_path in resolved
    refreshed_hash = load_data(configuration_path)["resolved_hashes"]["runtime_configuration"]
    assert refreshed_hash != original_hash
