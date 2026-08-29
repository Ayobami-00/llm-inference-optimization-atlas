from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.proposals import ProposalIssueError, materialize_issue_proposal
from atlas.proposals.issue import IssueFetcher
from atlas.studies import StudyError, find_study, new_experiment, new_study
from atlas.utilities.repository import repository_relative
from atlas.utilities.serialization import load_data
from atlas.validation import Validator
from atlas.validation.discovery import discover_data_files


class ContributionError(RuntimeError):
    """A contribution could not be started or inspected."""


@dataclass(frozen=True)
class ContributionStart:
    proposal_id: str
    proposal_type: str
    proposal_path: str
    contribution_path: str
    expected_branch: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "proposal_path": self.proposal_path,
            "contribution_path": self.contribution_path,
            "expected_branch": self.expected_branch,
        }


@dataclass(frozen=True)
class ContributionStage:
    name: str
    complete: bool
    detail: str
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "complete": self.complete,
            "detail": self.detail,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class ContributionStatus:
    study: str
    path: str
    ready: bool
    stages: tuple[ContributionStage, ...]
    counts: dict[str, int]
    validation_errors: int

    @property
    def next_action(self) -> str:
        return next(
            (stage.next_action for stage in self.stages if not stage.complete),
            "Open or update the pull request and request review.",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ready,
            "study": self.study,
            "path": self.path,
            "ready": self.ready,
            "next_action": self.next_action,
            "counts": self.counts,
            "validation_errors": self.validation_errors,
            "stages": [stage.as_dict() for stage in self.stages],
        }


def start_contribution(
    root: Path,
    issue_url: str,
    *,
    token: str | None = None,
    fetcher: IssueFetcher | None = None,
) -> ContributionStart:
    """Start an approved study or experiment contribution from one issue URL."""

    try:
        proposal_path, proposal = materialize_issue_proposal(
            root, issue_url, token=token, fetcher=fetcher
        )
        proposal_type = str(proposal.get("proposal_type"))
        if proposal_type == "study":
            path = new_study(root, str(proposal_path))
        elif proposal_type == "experiment":
            study_reference = str(proposal.get("scope", {}).get("study", ""))
            match = re.fullmatch(r"atlas://study/(?P<id>S[0-9]{3})@v[1-9][0-9]*", study_reference)
            if not match:
                raise ContributionError(
                    "Experiment proposal scope.study must be an atlas://study/S###@v# reference"
                )
            path = new_experiment(root, match.group("id"), str(proposal_path))
        else:
            raise ContributionError(
                "Contribution start currently scaffolds approved study and experiment proposals; "
                f"materialized {proposal_type!r} at {proposal_path}"
            )
    except (ProposalIssueError, StudyError) as error:
        raise ContributionError(str(error)) from error
    return ContributionStart(
        proposal_id=str(proposal["id"]),
        proposal_type=str(proposal["proposal_type"]),
        proposal_path=repository_relative(proposal_path, root),
        contribution_path=repository_relative(path, root),
        expected_branch=(
            f"feat/{int(str(proposal['id'])[1:])}-{proposal.get('slug', 'contribution')}"
        ),
    )


def _artifacts(study_root: Path, root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in discover_data_files(study_root, root):
        try:
            data = load_data(path)
        except Exception:
            continue
        if isinstance(data, dict):
            artifacts.append(data)
    return artifacts


def _incomplete_scaffold(data: dict[str, Any]) -> bool:
    marker = data.get("extensions", {}).get("atlas.scaffold")
    return isinstance(marker, dict) and marker.get("complete") is not True


def _accepted_run(data: dict[str, Any]) -> bool:
    return bool(
        data.get("kind") == "RunRecord"
        and data.get("outcome") == "complete"
        and data.get("validation", {}).get("passed") is True
        and data.get("quality", {}).get("passed") is True
    )


def _expected_runs(experiments: list[dict[str, Any]]) -> int:
    expected = 0
    for experiment in experiments:
        replicates = experiment.get("protocol", {}).get("replicates", 0)
        candidates = experiment.get("candidates", [])
        if isinstance(replicates, int) and isinstance(candidates, list):
            expected += replicates * (1 + len(candidates))
    return expected


def _count_label(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or f'{singular}s')}"


def contribution_status(root: Path, study: str) -> ContributionStatus:
    """Explain contribution readiness as a staged, actionable checklist."""

    try:
        study_root = find_study(root, study)
    except StudyError as error:
        raise ContributionError(str(error)) from error
    artifacts = _artifacts(study_root, root)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        kind = artifact.get("kind")
        if isinstance(kind, str):
            by_kind.setdefault(kind, []).append(artifact)

    proposal_records = by_kind.get("Proposal", [])
    approved = any(
        proposal.get("approval", {}).get("state") == "approved"
        and proposal.get("approval", {}).get("issue_url")
        for proposal in proposal_records
    )
    core_paths = [
        study_root / name for name in ("study.yaml", "workload.yaml", "quality.yaml", "slo.yaml")
    ]
    core_records: list[dict[str, Any]] = []
    for path in core_paths:
        if not path.exists():
            continue
        try:
            record = load_data(path)
        except Exception:
            continue
        if isinstance(record, dict):
            core_records.append(record)
    design_complete = len(core_records) == len(core_paths) and not any(
        _incomplete_scaffold(record) for record in core_records
    )

    experiments = by_kind.get("Experiment", [])
    hypotheses = by_kind.get("Hypothesis", [])
    configurations = by_kind.get("Configuration", [])
    runtime_configurations = by_kind.get("RuntimeConfiguration", [])
    experiment_records = experiments + hypotheses + configurations + runtime_configurations
    preregistered = bool(experiments) and not any(
        _incomplete_scaffold(record) for record in experiment_records
    )

    bundle_roots = (
        [path for path in sorted((study_root / "execution").iterdir()) if path.is_dir()]
        if (study_root / "execution").exists()
        else []
    )
    execution_complete = bool(bundle_roots) and all(
        all((bundle / required).is_file() for required in ("README.md", "execution.yaml", "run.sh"))
        for bundle in bundle_roots
    )

    runs = by_kind.get("RunRecord", [])
    accepted_runs = [run for run in runs if _accepted_run(run)]
    expected_runs = _expected_runs(experiments)
    evidence_complete = expected_runs > 0 and len(accepted_runs) >= expected_runs
    comparisons = by_kind.get("Comparison", [])
    accepted_comparisons = [
        comparison for comparison in comparisons if comparison.get("status") == "accepted"
    ]
    analysis_complete = bool(experiments) and len(accepted_comparisons) >= len(experiments)
    findings = by_kind.get("Finding", [])
    interpretation_complete = bool(accepted_comparisons) and len(findings) >= len(
        accepted_comparisons
    )
    decisions = by_kind.get("DeploymentDecision", [])
    decision_complete = bool(decisions)

    validation = Validator(root).validate_path(study_root, strict=True)
    manifests = [path for path in study_root.rglob("contribution.yaml") if path.is_file()]
    scaffold_count = sum(_incomplete_scaffold(artifact) for artifact in artifacts)
    publication_complete = bool(manifests) and validation.ok and scaffold_count == 0

    stages = (
        ContributionStage(
            "Approved proposal",
            approved,
            "Approved canonical proposal is recorded."
            if approved
            else "No approved proposal is recorded.",
            "Obtain proposal:approved, then run atlas contribution start <issue-url>.",
        ),
        ContributionStage(
            "Frozen study design",
            design_complete,
            f"{len(core_records)}/{len(core_paths)} study contracts present; "
            f"{sum(_incomplete_scaffold(record) for record in core_records)} "
            "still marked incomplete.",
            "Complete study.yaml, workload.yaml, quality.yaml, and slo.yaml; "
            "remove their scaffold markers.",
        ),
        ContributionStage(
            "Preregistered experiments",
            preregistered,
            f"{len(experiments)} experiments, {len(hypotheses)} hypotheses, "
            f"{len(configurations)} configurations.",
            "Run atlas experiment new <study>, freeze all factors, run atlas study resolve "
            "<study>, then remove scaffold markers.",
        ),
        ContributionStage(
            "Reproducible execution",
            execution_complete,
            f"{_count_label(len(bundle_roots), 'execution bundle')} with the required "
            "lifecycle interface.",
            "Add an execution bundle with README.md, execution.yaml, and run.sh.",
        ),
        ContributionStage(
            "Accepted evidence",
            evidence_complete,
            f"{len(accepted_runs)}/{expected_runs} expected validated, "
            "quality-eligible runs accepted.",
            "Run the full profile, validate each draft, and promote immutable run IDs.",
        ),
        ContributionStage(
            "Controlled comparisons",
            analysis_complete,
            f"{len(accepted_comparisons)} accepted comparisons for {len(experiments)} experiments.",
            "Run atlas compare for every experiment and review the generated effects.",
        ),
        ContributionStage(
            "Scoped findings",
            interpretation_complete,
            f"{len(findings)} findings for {len(accepted_comparisons)} accepted comparisons.",
            "Author findings that retain negative and inconclusive evidence and do not "
            "exceed scope.",
        ),
        ContributionStage(
            "Deployment decision",
            decision_complete,
            f"{_count_label(len(decisions), 'deployment decision artifact')}.",
            "Add a deployment decision or an explicit no-recommendation outcome.",
        ),
        ContributionStage(
            "Publication checks",
            publication_complete,
            f"{len(validation.errors)} strict validation errors and {scaffold_count} "
            "incomplete markers.",
            "Resolve strict validation errors, run make check, and complete the "
            "pull-request checklist.",
        ),
    )
    counts = {
        "experiments": len(experiments),
        "execution_bundles": len(bundle_roots),
        "accepted_runs": len(accepted_runs),
        "comparisons": len(accepted_comparisons),
        "findings": len(findings),
        "decisions": len(decisions),
    }
    return ContributionStatus(
        study=str(by_kind.get("Study", [{}])[0].get("id", study)),
        path=repository_relative(study_root, root),
        ready=all(stage.complete for stage in stages),
        stages=stages,
        counts=counts,
        validation_errors=len(validation.errors),
    )
