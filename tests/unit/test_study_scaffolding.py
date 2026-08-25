from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atlas.studies.service import StudyError, new_study
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
        "proposal.yaml",
        "study.yaml",
    ]


def test_study_scaffold_rejects_invalid_requested_identity(tmp_path: Path) -> None:
    _copy_study_template(tmp_path)
    proposal_path = _write_proposal(tmp_path, study_id="study-one")

    with pytest.raises(StudyError, match="S###"):
        new_study(tmp_path, str(proposal_path))
