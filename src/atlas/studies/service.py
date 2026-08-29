from __future__ import annotations

import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.identities import next_identifier, next_identifiers
from atlas.utilities.repository import repository_relative
from atlas.utilities.serialization import canonical_json, load_data, yaml_writer
from atlas.validation.discovery import discover_data_files
from atlas.validation.references import canonical_reference


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


def _study_identifier(root: Path, proposal: dict[str, Any]) -> str:
    scope = proposal.get("scope", {})
    requested = scope.get("study_id") if isinstance(scope, dict) else None
    if requested is None:
        return next_identifier(root, "study")
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


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        yaml_writer().dump(data, stream)


def _proposal_reference(proposal: dict[str, Any]) -> str:
    return f"atlas://proposal/{proposal['id']}@v{proposal.get('version', 1)}"


def _apply_scaffold_identity(
    data: dict[str, Any],
    proposal: dict[str, Any],
    *,
    identifier: str,
    slug: str,
    title: str,
    description: str,
    now: str,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    authors, _ = _study_authors(proposal)
    if roles:
        for author in authors:
            author["roles"] = roles
    issue_url = str(proposal["approval"]["issue_url"])
    data.update(
        {
            "id": identifier,
            "slug": slug,
            "title": title,
            "description": description,
            "authors": authors,
            "created_at": now,
            "updated_at": now,
            "provenance": {
                "method": "approved-proposal-scaffold",
                "source_paths": [issue_url],
                "generated": True,
                "parent_artifacts": [_proposal_reference(proposal)],
            },
        }
    )
    return data


def _first_reference(study: dict[str, Any], key: str, fallback: str) -> str:
    values = study.get("candidate_space", {}).get(key, [])
    return str(values[0]) if isinstance(values, list) and values else fallback


def _artifact_digests(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in discover_data_files(root, root):
        try:
            data = load_data(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        identifier = data.get("id")
        version = data.get("version")
        if not isinstance(identifier, str) or not isinstance(version, int):
            continue
        reference = canonical_reference(identifier, version, data.get("kind"))
        if reference:
            digests[reference] = hashlib.sha256(canonical_json(data).encode()).hexdigest()
    return digests


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
        "hypotheses",
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
    proposal_reference = _proposal_reference(proposal)
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
    _write_yaml(study_root / "study.yaml", template)

    contract_templates = {
        "workload.yaml": (
            "workload.yaml",
            f"WS{number}",
            f"{slug}-workload",
            f"{proposal.get('title', identifier)} workload",
            "Frozen workload contract generated from the approved study proposal.",
        ),
        "quality.yaml": (
            "quality.yaml",
            f"QC{number}",
            f"{slug}-quality",
            f"{proposal.get('title', identifier)} quality contract",
            "Frozen quality gate generated from the approved study proposal.",
        ),
        "slo.yaml": (
            "slo.yaml",
            f"SLO{number}",
            f"{slug}-slo",
            f"{proposal.get('title', identifier)} SLO profile",
            "Frozen service-level envelope generated from the approved study proposal.",
        ),
    }
    for output_name, (
        template_name,
        contract_id,
        contract_slug,
        title,
        description,
    ) in contract_templates.items():
        contract = load_data(root / "reference" / "templates" / "v1" / "study" / template_name)
        if not isinstance(contract, dict):
            raise StudyError(f"Invalid study contract template: {template_name}")
        _apply_scaffold_identity(
            contract,
            proposal,
            identifier=contract_id,
            slug=contract_slug,
            title=title,
            description=description,
            now=now,
        )
        if output_name == "workload.yaml":
            contract.update(
                {
                    "archetype": template["archetype"],
                    "product_brief": template["product_brief"],
                    "quality_contract": f"atlas://quality-contract/QC{number}@v1",
                    "slo_profile": f"atlas://slo/SLO{number}@v1",
                }
            )
            traffic = scope.get("traffic_regimes", []) if isinstance(scope, dict) else []
            if traffic:
                contract["traffic"]["profiles"] = traffic
        _write_yaml(study_root / output_name, contract)

    shutil.copyfile(
        root / "reference" / "templates" / "v1" / "study" / "README.md",
        study_root / "README.md",
    )
    for directory in ("inputs", "execution"):
        shutil.copyfile(
            root / "reference" / "templates" / "v1" / "study" / directory / "README.md",
            study_root / directory / "README.md",
        )

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
        "artifacts": [
            "README.md",
            "proposal.yaml",
            "study.yaml",
            "workload.yaml",
            "quality.yaml",
            "slo.yaml",
            "inputs",
            "execution",
            "configurations",
            "hypotheses",
            "experiments",
            "findings",
            "decisions",
        ],
        "closes_issue": True,
    }
    _write_yaml(study_root / "contribution.yaml", contribution)
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


def resolve_configurations(root: Path, study: str) -> list[Path]:
    """Refresh resolved hashes after the contributor freezes runtime settings."""

    study_root = find_study(root, study)
    digests = _artifact_digests(root)
    outputs: list[Path] = []
    reference_fields = (
        "workload",
        "quality",
        "slo",
        "model",
        "hardware",
        "runtime",
        "runtime_configuration",
    )
    for path in sorted((study_root / "configurations").glob("CFG*.yaml")):
        configuration = load_data(path)
        if not isinstance(configuration, dict) or configuration.get("kind") != "Configuration":
            continue
        unresolved = [
            str(configuration.get(field, field))
            for field in reference_fields
            if str(configuration.get(field, "")) not in digests
        ]
        if unresolved:
            raise StudyError(
                f"Cannot resolve {path.name}; missing canonical artifacts: {', '.join(unresolved)}"
            )
        configuration["resolved_hashes"] = {
            field: digests[str(configuration[field])] for field in reference_fields
        }
        configuration["updated_at"] = _timestamp()
        _write_yaml(path, configuration)
        outputs.append(path)
    if not outputs:
        raise StudyError(f"No resolved configurations found in {study_root / 'configurations'}")
    return outputs


def new_experiment(
    root: Path,
    study: str,
    proposal_or_id: str | None = None,
) -> Path:
    study_root = find_study(root, study)
    study_data = load_data(study_root / "study.yaml")
    if not isinstance(study_data, dict):
        raise StudyError(f"Invalid study record: {study_root / 'study.yaml'}")
    proposal_path: Path | None = None
    proposal: dict[str, Any] | None = None
    if proposal_or_id:
        proposal_path, proposal = _proposal(root, proposal_or_id)
        if proposal.get("kind") != "Proposal" or proposal.get("proposal_type") != "experiment":
            raise StudyError("Experiment scaffolding requires an experiment proposal")
        approval = proposal.get("approval", {})
        if approval.get("state") != "approved" or not approval.get("issue_url"):
            raise StudyError("The experiment proposal must be approved")
        expected_study = f"atlas://study/{study_data['id']}@v{study_data.get('version', 1)}"
        if proposal.get("scope", {}).get("study") != expected_study:
            raise StudyError(f"Experiment proposal scope.study must be {expected_study}")
    identifier = next_identifier(root, "experiment")
    hypothesis_id = next_identifier(root, "hypothesis")
    configuration_ids = next_identifiers(root, "configuration", count=2)
    runtime_configuration_ids = next_identifiers(root, "runtime-configuration", count=2)
    experiment_root = study_root / "experiments" / identifier
    for name in ("runs", "comparisons"):
        (experiment_root / name).mkdir(parents=True, exist_ok=True)
    template = load_data(root / "reference" / "templates" / "v1" / "experiment" / "experiment.yaml")
    if not isinstance(template, dict):
        raise StudyError("Invalid experiment template")
    now = _timestamp()
    scope = proposal.get("scope", {}) if proposal else {}
    title = (
        str(proposal.get("title", f"Experiment {identifier}"))
        if proposal
        else (f"Experiment {identifier}")
    )
    description = (
        str(proposal.get("summary", proposal.get("description", "")))
        if proposal
        else f"Controlled experiment in {study_data['id']}; complete before execution."
    )
    study_reference = f"atlas://study/{study_data['id']}@v{study_data.get('version', 1)}"
    study_provenance = {
        "method": "approved-study-scaffold",
        "source_paths": [str(study_data.get("proposal", {}).get("issue_url", ""))],
        "generated": True,
        "parent_artifacts": [study_reference, str(study_data.get("proposal", {}).get("id", ""))],
    }
    if proposal:
        _apply_scaffold_identity(
            template,
            proposal,
            identifier=identifier,
            slug=_slug(str(proposal.get("slug", title))),
            title=title,
            description=description,
            now=now,
        )
    else:
        template.update(
            {
                "authors": study_data.get("authors", template["authors"]),
                "provenance": study_provenance,
            }
        )
    template.update(
        {
            "id": identifier,
            "slug": template.get("slug") if proposal else f"experiment-{identifier.lower()}",
            "title": title,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "study": study_reference,
            "question": str(scope.get("question", title)),
            "hypothesis": f"atlas://hypothesis/{hypothesis_id}@v1",
            "baseline": f"atlas://configuration/{configuration_ids[0]}@v1",
            "candidates": [f"atlas://configuration/{configuration_ids[1]}@v1"],
            "changed_factors": scope.get("changed_factors", template["changed_factors"]),
            "frozen_factors": scope.get("frozen_factors", template["frozen_factors"]),
            "quality_gate": scope.get("quality_gate", template["quality_gate"]),
            "expected_mechanism": str(
                scope.get("expected_mechanism", template["expected_mechanism"])
            ),
        }
    )
    replicates = scope.get("replicates")
    if isinstance(replicates, int):
        template["protocol"]["replicates"] = replicates
    primary_metric = str(scope.get("primary_metric", template["metrics"]["primary"][0]))
    template["metrics"]["primary"] = [primary_metric]
    guardrails = scope.get("guardrails")
    if isinstance(guardrails, list):
        template["metrics"]["guardrails"] = guardrails

    hypothesis = load_data(
        root / "reference" / "templates" / "v1" / "experiment" / "hypothesis.yaml"
    )
    if not isinstance(hypothesis, dict):
        raise StudyError("Invalid hypothesis template")
    if proposal:
        _apply_scaffold_identity(
            hypothesis,
            proposal,
            identifier=hypothesis_id,
            slug=f"{template['slug']}-hypothesis",
            title=str(scope.get("hypothesis", title)),
            description=description,
            now=now,
        )
    else:
        hypothesis.update(
            {
                "id": hypothesis_id,
                "slug": f"{template['slug']}-hypothesis",
                "title": f"Hypothesis for {identifier}",
                "description": description,
                "authors": study_data.get("authors", []),
                "created_at": now,
                "updated_at": now,
                "provenance": study_provenance,
            }
        )
    hypothesis.update(
        {
            "observation": str(proposal.get("motivation", description))
            if proposal
            else description,
            "statement": str(scope.get("hypothesis", hypothesis["statement"])),
            "intervention": "; ".join(template["changed_factors"]),
            "expected_mechanism": template["expected_mechanism"],
            "primary_metric": primary_metric,
            "guardrails": template["metrics"]["guardrails"],
            "quality_gate": template["quality_gate"],
            "falsification_conditions": scope.get(
                "falsification_conditions", hypothesis["falsification_conditions"]
            ),
        }
    )
    _write_yaml(study_root / "hypotheses" / f"{hypothesis_id}.yaml", hypothesis)

    model = _first_reference(study_data, "models", "atlas://model/M000@v1")
    hardware = _first_reference(study_data, "hardware", "atlas://hardware/HW000@v1")
    runtime = _first_reference(study_data, "runtimes", "atlas://runtime/RT000@v1")
    condition_paths: list[Path] = []
    for role, configuration_id, runtime_configuration_id in zip(
        ("baseline", "candidate"),
        configuration_ids,
        runtime_configuration_ids,
        strict=True,
    ):
        runtime_configuration = load_data(
            root / "reference" / "templates" / "v1" / "experiment" / "runtime-configuration.yaml"
        )
        if not isinstance(runtime_configuration, dict):
            raise StudyError("Invalid runtime configuration template")
        if proposal:
            _apply_scaffold_identity(
                runtime_configuration,
                proposal,
                identifier=runtime_configuration_id,
                slug=f"{template['slug']}-{role}",
                title=f"{title} {role} runtime",
                description=f"{role.title()} runtime condition for {identifier}.",
                now=now,
            )
        else:
            runtime_configuration.update(
                {
                    "id": runtime_configuration_id,
                    "slug": f"{template['slug']}-{role}",
                    "title": f"{title} {role} runtime",
                    "description": f"{role.title()} runtime condition for {identifier}.",
                    "authors": study_data.get("authors", []),
                    "created_at": now,
                    "updated_at": now,
                    "provenance": study_provenance,
                }
            )
        runtime_configuration.update(
            {"runtime_build": runtime, "model": model, "hardware": hardware}
        )
        runtime_configuration.setdefault("extensions", {})["atlas.condition"] = {
            "role": role,
            "changed_factors": template["changed_factors"],
        }
        runtime_path = study_root / "configurations" / f"{runtime_configuration_id}.yaml"
        _write_yaml(runtime_path, runtime_configuration)

        configuration = load_data(
            root / "reference" / "templates" / "v1" / "experiment" / "configuration.yaml"
        )
        if not isinstance(configuration, dict):
            raise StudyError("Invalid configuration template")
        if proposal:
            _apply_scaffold_identity(
                configuration,
                proposal,
                identifier=configuration_id,
                slug=f"{template['slug']}-{role}",
                title=f"{title} {role} configuration",
                description=f"{role.title()} resolved condition for {identifier}.",
                now=now,
            )
        else:
            configuration.update(
                {
                    "id": configuration_id,
                    "slug": f"{template['slug']}-{role}",
                    "title": f"{title} {role} configuration",
                    "description": f"{role.title()} resolved condition for {identifier}.",
                    "authors": study_data.get("authors", []),
                    "created_at": now,
                    "updated_at": now,
                    "provenance": study_provenance,
                }
            )
        configuration.update(
            {
                "workload": study_data["contracts"]["workload"],
                "quality": study_data["contracts"]["quality"],
                "slo": study_data["contracts"]["slo"],
                "model": model,
                "hardware": hardware,
                "runtime": runtime,
                "runtime_configuration": (
                    f"atlas://runtime-configuration/{runtime_configuration_id}@v1"
                ),
            }
        )
        condition_path = study_root / "configurations" / f"{configuration_id}.yaml"
        _write_yaml(condition_path, configuration)
        condition_paths.extend([runtime_path, condition_path])

    digests = _artifact_digests(root)
    for configuration_id, runtime_configuration_id in zip(
        configuration_ids, runtime_configuration_ids, strict=True
    ):
        path = study_root / "configurations" / f"{configuration_id}.yaml"
        configuration = load_data(path)
        if not isinstance(configuration, dict):
            continue
        references = {
            "workload": configuration["workload"],
            "quality": configuration["quality"],
            "slo": configuration["slo"],
            "model": configuration["model"],
            "hardware": configuration["hardware"],
            "runtime": configuration["runtime"],
            "runtime_configuration": (
                f"atlas://runtime-configuration/{runtime_configuration_id}@v1"
            ),
        }
        configuration["resolved_hashes"] = {
            key: digests.get(reference, "0" * 64) for key, reference in references.items()
        }
        _write_yaml(path, configuration)

    output = experiment_root / "experiment.yaml"
    _write_yaml(output, template)
    shutil.copyfile(
        root / "reference" / "templates" / "v1" / "experiment" / "README.md",
        experiment_root / "README.md",
    )
    if proposal and proposal_path:
        proposal_output = experiment_root / "proposal.yaml"
        if proposal_path.resolve() != proposal_output.resolve():
            shutil.copyfile(proposal_path, proposal_output)
        artifact_paths = [
            repository_relative(experiment_root, root),
            repository_relative(study_root / "hypotheses" / f"{hypothesis_id}.yaml", root),
            *(repository_relative(path, root) for path in condition_paths),
            repository_relative(study_root / "findings", root),
        ]
        contribution = {
            "$schema": (
                "https://ayobami-00.github.io/llm-inference-optimization-atlas/"
                "schemas/v1/contributions/contribution-manifest.schema.json"
            ),
            "proposal": _proposal_reference(proposal),
            "issue_url": proposal["approval"]["issue_url"],
            "approval_label": "proposal:approved",
            "contribution_type": "experiment",
            "artifacts": artifact_paths,
            "closes_issue": True,
        }
        _write_yaml(experiment_root / "contribution.yaml", contribution)
    return experiment_root
