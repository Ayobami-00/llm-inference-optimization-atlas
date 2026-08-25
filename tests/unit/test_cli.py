from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from atlas.cli import app

ROOT = Path(__file__).parents[2]
runner = CliRunner()


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
