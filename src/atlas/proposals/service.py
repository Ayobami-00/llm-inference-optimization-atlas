from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.constants import EXIT_EXTERNAL
from atlas.utilities.serialization import load_data, yaml_writer
from atlas.validation import ValidationReport, Validator

PROPOSAL_TYPES = {
    "study": "study.yaml",
    "experiment": "experiment.yaml",
    "replication": "replication.yaml",
    "finding-challenge": "finding-challenge.yaml",
    "methodology": "methodology.yaml",
}

PROPOSAL_LABELS = {
    "study": "proposal:type:study",
    "experiment": "proposal:type:experiment",
    "replication": "proposal:type:replication",
    "finding_challenge": "proposal:type:challenge",
    "methodology": "proposal:type:methodology",
}


class ProposalError(RuntimeError):
    """A proposal operation could not be completed."""


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "proposal"


def new_proposal(root: Path, proposal_type: str, output: Path) -> Path:
    normalized_type = proposal_type.strip().lower().replace("_", "-")
    try:
        template_name = PROPOSAL_TYPES[normalized_type]
    except KeyError as error:
        choices = ", ".join(PROPOSAL_TYPES)
        raise ProposalError(f"Unknown proposal type {proposal_type!r}; choose {choices}") from error
    output = output if output.is_absolute() else Path.cwd() / output
    if output.exists():
        raise ProposalError(f"Refusing to overwrite existing proposal: {output}")
    template = root / "reference" / "templates" / "v1" / "proposals" / template_name
    data = load_data(template)
    if not isinstance(data, dict):
        raise ProposalError(f"Invalid proposal template: {template}")
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data["created_at"] = timestamp
    data["updated_at"] = timestamp
    data["slug"] = _slug(output.stem)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        yaml_writer().dump(data, stream)
    return output


def validate_proposal(root: Path, path: Path) -> ValidationReport:
    return Validator(root).validate_path(path)


def render_proposal(data: dict[str, Any]) -> str:
    lines = [
        f"# {data.get('title', 'Atlas proposal')}",
        "",
        str(data.get("summary", data.get("description", ""))),
        "",
        "## Proposal identity",
        "",
        f"- Proposal: `{data.get('id', 'unknown')}@v{data.get('version', 1)}`",
        f"- Type: `{data.get('proposal_type', 'unknown')}`",
        f"- Status: `{data.get('approval', {}).get('state', 'pending')}`",
        "",
        "## Motivation",
        "",
        str(data.get("motivation", "")),
        "",
        "## Scope",
        "",
        "```yaml",
    ]
    stream = io.StringIO()
    yaml_writer().dump(data.get("scope", {}), stream)
    lines.extend([stream.getvalue().rstrip(), "```", "", "## Planned artifacts", ""])
    lines.extend(f"- `{artifact}`" for artifact in data.get("artifacts", []))
    lines.extend(["", "## Resources", "", "```yaml"])
    stream = io.StringIO()
    yaml_writer().dump(data.get("resources", {}), stream)
    lines.extend([stream.getvalue().rstrip(), "```", "", "## Risks", ""])
    risks = data.get("risks", [])
    lines.extend(f"- {risk}" for risk in risks)
    lines.extend(
        [
            "",
            "<!-- atlas-proposal",
            f"id: {data.get('id', 'unknown')}",
            f"version: {data.get('version', 1)}",
            f"type: {data.get('proposal_type', 'unknown')}",
            "-->",
            "",
        ]
    )
    return "\n".join(lines)


def create_github_issue(path: Path, data: dict[str, Any], repository: str | None = None) -> str:
    executable = shutil.which("gh")
    if not executable:
        raise ProposalError("GitHub CLI is not installed or not on PATH")
    body = render_proposal(data)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as stream:
        stream.write(body)
        body_path = Path(stream.name)
    command = [
        executable,
        "issue",
        "create",
        "--title",
        str(data.get("title", path.stem)),
        "--body-file",
        str(body_path),
        "--label",
        PROPOSAL_LABELS.get(
            str(data.get("proposal_type", "methodology")),
            "proposal:type:methodology",
        ),
        "--label",
        "proposal:needs-triage",
    ]
    if repository:
        command.extend(["--repo", repository])
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    finally:
        body_path.unlink(missing_ok=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise ProposalError(f"GitHub issue creation failed ({EXIT_EXTERNAL}): {message}")
    return result.stdout.strip()
