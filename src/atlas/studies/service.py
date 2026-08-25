from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.utilities.serialization import load_data, yaml_writer
from atlas.validation.discovery import discover_data_files


class StudyError(RuntimeError):
    """A study scaffold operation could not be completed."""


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    for suffix in ("-study-proposal", "-proposal"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized or "study"


def _next_identifier(root: Path, prefix: str, width: int) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}(?P<number>\d{{{width}}})$")
    maximum = -1
    for path in discover_data_files(root, root):
        try:
            data = load_data(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        identifier = data.get("id")
        if isinstance(identifier, str) and (match := pattern.fullmatch(identifier)):
            maximum = max(maximum, int(match.group("number")))
    return f"{prefix}{maximum + 1:0{width}d}"


def _find_artifact(root: Path, identifier: str) -> tuple[Path, dict[str, Any]]:
    for path in discover_data_files(root, root):
        try:
            data = load_data(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id") == identifier:
            return path, data
    raise StudyError(f"No canonical artifact found with ID {identifier}")


def _proposal(root: Path, proposal_or_id: str) -> tuple[Path, dict[str, Any]]:
    candidate = Path(proposal_or_id)
    if candidate.exists():
        data = load_data(candidate)
        if not isinstance(data, dict):
            raise StudyError(f"Proposal must be an object: {candidate}")
        return candidate, data
    return _find_artifact(root, proposal_or_id)


def new_study(root: Path, proposal_or_id: str) -> Path:
    _, proposal = _proposal(root, proposal_or_id)
    if proposal.get("kind") != "Proposal" or proposal.get("proposal_type") != "study":
        raise StudyError("Study scaffolding requires a study proposal")
    approval = proposal.get("approval", {})
    if approval.get("state") != "approved" or not approval.get("issue_url"):
        raise StudyError("The study proposal must have an approved state and GitHub issue URL")

    identifier = _next_identifier(root, "S", 3)
    slug = _slug(str(proposal.get("slug", proposal.get("title", "study"))))
    study_root = root / "studies" / f"{identifier}-{slug}" / "v1"
    if study_root.exists():
        raise StudyError(f"Refusing to overwrite existing study: {study_root}")
    for name in (
        "configurations",
        "experiments",
        "execution",
        "findings",
        "decisions",
        "inputs",
    ):
        (study_root / name).mkdir(parents=True, exist_ok=True)

    template = load_data(root / "reference" / "templates" / "v1" / "study" / "study.yaml")
    if not isinstance(template, dict):
        raise StudyError("Invalid study template")
    now = _timestamp()
    template.update(
        {
            "id": identifier,
            "slug": slug,
            "title": str(proposal.get("title", f"Study {identifier}")),
            "description": str(proposal.get("summary", proposal.get("description", ""))),
            "created_at": now,
            "updated_at": now,
            "proposal": {
                "id": f"atlas://proposal/{proposal['id']}@v{proposal.get('version', 1)}",
                "issue_url": approval["issue_url"],
                "approval": "approved",
            },
        }
    )
    scope = proposal.get("scope", {})
    if isinstance(scope, dict):
        if isinstance(scope.get("archetype"), str):
            template["archetype"] = scope["archetype"]
        if isinstance(scope.get("research_questions"), list):
            template["research_questions"] = scope["research_questions"]
        template["boundaries"] = {
            "included": scope.get("included", template["boundaries"]["included"]),
            "excluded": scope.get("excluded", template["boundaries"]["excluded"]),
        }
    with (study_root / "study.yaml").open("w") as stream:
        yaml_writer().dump(template, stream)

    contribution = {
        "$schema": (
            "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
            "schemas/v1/contributions/contribution-manifest.schema.json"
        ),
        "proposal": f"atlas://proposal/{proposal['id']}@v{proposal.get('version', 1)}",
        "issue_url": approval["issue_url"],
        "approval_label": "proposal:approved",
        "contribution_type": "study",
        "artifacts": ["study.yaml"],
        "closes_issue": True,
    }
    with (study_root / "contribution.yaml").open("w") as stream:
        yaml_writer().dump(contribution, stream)
    return study_root


def find_study(root: Path, value: str) -> Path:
    studies_root = root / "studies"
    if not studies_root.exists():
        raise StudyError("No studies directory exists")
    matches = []
    for path in sorted(studies_root.glob("S*-*/v*")):
        directory_name = path.parent.name
        if value in {directory_name, directory_name.split("-", 1)[0]} or directory_name.endswith(
            f"-{value}"
        ):
            matches.append(path)
    if len(matches) != 1:
        raise StudyError(f"Expected one study matching {value!r}; found {len(matches)}")
    return matches[0]


def new_experiment(root: Path, study: str) -> Path:
    study_root = find_study(root, study)
    study_data = load_data(study_root / "study.yaml")
    if not isinstance(study_data, dict):
        raise StudyError(f"Invalid study record: {study_root / 'study.yaml'}")
    identifier = _next_identifier(root, "E", 4)
    experiment_root = study_root / "experiments" / identifier
    for name in ("runs", "comparisons"):
        (experiment_root / name).mkdir(parents=True, exist_ok=True)
    template = load_data(
        root / "reference" / "templates" / "v1" / "experiment" / "experiment.yaml"
    )
    if not isinstance(template, dict):
        raise StudyError("Invalid experiment template")
    now = _timestamp()
    template.update(
        {
            "id": identifier,
            "slug": f"experiment-{identifier.lower()}",
            "title": f"Experiment {identifier}",
            "description": (
                f"Controlled experiment in {study_data['id']}; complete before execution."
            ),
            "created_at": now,
            "updated_at": now,
            "study": f"atlas://study/{study_data['id']}@v{study_data.get('version', 1)}",
        }
    )
    output = experiment_root / "experiment.yaml"
    with output.open("w") as stream:
        yaml_writer().dump(template, stream)
    return experiment_root
