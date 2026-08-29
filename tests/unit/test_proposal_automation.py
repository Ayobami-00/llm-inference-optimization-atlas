from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from atlas.proposals.approval import check_pull_request_approval
from atlas.proposals.issue import (
    materialize_issue_proposal,
    proposal_from_issue,
    validate_issue_event,
)
from atlas.utilities.serialization import load_data, yaml_writer

ROOT = Path(__file__).parents[2]


def _issue_body(proposal_type: str = "study") -> str:
    return f"""<!-- atlas-proposal-form:v1:{proposal_type} -->
### Proposal title

Measure CPU batching

### Summary

Measure latency and goodput under controlled CPU batching.

### Motivation

The practical crossover point is unknown.

### Scope

```yaml
archetype: atlas://workload/W001@v1
research_questions:
  - When does batching improve SLO goodput?
```

### Planned artifacts

```yaml
- study
- experiments
- findings
```

### Resources

```yaml
compute: Local CPU
downloads: 300 MB
```

### Risks

```yaml
- Narrow hardware scope
```

### Conflict disclosure

None declared
"""


def _issue(*, approved: bool = True) -> dict[str, Any]:
    labels = [{"name": "proposal:type:study"}]
    if approved:
        labels.append({"name": "proposal:approved"})
    return {
        "number": 17,
        "body": _issue_body(),
        "labels": labels,
        "user": {"login": "contributor"},
        "created_at": "2026-08-25T12:00:00Z",
        "updated_at": "2026-08-25T12:00:00Z",
        "html_url": ("https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/17"),
    }


def test_issue_form_is_materialized_and_schema_validated(tmp_path: Path) -> None:
    event = {"issue": _issue(approved=False)}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    result = validate_issue_event(ROOT, path)
    assert result.ok
    assert result.proposal is not None
    assert result.proposal["id"] == "P0017"
    assert result.proposal["scope"]["archetype"] == "atlas://workload/W001@v1"


def test_issue_form_rejects_missing_machine_marker(tmp_path: Path) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"issue": {"number": 2, "body": "### Summary\nNo marker"}}))
    result = validate_issue_event(ROOT, path)
    assert not result.ok
    assert "marker" in result.issues[0]["message"]


def _manifest_bytes() -> str:
    manifest = {
        "$schema": (
            "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
            "schemas/v1/contributions/contribution-manifest.schema.json"
        ),
        "proposal": "atlas://proposal/P0017@v1",
        "issue_url": ("https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/17"),
        "approval_label": "proposal:approved",
        "contribution_type": "study",
        "artifacts": ["study.yaml"],
        "closes_issue": True,
    }
    from io import StringIO

    stream = StringIO()
    yaml_writer().dump(manifest, stream)
    return base64.b64encode(stream.getvalue().encode()).decode()


def _proposal_bytes(*, changed_scope: bool = False) -> str:
    result = proposal_from_issue(ROOT, _issue())
    assert result.ok and result.proposal is not None
    proposal = result.proposal
    proposal["approval"] = {
        "state": "approved",
        "issue_url": "https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/17",
    }
    if changed_scope:
        proposal["scope"]["research_questions"] = ["A question that was not approved?"]
    from io import StringIO

    stream = StringIO()
    yaml_writer().dump(proposal, stream)
    return base64.b64encode(stream.getvalue().encode()).decode()


def test_approved_issue_materializes_to_canonical_proposal(tmp_path: Path) -> None:
    issue_url = "https://github.com/Ayobami-00/llm-inference-optimization-atlas/issues/17"

    def fetch(url: str) -> Any:
        assert url.endswith("/issues/17")
        return _issue()

    path, proposal = materialize_issue_proposal(
        ROOT,
        issue_url,
        output=tmp_path / "P0017.yaml",
        fetcher=fetch,
    )

    assert path == tmp_path / "P0017.yaml"
    assert proposal["id"] == "P0017"
    assert proposal["approval"] == {"state": "approved", "issue_url": issue_url}
    assert load_data(path) == proposal


def test_pull_request_gate_checks_approval_type_branch_and_artifacts(tmp_path: Path) -> None:
    repository = "Ayobami-00/llm-inference-optimization-atlas"
    event = {
        "repository": {"full_name": repository},
        "pull_request": {
            "url": f"https://api.github.com/repos/{repository}/pulls/20",
            "body": "Closes #17",
            "head": {"sha": "a" * 40, "ref": "feat/17-cpu-batching"},
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))

    def fetch(url: str) -> Any:
        if "/files?" in url:
            return [
                {"filename": "studies/S001-chat/v1/contribution.yaml"},
                {"filename": "studies/S001-chat/v1/study.yaml"},
            ]
        if "/contents/" in url:
            content = _proposal_bytes() if "proposal.yaml" in url else _manifest_bytes()
            return {"encoding": "base64", "content": content}
        if url.endswith("/issues/17"):
            return _issue()
        raise AssertionError(url)

    result = check_pull_request_approval(ROOT, event_path, "test", fetcher=fetch)
    assert result.ok
    assert result.checked_manifests == 1


def test_pull_request_gate_rejects_unapproved_issue(tmp_path: Path) -> None:
    repository = "Ayobami-00/llm-inference-optimization-atlas"
    event = {
        "repository": {"full_name": repository},
        "pull_request": {
            "url": f"https://api.github.com/repos/{repository}/pulls/20",
            "body": "Closes #17",
            "head": {"sha": "a" * 40, "ref": "feat/17-cpu-batching"},
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))

    def fetch(url: str) -> Any:
        if "/files?" in url:
            return [
                {"filename": "studies/S001-chat/v1/contribution.yaml"},
                {"filename": "studies/S001-chat/v1/study.yaml"},
            ]
        if "/contents/" in url:
            content = _proposal_bytes() if "proposal.yaml" in url else _manifest_bytes()
            return {"encoding": "base64", "content": content}
        return _issue(approved=False)

    result = check_pull_request_approval(ROOT, event_path, "test", fetcher=fetch)
    assert not result.ok
    assert any("not approved" in issue["message"] for issue in result.issues)


def test_pull_request_gate_rejects_semantic_scope_drift(tmp_path: Path) -> None:
    repository = "Ayobami-00/llm-inference-optimization-atlas"
    event = {
        "repository": {"full_name": repository},
        "pull_request": {
            "url": f"https://api.github.com/repos/{repository}/pulls/20",
            "body": "Closes #17",
            "head": {"sha": "a" * 40, "ref": "feat/17-cpu-batching"},
        },
    }
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))

    def fetch(url: str) -> Any:
        if "/files?" in url:
            return [
                {"filename": "studies/S001-chat/v1/contribution.yaml"},
                {"filename": "studies/S001-chat/v1/proposal.yaml"},
                {"filename": "studies/S001-chat/v1/study.yaml"},
            ]
        if "/contents/" in url:
            content = (
                _proposal_bytes(changed_scope=True) if "proposal.yaml" in url else _manifest_bytes()
            )
            return {"encoding": "base64", "content": content}
        if url.endswith("/issues/17"):
            return _issue()
        raise AssertionError(url)

    result = check_pull_request_approval(ROOT, event_path, "test", fetcher=fetch)

    assert not result.ok
    assert any("does not match" in issue["message"] for issue in result.issues)
