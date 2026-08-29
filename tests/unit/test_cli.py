from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import atlas.cli as cli
from atlas.cli import app
from atlas.proposals import validate_proposal

ROOT = Path(__file__).parents[2]
runner = CliRunner()


def test_doctor_human_output_renders_each_tool_on_its_own_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tool_version(name: str, *arguments: str) -> dict[str, Any]:
        del arguments
        if name == "docker":
            return {"available": False}
        return {"available": True, "version": f"{name} test-version"}

    monkeypatch.setattr(cli, "_tool_version", tool_version)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Tools" in result.output
    assert "git" in result.output
    assert "✓ available" in result.output
    assert "docker" in result.output
    assert "✗ unavailable" in result.output
    assert "—" in result.output
    assert '{"docker"' not in result.output


def test_doctor_json_output_keeps_structured_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_tool_version",
        lambda name, *arguments: {"available": True, "version": f"{name} test-version"},
    )

    result = runner.invoke(app, ["--json", "doctor"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tools"]["git"] == {
        "available": True,
        "version": "git test-version",
    }


def test_schema_check_supports_json_output(monkeypatch: object) -> None:
    result = runner.invoke(app, ["--json", "schema", "check"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schemas"] >= 36


def test_direct_invalid_fixture_uses_validation_exit_code() -> None:
    result = runner.invoke(
        app,
        ["--json", "validate", str(ROOT / "tests" / "fixtures" / "invalid" / "source.json")],
    )
    assert result.exit_code == 3
    assert json.loads(result.output)["errors"] == 1


def test_repository_wide_strict_validation_excludes_test_fixtures() -> None:
    result = runner.invoke(app, ["--json", "validate", "--all", "--strict"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["errors"] == 0


def test_identity_preview_returns_consecutive_ids() -> None:
    result = runner.invoke(app, ["--json", "ids", "next", "experiment", "--count", "2"])

    assert result.exit_code == 0, result.output
    identifiers = json.loads(result.output)["identifiers"]
    assert len(identifiers) == 2
    assert int(identifiers[1][1:]) == int(identifiers[0][1:]) + 1


def test_contribution_status_explains_the_complete_study_journey() -> None:
    result = runner.invoke(app, ["contribution", "status", "S003"])

    assert result.exit_code == 0, result.output
    assert "Contribution status: ready for review" in result.output
    assert "Approved proposal" in result.output
    assert "Accepted evidence" in result.output
    assert "Publication checks" in result.output


def test_proposal_help_exposes_guided_authoring() -> None:
    result = runner.invoke(app, ["proposal", "new", "--help"])

    assert result.exit_code == 0, result.output
    assert "--guided" in result.output


def test_guided_study_proposal_requires_no_yaml_authoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "find_repository_root", lambda: ROOT)
    output = tmp_path / "proposal.yaml"
    answers = [
        "CPU prompt reuse",
        "Measure repeated-prefix TTFT on CPU.",
        "The deployment boundary is unknown.",
        "Contributor",
        "contributor",
        "",
        "W004",
        "",
        "",
        "",
        "",
        "Does prompt reuse reduce TTFT?",
        "",
        "",
        "Local CPU for two hours",
        "",
        "",
        "",
    ]

    result = runner.invoke(
        app,
        ["proposal", "new", "study", "--guided", "--output", str(output)],
        input="\n".join(answers) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert validate_proposal(ROOT, output).ok
