from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.proposals.service import PROPOSAL_LABELS, _slug
from atlas.schemas import SchemaCatalog
from atlas.utilities.serialization import yaml_loader

PROPOSAL_SCHEMA = (
    "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
    "schemas/v1/contributions/proposal.schema.json"
)
FORM_MARKER = re.compile(r"<!--\s*atlas-proposal-form:v1:(?P<type>[a-z-]+)\s*-->", re.IGNORECASE)
SECTION = re.compile(
    r"^### (?P<title>[^\n]+)\n+(?P<body>.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL
)
TYPE_VALUES = {
    "study": "study",
    "experiment": "experiment",
    "replication": "replication",
    "finding-challenge": "finding_challenge",
    "methodology": "methodology",
}


@dataclass(frozen=True)
class ProposalIssue:
    ok: bool
    proposal: dict[str, Any] | None = None
    issues: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        proposal = self.proposal or {}
        return {
            "ok": self.ok,
            "proposal_id": proposal.get("id"),
            "proposal_type": proposal.get("proposal_type"),
            "issues": self.issues,
        }


def _problem(location: str, message: str, code: str = "proposal-issue") -> dict[str, str]:
    return {
        "severity": "error",
        "code": code,
        "path": ".github/ISSUE_TEMPLATE",
        "location": location,
        "message": message,
    }


def _sections(body: str) -> dict[str, str]:
    return {
        match.group("title").strip().lower(): match.group("body").strip()
        for match in SECTION.finditer(body)
    }


def _plain(value: str) -> str:
    if value == "_No response_":
        return ""
    fenced = re.fullmatch(r"```(?:yaml)?\s*\n(?P<value>.*?)\n```", value, re.DOTALL)
    return fenced.group("value").strip() if fenced else value.strip()


def _structured(
    sections: dict[str, str], title: str, expected: type[dict[Any, Any]] | type[list[Any]]
) -> tuple[Any, list[dict[str, str]]]:
    value = _plain(sections.get(title, ""))
    if not value:
        return None, [_problem(f"/{title}", f"{title.title()} is required")]
    try:
        parsed = yaml_loader().load(value)
    except Exception as error:
        return None, [_problem(f"/{title}", f"Invalid YAML: {error}")]
    if not isinstance(parsed, expected):
        expected_name = "mapping" if expected is dict else "list"
        return None, [_problem(f"/{title}", f"Expected a YAML {expected_name}")]
    return parsed, []


def validate_issue_event(root: Path, event_path: Path) -> ProposalIssue:
    try:
        event = json.loads(event_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return ProposalIssue(False, issues=[_problem("/", f"Cannot read event: {error}")])
    issue = event.get("issue")
    if not isinstance(issue, dict):
        return ProposalIssue(False, issues=[_problem("/issue", "Event has no issue object")])
    body = str(issue.get("body") or "")
    marker = FORM_MARKER.search(body)
    if not marker:
        return ProposalIssue(False, issues=[_problem("/body", "Atlas proposal marker is missing")])
    form_type = marker.group("type").lower()
    proposal_type = TYPE_VALUES.get(form_type)
    if proposal_type is None:
        return ProposalIssue(
            False, issues=[_problem("/body", f"Unknown proposal type: {form_type}")]
        )

    problems: list[dict[str, str]] = []
    number = issue.get("number")
    if not isinstance(number, int) or not 1 <= number <= 9999:
        problems.append(_problem("/issue/number", "Issue number must fit the P#### namespace"))
        number = 0
    labels = {
        str(label.get("name")) for label in issue.get("labels", []) if isinstance(label, dict)
    }
    expected_label = PROPOSAL_LABELS[proposal_type]
    if expected_label not in labels:
        problems.append(_problem("/issue/labels", f"Required label is missing: {expected_label}"))

    sections = _sections(body)
    title = _plain(sections.get("proposal title", ""))
    summary = _plain(sections.get("summary", ""))
    motivation = _plain(sections.get("motivation", ""))
    required_text = (
        ("Proposal title", title),
        ("Summary", summary),
        ("Motivation", motivation),
    )
    for name, value in required_text:
        if not value:
            problems.append(_problem(f"/{name.lower().replace(' ', '-')}", f"{name} is required"))
    scope, scope_problems = _structured(sections, "scope", dict)
    artifacts, artifact_problems = _structured(sections, "planned artifacts", list)
    resources, resource_problems = _structured(sections, "resources", dict)
    risks, risk_problems = _structured(sections, "risks", list)
    problems.extend(scope_problems + artifact_problems + resource_problems + risk_problems)

    user = issue.get("user", {})
    login = (
        str(user.get("login") or "unknown-contributor")
        if isinstance(user, dict)
        else "unknown-contributor"
    )
    conflict = _plain(sections.get("conflict disclosure", ""))
    created = str(issue.get("created_at") or "1970-01-01T00:00:00Z")
    updated = str(issue.get("updated_at") or created)
    issue_url = str(issue.get("html_url") or "")
    proposal = {
        "$schema": PROPOSAL_SCHEMA,
        "schema_version": 1,
        "kind": "Proposal",
        "id": f"P{number:04d}",
        "version": 1,
        "slug": _slug(title or f"proposal-{number}"),
        "title": title or "Invalid proposal",
        "description": summary or "Invalid proposal",
        "status": "proposed",
        "authors": [
            {
                "name": login,
                "github": login,
                "roles": ["proposer"],
                "conflicts": (
                    [] if conflict.lower() in {"", "none", "none declared"} else [conflict]
                ),
            }
        ],
        "created_at": created,
        "updated_at": updated,
        "license": "Apache-2.0",
        "citations": [],
        "provenance": {
            "method": "github-issue-form",
            "source_paths": [issue_url] if issue_url else [],
            "generated": True,
        },
        "extensions": {"github.issue-url": issue_url} if issue_url else {},
        "proposal_type": proposal_type,
        "summary": summary,
        "motivation": motivation,
        "scope": scope if isinstance(scope, dict) else {},
        "artifacts": artifacts if isinstance(artifacts, list) else [],
        "resources": resources if isinstance(resources, dict) else {},
        "risks": risks if isinstance(risks, list) else [],
        "approval": {"state": "pending", **({"issue_url": issue_url} if issue_url else {})},
    }
    catalog = SchemaCatalog(root / "reference" / "schemas" / "v1")
    for schema_error in catalog.validate(proposal, PROPOSAL_SCHEMA):
        problems.append(_problem(schema_error.path, schema_error.message, "schema"))
    return ProposalIssue(not problems, proposal=proposal, issues=problems)
