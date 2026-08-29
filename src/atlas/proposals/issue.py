from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
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
ISSUE_URL = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repository>[^/]+)/issues/(?P<number>[1-9][0-9]*)/?$"
)
IssueFetcher = Callable[[str], Any]


class ProposalIssueError(RuntimeError):
    """A GitHub proposal issue could not be read or materialized."""


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


def proposal_from_issue(root: Path, issue: dict[str, Any]) -> ProposalIssue:
    """Convert a GitHub issue-form payload into its canonical proposal record."""

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


def validate_issue_event(root: Path, event_path: Path) -> ProposalIssue:
    try:
        event = json.loads(event_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return ProposalIssue(False, issues=[_problem("/", f"Cannot read event: {error}")])
    issue = event.get("issue")
    if not isinstance(issue, dict):
        return ProposalIssue(False, issues=[_problem("/issue", "Event has no issue object")])
    return proposal_from_issue(root, issue)


def _issue_fetcher(token: str | None = None) -> IssueFetcher:
    def fetch(url: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "atlas-contribution-client",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProposalIssueError(f"GitHub issue request failed: {error}") from error

    return fetch


def fetch_issue_proposal(
    root: Path,
    issue_url: str,
    *,
    token: str | None = None,
    fetcher: IssueFetcher | None = None,
    require_approved: bool = True,
) -> dict[str, Any]:
    """Fetch, validate, and materialize a proposal from its GitHub issue."""

    match = ISSUE_URL.fullmatch(issue_url)
    if not match:
        raise ProposalIssueError(
            "Issue URL must look like https://github.com/OWNER/REPOSITORY/issues/123"
        )
    owner = urllib.parse.quote(match.group("owner"), safe="")
    repository = urllib.parse.quote(match.group("repository"), safe="")
    number = int(match.group("number"))
    fetch = fetcher or _issue_fetcher(token)
    payload = fetch(f"https://api.github.com/repos/{owner}/{repository}/issues/{number}")
    if not isinstance(payload, dict):
        raise ProposalIssueError("GitHub issue response is not an object")
    result = proposal_from_issue(root, payload)
    if not result.ok or result.proposal is None:
        details = "; ".join(issue["message"] for issue in result.issues)
        raise ProposalIssueError(f"Proposal issue is invalid: {details}")
    labels = {
        str(label.get("name")) for label in payload.get("labels", []) if isinstance(label, dict)
    }
    if require_approved and "proposal:approved" not in labels:
        raise ProposalIssueError("Proposal issue does not have the proposal:approved label")
    proposal = result.proposal
    if "proposal:approved" in labels:
        proposal["approval"] = {"state": "approved", "issue_url": issue_url}
    return proposal


def materialize_issue_proposal(
    root: Path,
    issue_url: str,
    *,
    output: Path | None = None,
    token: str | None = None,
    fetcher: IssueFetcher | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write an approved issue as canonical YAML without silently replacing a draft."""

    from atlas.utilities.serialization import load_data, yaml_writer

    proposal = fetch_issue_proposal(root, issue_url, token=token, fetcher=fetcher)
    destination = output or root / ".atlas" / "work" / "proposals" / f"{proposal['id']}.yaml"
    destination = destination if destination.is_absolute() else root / destination
    if destination.exists():
        existing = load_data(destination)
        if existing != proposal:
            raise ProposalIssueError(
                f"Refusing to overwrite a different materialized proposal: {destination}"
            )
        return destination, proposal
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w") as stream:
        yaml_writer().dump(proposal, stream)
    return destination, proposal
