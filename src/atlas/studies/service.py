from __future__ import annotations

import re
import shutil
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
    maximum = 0
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


def _study_identifier(root: Path, proposal: dict[str, Any]) -> str:
    scope = proposal.get("scope", {})
    requested = scope.get("study_id") if isinstance(scope, dict) else None
    if requested is None:
        return _next_identifier(root, "S", 3)
    identifier = str(requested)
    if not re.fullmatch(r"S[0-9]{3}", identifier):
        raise StudyError("Study proposal scope.study_id must match S###")
    try:
        _find_artifact(root, identifier)
    except StudyError:
        return identifier
    raise StudyError(f"Canonical artifact ID already exists: {identifier}")


def _study_authors(proposal: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    authors: list[dict[str, Any]] = []
    maintainers: list[str] = []
    for value in proposal.get("authors", []):
        if not isinstance(value, dict) or not value.get("name"):
            continue
        author = {
            key: value[key]
            for key in ("name", "github", "orcid", "affiliation", "conflicts")
            if key in value
        }
        author["roles"] = ["investigator"]
        author.setdefault("conflicts", [])
        authors.append(author)
        maintainers.append(str(value.get("github") or value["name"]))
    if not authors:
        raise StudyError("The approved proposal must identify at least one author")
    return authors, maintainers


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
    proposal_path, proposal = _proposal(root, proposal_or_id)
    if proposal.get("kind") != "Proposal" or proposal.get("proposal_type") != "study":
        raise StudyError("Study scaffolding requires a study proposal")
    approval = proposal.get("approval", {})
    if approval.get("state") != "approved" or not approval.get("issue_url"):
        raise StudyError("The study proposal must have an approved state and GitHub issue URL")

    identifier = _study_identifier(root, proposal)
    scope = proposal.get("scope", {})
    requested_slug = scope.get("slug") if isinstance(scope, dict) else None
    slug = _slug(str(requested_slug or proposal.get("slug", proposal.get("title", "study"))))
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
    authors, maintainers = _study_authors(proposal)
    number = identifier.removeprefix("S")
    proposal_reference = f"atlas://proposal/{proposal['id']}@v{proposal.get('version', 1)}"
    template.update(
        {
            "id": identifier,
            "slug": slug,
            "title": str(proposal.get("title", f"Study {identifier}")),
            "description": str(proposal.get("summary", proposal.get("description", ""))),
            "created_at": now,
            "updated_at": now,
            "authors": authors,
            "product_brief": str(
                scope.get("product_brief", proposal.get("summary", proposal.get("description", "")))
            ),
            "proposal": {
                "id": proposal_reference,
                "issue_url": approval["issue_url"],
                "approval": "approved",
            },
            "contracts": {
                "workload": f"atlas://workload-spec/WS{number}@v1",
                "quality": f"atlas://quality-contract/QC{number}@v1",
                "slo": f"atlas://slo/SLO{number}@v1",
            },
            "candidate_space": {
                "models": scope.get("models", []),
                "hardware": scope.get("hardware", []),
                "runtimes": scope.get("runtimes", []),
            },
            "maintainers": maintainers,
            "provenance": {
                "method": "approved-proposal-scaffold",
                "source_paths": [approval["issue_url"]],
                "generated": True,
                "parent_artifacts": [proposal_reference],
            },
        }
    )
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

    proposal_output = study_root / "proposal.yaml"
    if proposal_path.resolve() != proposal_output.resolve():
        shutil.copyfile(proposal_path, proposal_output)

    contribution = {
        "$schema": (
            "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
            "schemas/v1/contributions/contribution-manifest.schema.json"
        ),
        "proposal": f"atlas://proposal/{proposal['id']}@v{proposal.get('version', 1)}",
        "issue_url": approval["issue_url"],
        "approval_label": "proposal:approved",
        "contribution_type": "study",
        "artifacts": ["proposal.yaml", "study.yaml"],
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
    template = load_data(root / "reference" / "templates" / "v1" / "experiment" / "experiment.yaml")
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
