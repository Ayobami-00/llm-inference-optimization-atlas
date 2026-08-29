from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from atlas.utilities.serialization import yaml_loader

ROOT = Path(__file__).parents[2]
GITHUB = ROOT / ".github"


def _yaml(path: Path) -> dict[str, Any] | list[Any]:
    value = yaml_loader().load(path.read_text())
    assert isinstance(value, (dict, list))
    return value


def test_issue_forms_are_schema_backed_and_labels_are_declared() -> None:
    label_data = _yaml(GITHUB / "labels.yml")
    assert isinstance(label_data, list)
    known_labels = {item["name"] for item in label_data}
    forms = sorted(
        path for path in (GITHUB / "ISSUE_TEMPLATE").glob("*.yml") if path.name != "config.yml"
    )
    assert len(forms) == 5
    required_sections = {
        "Proposal title",
        "Summary",
        "Motivation",
        "Scope",
        "Planned artifacts",
        "Resources",
        "Risks",
        "Conflict disclosure",
        "Contributor agreement",
    }
    for path in forms:
        form = _yaml(path)
        assert isinstance(form, dict)
        assert set(form["labels"]) <= known_labels
        bodies = form["body"]
        marker_text = "\n".join(
            str(item.get("attributes", {}).get("value", ""))
            for item in bodies
            if isinstance(item, dict)
        )
        assert re.search(r"<!-- atlas-proposal-form:v1:[a-z-]+ -->", marker_text)
        labels = {
            item.get("attributes", {}).get("label")
            for item in bodies
            if isinstance(item, dict) and "id" in item
        }
        assert labels == required_sections


def test_workflows_have_explicit_permissions_and_pinned_actions() -> None:
    workflows = sorted((GITHUB / "workflows").glob("*.yml"))
    assert {path.name for path in workflows} == {
        "approval-gate.yml",
        "ci.yml",
        "dependency-review.yml",
        "pages.yml",
        "proposal-validation.yml",
        "real-model-study.yml",
    }
    for path in workflows:
        workflow = _yaml(path)
        assert isinstance(workflow, dict)
        assert "permissions" in workflow or all(
            "permissions" in job for job in workflow["jobs"].values()
        )
        for action in re.findall(r"uses:\s*([^\s]+)", path.read_text()):
            assert re.fullmatch(
                r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@(?:v[1-9][0-9]*|[0-9a-f]{40})",
                action,
            )


def test_approval_gate_never_checks_out_or_executes_pull_request_code() -> None:
    path = GITHUB / "workflows" / "approval-gate.yml"
    workflow = _yaml(path)
    assert isinstance(workflow, dict)
    assert "pull_request_target" in workflow["on"]
    condition = workflow["jobs"]["approval"]["if"]
    assert "github.event.pull_request.draft == false" in condition
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in condition
    text = path.read_text()
    assert "github.event.repository.default_branch" in text
    assert "github.event.pull_request.head.sha" not in text
    assert "atlas proposal check-approval" in text


def test_ordinary_ci_cannot_prepare_or_run_models() -> None:
    excluded = {"real-model-study.yml"}
    for path in (GITHUB / "workflows").glob("*.yml"):
        if path.name in excluded:
            continue
        text = path.read_text()
        assert "atlas execution prepare" not in text
        assert "atlas execution run" not in text


def test_pages_builds_generated_site_without_enabling_pages() -> None:
    text = (GITHUB / "workflows" / "pages.yml").read_text()
    assert "atlas site build" in text
    assert "actions/upload-pages-artifact@v5" in text
    assert "actions/deploy-pages@v5" in text
    assert "actions/configure-pages" not in text
