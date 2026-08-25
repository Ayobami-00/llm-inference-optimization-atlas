from __future__ import annotations

from pathlib import Path

from atlas.proposals import render_proposal, validate_proposal
from atlas.utilities.serialization import load_data

ROOT = Path(__file__).parents[2]


def test_rendered_proposal_retains_machine_identity() -> None:
    path = ROOT / "reference" / "templates" / "v1" / "proposals" / "study.yaml"
    data = load_data(path)
    assert isinstance(data, dict)
    assert validate_proposal(ROOT, path).ok
    rendered = render_proposal(data)
    assert "<!-- atlas-proposal" in rendered
    assert "id: P0000" in rendered
    assert "type: study" in rendered
