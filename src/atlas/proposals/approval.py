from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from atlas.proposals.issue import proposal_from_issue
from atlas.schemas import SchemaCatalog
from atlas.utilities.serialization import canonical_json, yaml_loader

Fetcher = Callable[[str], Any]
CONTRIBUTION_SCHEMA = (
    "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
    "schemas/v1/contributions/contribution-manifest.schema.json"
)
ISSUE_TYPES = {
    "study": "study",
    "experiment": "experiment",
    "replication": "replication",
    "challenge": "finding_challenge",
    "methodology": "methodology",
}
CONTRIBUTION_TYPES = {
    "study": "study",
    "experiment": "experiment",
    "replication": "replication",
    "finding_challenge": "finding_challenge",
    "methodology": "methodology",
    "tooling": "methodology",
}


@dataclass(frozen=True)
class ApprovalReport:
    ok: bool
    checked_manifests: int = 0
    issues: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_manifests": self.checked_manifests,
            "issues": self.issues,
        }


def _problem(path: str, location: str, message: str, code: str = "approval") -> dict[str, str]:
    return {
        "severity": "error",
        "code": code,
        "path": path,
        "location": location,
        "message": message,
    }


def _github_fetcher(token: str) -> Fetcher:
    def fetch(url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "atlas-approval-gate",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise RuntimeError(f"GitHub API request failed for {url}: {error}") from error

    return fetch


def _changed_files(fetch: Fetcher, api_url: str) -> list[str]:
    files: list[str] = []
    for page in range(1, 31):
        payload = fetch(f"{api_url}/files?per_page=100&page={page}")
        if not isinstance(payload, list):
            raise RuntimeError("GitHub pull-request files response is not a list")
        files.extend(
            str(item["filename"])
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("filename"), str)
        )
        if len(payload) < 100:
            return files
    raise RuntimeError("Pull request exceeds the 3,000-file approval review limit")


def _manifest(fetch: Fetcher, repository: str, path: str, revision: str) -> dict[str, Any]:
    quoted_path = urllib.parse.quote(path, safe="/")
    quoted_revision = urllib.parse.quote(revision, safe="")
    payload = fetch(
        f"https://api.github.com/repos/{repository}/contents/{quoted_path}?ref={quoted_revision}"
    )
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise RuntimeError(f"Cannot read contribution manifest from pull request: {path}")
    content = payload.get("content")
    if not isinstance(content, str):
        raise RuntimeError(f"Contribution manifest has no content: {path}")
    data = yaml_loader().load(base64.b64decode(content).decode())
    if not isinstance(data, dict):
        raise RuntimeError(f"Contribution manifest must be a YAML object: {path}")
    return data


def _issue_number(issue_url: str, repository: str) -> int | None:
    expected = re.fullmatch(
        rf"https://github\.com/{re.escape(repository)}/issues/(?P<number>[1-9][0-9]*)/?",
        issue_url,
    )
    return int(expected.group("number")) if expected else None


def _artifact_changed(manifest_path: str, artifact: str, changed: set[str]) -> bool:
    if artifact.startswith("/"):
        return False
    parts = PurePosixPath(artifact).parts
    if ".." in parts:
        return False
    if artifact.startswith(
        (
            "studies/",
            "registry/",
            "reference/",
            "docs/",
            "src/",
            "tests/",
            "site/",
            ".github/",
        )
    ):
        resolved = str(PurePosixPath(artifact)).rstrip("/")
    else:
        parent = PurePosixPath(manifest_path).parent
        resolved = str(parent / artifact).rstrip("/")
    return resolved in changed or any(path.startswith(f"{resolved}/") for path in changed)


SEMANTIC_PROPOSAL_FIELDS = (
    "id",
    "version",
    "proposal_type",
    "title",
    "description",
    "authors",
    "summary",
    "motivation",
    "scope",
    "artifacts",
    "resources",
    "risks",
)


def _proposal_semantics(proposal: dict[str, Any]) -> str:
    return canonical_json({field: proposal.get(field) for field in SEMANTIC_PROPOSAL_FIELDS})


def _closes_issue(body: str, number: int, issue_url: str) -> bool:
    action = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
    return bool(re.search(rf"(?im)\b{action}\s+(?:#{number}\b|{re.escape(issue_url)})", body))


def check_pull_request_approval(
    root: Path,
    event_path: Path,
    token: str,
    *,
    fetcher: Fetcher | None = None,
) -> ApprovalReport:
    problems: list[dict[str, str]] = []
    try:
        event = json.loads(event_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        return ApprovalReport(False, issues=[_problem(str(event_path), "/", str(error))])
    pull = event.get("pull_request")
    repository_data = event.get("repository")
    if not isinstance(pull, dict) or not isinstance(repository_data, dict):
        return ApprovalReport(False, issues=[_problem(str(event_path), "/", "Not a PR event")])
    repository = repository_data.get("full_name")
    api_url = pull.get("url")
    head = pull.get("head")
    if (
        not isinstance(repository, str)
        or not isinstance(api_url, str)
        or not isinstance(head, dict)
    ):
        return ApprovalReport(False, issues=[_problem(str(event_path), "/", "Incomplete PR event")])
    revision = head.get("sha")
    branch = head.get("ref")
    if not isinstance(revision, str) or not isinstance(branch, str):
        return ApprovalReport(False, issues=[_problem(str(event_path), "/head", "Missing head")])
    fetch = fetcher or _github_fetcher(token)
    try:
        changed_files = _changed_files(fetch, api_url)
    except RuntimeError as error:
        return ApprovalReport(False, issues=[_problem(str(event_path), "/files", str(error))])
    changed = set(changed_files)
    manifests = [path for path in changed_files if PurePosixPath(path).name == "contribution.yaml"]
    if not manifests:
        return ApprovalReport(
            False,
            issues=[_problem("contribution.yaml", "/", "PR must add or update contribution.yaml")],
        )

    catalog = SchemaCatalog(root / "reference" / "schemas" / "v1")
    proposal_numbers: set[int] = set()
    for manifest_path in manifests:
        try:
            data = _manifest(fetch, repository, manifest_path, revision)
        except (RuntimeError, ValueError) as error:
            problems.append(_problem(manifest_path, "/", str(error)))
            continue
        for schema_error in catalog.validate(data, CONTRIBUTION_SCHEMA):
            problems.append(
                _problem(manifest_path, schema_error.path, schema_error.message, "schema")
            )
        issue_url = data.get("issue_url")
        issue_number = _issue_number(str(issue_url), repository)
        if issue_number is None:
            problems.append(
                _problem(manifest_path, "/issue_url", "Issue URL must target this repository")
            )
            continue
        proposal_numbers.add(issue_number)
        expected_proposal = f"atlas://proposal/P{issue_number:04d}@v1"
        if data.get("proposal") != expected_proposal:
            problems.append(
                _problem(
                    manifest_path,
                    "/proposal",
                    f"Proposal identity must be {expected_proposal}",
                )
            )
        for artifact in data.get("artifacts", []):
            if isinstance(artifact, str) and not _artifact_changed(
                manifest_path, artifact, changed
            ):
                problems.append(
                    _problem(
                        manifest_path,
                        "/artifacts",
                        f"Declared artifact is not changed by this PR: {artifact}",
                    )
                )
        try:
            issue = fetch(f"https://api.github.com/repos/{repository}/issues/{issue_number}")
        except RuntimeError as error:
            problems.append(_problem(manifest_path, "/issue_url", str(error)))
            continue
        if not isinstance(issue, dict):
            problems.append(_problem(manifest_path, "/issue_url", "Invalid issue response"))
            continue
        labels = {
            str(label.get("name")) for label in issue.get("labels", []) if isinstance(label, dict)
        }
        if "proposal:approved" not in labels:
            problems.append(_problem(manifest_path, "/approval_label", "Proposal is not approved"))
        issue_type = next(
            (value for key, value in ISSUE_TYPES.items() if f"proposal:type:{key}" in labels),
            None,
        )
        contribution_type = CONTRIBUTION_TYPES.get(str(data.get("contribution_type")))
        if issue_type is None or issue_type != contribution_type:
            problems.append(
                _problem(
                    manifest_path,
                    "/contribution_type",
                    "Contribution type does not match the approved proposal issue",
                )
            )
        if data.get("closes_issue") and not _closes_issue(
            str(pull.get("body") or ""), issue_number, str(issue_url)
        ):
            problems.append(
                _problem(
                    manifest_path,
                    "/closes_issue",
                    f"PR body must close issue #{issue_number}",
                )
            )
        proposal_path = str(PurePosixPath(manifest_path).parent / "proposal.yaml")
        try:
            committed_proposal = _manifest(fetch, repository, proposal_path, revision)
        except (RuntimeError, ValueError) as error:
            problems.append(
                _problem(
                    proposal_path,
                    "/",
                    f"Cannot read the canonical proposal beside contribution.yaml: {error}",
                )
            )
            continue
        issue_proposal = proposal_from_issue(root, issue)
        if not issue_proposal.ok or issue_proposal.proposal is None:
            messages = "; ".join(problem["message"] for problem in issue_proposal.issues)
            problems.append(
                _problem(
                    proposal_path,
                    "/",
                    f"Approved issue no longer materializes as a valid proposal: {messages}",
                )
            )
            continue
        if _proposal_semantics(committed_proposal) != _proposal_semantics(issue_proposal.proposal):
            problems.append(
                _problem(
                    proposal_path,
                    "/scope",
                    "Committed proposal does not match the approved issue semantics",
                )
            )
        approval = committed_proposal.get("approval", {})
        if approval.get("state") != "approved" or approval.get("issue_url") != issue_url:
            problems.append(
                _problem(
                    proposal_path,
                    "/approval",
                    "Committed proposal must record the approved issue URL and approved state",
                )
            )
    if len(proposal_numbers) > 1:
        problems.append(
            _problem("contribution.yaml", "/proposal", "One PR may implement only one proposal")
        )
    if proposal_numbers:
        number = next(iter(proposal_numbers))
        if not re.fullmatch(rf"(?:feat|fix|chore|docs)/{number}-[a-z0-9]+(?:-[a-z0-9]+)*", branch):
            problems.append(
                _problem(
                    "contribution.yaml",
                    "/branch",
                    f"Branch must use <type>/{number}-<slug>; found {branch}",
                )
            )
    return ApprovalReport(not problems, checked_manifests=len(manifests), issues=problems)
