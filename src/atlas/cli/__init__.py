"""Atlas command-line interface."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from atlas import __version__
from atlas.comparisons import ComparisonError, compare_all, compare_experiment
from atlas.constants import EXIT_EXECUTION, EXIT_EXTERNAL, EXIT_INTEGRITY, EXIT_VALIDATION
from atlas.execution import (
    ExecutionError,
    bundle_plan,
    destroy_bundle,
    find_bundle,
    list_bundles,
    prepare_bundle,
    run_bundle,
    start_bundle,
)
from atlas.execution.cache import inspect_cache, prune_cache
from atlas.execution.evidence import promote_evidence, validate_evidence
from atlas.graph import GraphCompiler, GraphError
from atlas.graph.server import serve_site
from atlas.ontology import check_ontology
from atlas.proposals import (
    create_github_issue,
    new_proposal,
    render_proposal,
    validate_proposal,
)
from atlas.proposals.service import ProposalError
from atlas.schemas import SchemaCatalog
from atlas.sources import build_source_catalog, check_sources
from atlas.studies import StudyError, new_experiment, new_study
from atlas.utilities.repository import find_repository_root, repository_relative
from atlas.utilities.serialization import load_data
from atlas.validation import ValidationReport, Validator
from atlas.validation.ids import check_ids


@dataclass
class CLIState:
    json_output: bool = False


app = typer.Typer(no_args_is_help=True, help="Validate, run, and explore Atlas evidence.")
schema_app = typer.Typer(no_args_is_help=True, help="Inspect frozen schema contracts.")
ontology_app = typer.Typer(no_args_is_help=True, help="Validate the inference ontology.")
sources_app = typer.Typer(no_args_is_help=True, help="Validate external source records.")
ids_app = typer.Typer(no_args_is_help=True, help="Validate artifact identities and references.")
proposal_app = typer.Typer(no_args_is_help=True, help="Create and review contribution proposals.")
study_app = typer.Typer(no_args_is_help=True, help="Create and inspect Atlas studies.")
experiment_app = typer.Typer(no_args_is_help=True, help="Create controlled experiments.")
execution_app = typer.Typer(no_args_is_help=True, help="Prepare and run execution bundles.")
evidence_app = typer.Typer(no_args_is_help=True, help="Validate and promote run evidence.")
finding_app = typer.Typer(no_args_is_help=True, help="Validate evidence-backed findings.")
decision_app = typer.Typer(no_args_is_help=True, help="Validate deployment decisions.")
cache_app = typer.Typer(no_args_is_help=True, help="Inspect and prune the shared artifact cache.")
graph_app = typer.Typer(no_args_is_help=True, help="Compile and serve evidence graph projections.")
app.add_typer(schema_app, name="schema")
app.add_typer(ontology_app, name="ontology")
app.add_typer(sources_app, name="sources")
app.add_typer(ids_app, name="ids")
app.add_typer(proposal_app, name="proposal")
app.add_typer(study_app, name="study")
app.add_typer(experiment_app, name="experiment")
app.add_typer(execution_app, name="execution")
app.add_typer(evidence_app, name="evidence")
app.add_typer(finding_app, name="finding")
app.add_typer(decision_app, name="decision")
app.add_typer(cache_app, name="cache")
app.add_typer(graph_app, name="graph")


@app.callback()
def main(
    ctx: typer.Context,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit stable JSON instead of formatted text.")
    ] = False,
) -> None:
    """Operate a schema-first Atlas repository."""
    ctx.obj = CLIState(json_output=json_output)


def _state(ctx: typer.Context) -> CLIState:
    return ctx.ensure_object(CLIState)


def _emit(ctx: typer.Context, payload: dict[str, Any], *, title: str) -> None:
    if _state(ctx).json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console = Console()
    ok = bool(payload.get("ok", True))
    console.print(f"[{'green' if ok else 'red'}]{title}: {'ok' if ok else 'failed'}[/]")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    for key, value in payload.items():
        if key in {"ok", "issues"}:
            continue
        rendered = (
            json.dumps(value, sort_keys=True)
            if isinstance(value, (dict, list))
            else str(value)
        )
        table.add_row(key.replace("_", " "), rendered)
    console.print(table)
    for issue in payload.get("issues", []):
        color = "red" if issue.get("severity") == "error" else "yellow"
        console.print(
            f"[{color}]{issue.get('severity', 'error')}[/] "
            f"{issue.get('path', '')}{issue.get('location', '')}: {issue.get('message', '')}"
        )


def _exit_for_report(ok: bool) -> None:
    if not ok:
        raise typer.Exit(EXIT_VALIDATION)


@app.command()
def version() -> None:
    """Print the Atlas version."""
    typer.echo(__version__)


def _tool_version(name: str, *arguments: str) -> dict[str, Any]:
    executable = shutil.which(name)
    if not executable:
        return {"available": False}
    result = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    first_line = (result.stdout or result.stderr).strip().splitlines()
    return {
        "available": result.returncode == 0,
        "version": first_line[0] if first_line else "unknown",
    }


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Inspect the local environment without downloading or changing artifacts."""
    root = find_repository_root()
    tools = {
        "git": _tool_version("git", "--version"),
        "uv": _tool_version("uv", "--version"),
        "node": _tool_version("node", "--version"),
        "npm": _tool_version("npm", "--version"),
        "docker": _tool_version("docker", "--version"),
    }
    payload = {
        "ok": tools["git"]["available"] and tools["uv"]["available"],
        "atlas_version": __version__,
        "repository": str(root),
        "python": sys.version.split()[0],
        "platform": platform.system().lower(),
        "architecture": platform.machine().lower(),
        "tools": tools,
    }
    _emit(ctx, payload, title="Atlas doctor")
    _exit_for_report(bool(payload["ok"]))


@schema_app.command("check")
def schema_check(ctx: typer.Context) -> None:
    """Validate every V1 schema against JSON Schema Draft 2020-12."""
    root = find_repository_root()
    catalog = SchemaCatalog(root / "reference" / "schemas" / "v1")
    errors = catalog.check()
    payload = {
        "ok": not errors,
        "schemas": len(catalog.identifiers),
        "draft": "2020-12",
        "issues": [
            {
                "severity": "error",
                "path": error.path,
                "location": "/",
                "message": error.message,
            }
            for error in errors
        ],
    }
    _emit(ctx, payload, title="Schema check")
    _exit_for_report(bool(payload["ok"]))


@ontology_app.command("check")
def ontology_check(ctx: typer.Context) -> None:
    """Validate ontology schemas, coverage, IDs, and references."""
    report = check_ontology(find_repository_root())
    _emit(ctx, report.as_dict(), title="Ontology check")
    _exit_for_report(report.ok)


@sources_app.command("check")
def sources_check(
    ctx: typer.Context,
    build: Annotated[
        bool, typer.Option("--build", help="Also generate catalog.json and bibliography.bib.")
    ] = False,
) -> None:
    """Validate passive external-source records."""
    root = find_repository_root()
    report = check_sources(root)
    payload = report.as_dict()
    if build and report.ok:
        catalog, bibliography = build_source_catalog(root)
        payload["generated"] = [
            repository_relative(catalog, root),
            repository_relative(bibliography, root),
        ]
    _emit(ctx, payload, title="Source check")
    _exit_for_report(report.ok)


@ids_app.command("check")
def ids_check(ctx: typer.Context) -> None:
    """Detect duplicate identities and unresolved Atlas references."""
    report = check_ids(find_repository_root())
    _emit(ctx, report.as_dict(), title="Identity check")
    _exit_for_report(report.ok)


def _github_annotations(report: ValidationReport) -> None:
    for issue in report.issues:
        level = "error" if issue.severity == "error" else "warning"
        message = issue.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        typer.echo(f"::{level} file={issue.path},title=Atlas {issue.code}::{message}")


@app.command("validate")
def validate(
    ctx: typer.Context,
    path: Annotated[Path | None, typer.Argument(help="File or directory to validate.")] = None,
    all_artifacts: Annotated[
        bool, typer.Option("--all", help="Validate all canonical repository artifacts.")
    ] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Resolve references and enforce identity uniqueness.")
    ] = False,
    github: Annotated[
        bool, typer.Option("--github", help="Emit GitHub workflow annotations.")
    ] = False,
) -> None:
    """Validate canonical YAML and JSON artifacts without downloading models."""
    root = find_repository_root()
    target = root if all_artifacts else (path or Path.cwd())
    target = target if target.is_absolute() else root / target
    if not target.exists():
        raise typer.BadParameter(f"Path does not exist: {target}")
    report = Validator(root).validate_path(target, strict=strict)
    if github:
        _github_annotations(report)
    else:
        _emit(ctx, report.as_dict(), title="Artifact validation")
    _exit_for_report(report.ok)


@proposal_app.command("new")
def proposal_new(
    ctx: typer.Context,
    proposal_type: Annotated[str, typer.Argument(help="Proposal type.")],
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("proposal.yaml"),
) -> None:
    """Create a proposal from a V1 reference template."""
    try:
        path = new_proposal(find_repository_root(), proposal_type, output)
    except ProposalError as error:
        raise typer.BadParameter(str(error)) from error
    _emit(
        ctx,
        {"ok": True, "type": proposal_type, "path": str(path)},
        title="Proposal created",
    )


@proposal_app.command("validate")
def proposal_validate(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate a proposal against its declared V1 schema."""
    report = validate_proposal(find_repository_root(), path)
    _emit(ctx, report.as_dict(), title="Proposal validation")
    _exit_for_report(report.ok)


@proposal_app.command("render")
def proposal_render(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Render a proposal as a human-reviewable GitHub issue body."""
    data = load_data(path)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Proposal must be an object: {path}")
    body = render_proposal(data)
    if _state(ctx).json_output:
        typer.echo(json.dumps({"ok": True, "body": body}, indent=2, sort_keys=True))
    else:
        typer.echo(body)


@proposal_app.command("create-issue")
def proposal_create_issue(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    repository: Annotated[
        str | None, typer.Option("--repo", help="GitHub OWNER/REPOSITORY override.")
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Create the external issue without an interactive prompt.")
    ] = False,
) -> None:
    """Create the rendered proposal as a GitHub issue."""
    root = find_repository_root()
    report = validate_proposal(root, path)
    if not report.ok:
        _emit(ctx, report.as_dict(), title="Proposal validation")
        raise typer.Exit(EXIT_VALIDATION)
    data = load_data(path)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Proposal must be an object: {path}")
    if not yes and not typer.confirm("Create this public GitHub issue?"):
        raise typer.Abort()
    try:
        url = create_github_issue(path, data, repository)
    except ProposalError as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXTERNAL) from error
    _emit(ctx, {"ok": True, "issue_url": url}, title="Proposal issue created")


@study_app.command("new")
def study_new(
    ctx: typer.Context,
    proposal_or_id: Annotated[
        str, typer.Argument(help="Approved proposal path or canonical P#### ID.")
    ],
) -> None:
    """Create a study hierarchy from an approved proposal."""
    root = find_repository_root()
    try:
        path = new_study(root, proposal_or_id)
    except StudyError as error:
        raise typer.BadParameter(str(error)) from error
    _emit(
        ctx,
        {"ok": True, "path": repository_relative(path, root)},
        title="Study scaffold created",
    )


@experiment_app.command("new")
def experiment_new(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument(help="Study ID or directory slug.")],
) -> None:
    """Create an experiment hierarchy inside a study."""
    root = find_repository_root()
    try:
        path = new_experiment(root, study)
    except StudyError as error:
        raise typer.BadParameter(str(error)) from error
    _emit(
        ctx,
        {"ok": True, "path": repository_relative(path, root)},
        title="Experiment scaffold created",
    )


@execution_app.command("list")
def execution_list(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument(help="Study ID or slug.")],
) -> None:
    """List reproducible execution bundles for a study."""
    try:
        bundles = list_bundles(find_repository_root(), study)
    except (StudyError, ExecutionError) as error:
        raise typer.BadParameter(str(error)) from error
    _emit(ctx, {"ok": True, "study": study, "bundles": bundles}, title="Execution bundles")


@execution_app.command("prepare")
def execution_prepare(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument()],
    bundle_name: Annotated[str, typer.Argument()],
    yes: Annotated[
        bool, typer.Option("--yes", help="Accept displayed licenses and download artifacts.")
    ] = False,
) -> None:
    """Resolve and checksum declared artifacts into the shared cache."""
    root = find_repository_root()
    try:
        bundle = find_bundle(root, study, bundle_name)
        plan = bundle_plan(bundle, root / ".atlas" / "cache")
    except (StudyError, ExecutionError) as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXECUTION) from error
    _emit(ctx, {"ok": True, **plan}, title="Preparation plan")
    downloads = [artifact for artifact in plan["artifacts"] if not artifact["cached"]]
    if downloads and not yes and not typer.confirm("Accept these licenses and download artifacts?"):
        raise typer.Abort()
    try:
        paths = prepare_bundle(bundle, root / ".atlas" / "cache")
    except ExecutionError as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXTERNAL) from error
    _emit(
        ctx,
        {"ok": True, "prepared": [str(path) for path in paths]},
        title="Execution artifacts prepared",
    )


@execution_app.command("start")
def execution_start(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument()],
    bundle_name: Annotated[str, typer.Argument()],
) -> None:
    """Start resources declared by an execution bundle."""
    root = find_repository_root()
    try:
        bundle = find_bundle(root, study, bundle_name)
        work_dir = start_bundle(root, bundle)
    except (StudyError, ExecutionError) as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXECUTION) from error
    _emit(ctx, {"ok": True, "work_dir": str(work_dir)}, title="Execution resources started")


@execution_app.command("run")
def execution_run(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument()],
    bundle_name: Annotated[str, typer.Argument()],
    profile: Annotated[str, typer.Option("--profile")] = "quick",
) -> None:
    """Run a bundle and always execute its declared cleanup lifecycle."""
    root = find_repository_root()
    try:
        bundle = find_bundle(root, study, bundle_name)
        work_dir = run_bundle(root, bundle, profile)
    except (StudyError, ExecutionError) as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXECUTION) from error
    _emit(ctx, {"ok": True, "work_dir": str(work_dir)}, title="Execution complete")


@execution_app.command("destroy")
def execution_destroy(
    ctx: typer.Context,
    study: Annotated[str, typer.Argument()],
    bundle_name: Annotated[str, typer.Argument()],
) -> None:
    """Idempotently destroy the latest resources for a bundle."""
    root = find_repository_root()
    try:
        bundle = find_bundle(root, study, bundle_name)
        base = root / ".atlas" / "work" / bundle.study_root.parent.name / bundle.root.name
        candidates = sorted((path for path in base.glob("*") if path.is_dir()), reverse=True)
        work_dir = candidates[0] if candidates else base / "cleanup"
        work_dir.mkdir(parents=True, exist_ok=True)
        destroy_bundle(bundle, work_dir)
    except (StudyError, ExecutionError) as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXECUTION) from error
    _emit(ctx, {"ok": True, "work_dir": str(work_dir)}, title="Execution resources destroyed")


@evidence_app.command("validate")
def evidence_validate(
    ctx: typer.Context,
    draft_run: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Validate run schemas, checksums, and actual Arrow column contracts."""
    report = validate_evidence(find_repository_root(), draft_run)
    _emit(ctx, report.as_dict(), title="Evidence validation")
    if not report.ok:
        raise typer.Exit(EXIT_INTEGRITY)


@evidence_app.command("promote")
def evidence_promote(
    ctx: typer.Context,
    draft_run: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    run_id: Annotated[str, typer.Option("--run-id")],
) -> None:
    """Promote a valid draft into a new immutable accepted run directory."""
    root = find_repository_root()
    try:
        destination = promote_evidence(root, draft_run, run_id)
    except (ValueError, FileExistsError) as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_INTEGRITY) from error
    _emit(
        ctx,
        {"ok": True, "path": repository_relative(destination, root)},
        title="Evidence promoted",
    )


@app.command("compare")
def compare(
    ctx: typer.Context,
    experiment: Annotated[str | None, typer.Argument(help="Experiment ID or slug.")] = None,
    all_experiments: Annotated[
        bool, typer.Option("--all", help="Compare all experiments with eligible accepted runs.")
    ] = False,
) -> None:
    """Generate controlled effects and paired-bootstrap confidence intervals."""
    if not all_experiments and experiment is None:
        raise typer.BadParameter("Provide an experiment or use --all")
    root = find_repository_root()
    try:
        outputs = (
            compare_all(root)
            if all_experiments
            else compare_experiment(root, str(experiment))
        )
    except ComparisonError as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_INTEGRITY) from error
    _emit(
        ctx,
        {"ok": True, "comparisons": [repository_relative(path, root) for path in outputs]},
        title="Comparison complete",
    )


def _validate_artifact_command(ctx: typer.Context, path: Path, title: str) -> None:
    report = Validator(find_repository_root()).validate_path(path)
    _emit(ctx, report.as_dict(), title=title)
    _exit_for_report(report.ok)


@finding_app.command("validate")
def finding_validate(
    ctx: typer.Context,
    finding: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate a finding artifact before review."""
    _validate_artifact_command(ctx, finding, "Finding validation")


@decision_app.command("validate")
def decision_validate(
    ctx: typer.Context,
    decision: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Validate a deployment decision artifact before review."""
    _validate_artifact_command(ctx, decision, "Decision validation")


@cache_app.command("inspect")
def cache_inspect(ctx: typer.Context) -> None:
    """Report shared cache size without reading model content."""
    payload = {"ok": True, **inspect_cache(find_repository_root() / ".atlas" / "cache")}
    _emit(ctx, payload, title="Cache inspection")


@cache_app.command("prune")
def cache_prune(
    ctx: typer.Context,
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete cached artifacts without an interactive prompt.")
    ] = False,
) -> None:
    """Delete only the repository's recoverable shared artifact cache."""
    root = find_repository_root()
    cache_root = root / ".atlas" / "cache"
    before = inspect_cache(cache_root)
    _emit(ctx, {"ok": True, **before}, title="Cache prune plan")
    if before["files"] and not yes and not typer.confirm("Delete these recoverable cache files?"):
        raise typer.Abort()
    result = prune_cache(cache_root)
    _emit(ctx, {"ok": True, **result}, title="Cache pruned")


@graph_app.command("build")
def graph_build(
    ctx: typer.Context,
    study: Annotated[str | None, typer.Argument(help="Study ID or slug.")] = None,
    all_studies: Annotated[
        bool, typer.Option("--all", help="Build global and every per-study projection.")
    ] = False,
) -> None:
    """Compile deterministic graph JSON from canonical artifacts."""
    if all_studies and study:
        raise typer.BadParameter("Provide a study or --all, not both")
    root = find_repository_root()
    try:
        result = GraphCompiler(root).build(None if all_studies or study is None else study)
    except GraphError as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_INTEGRITY) from error
    payload = result.as_dict()
    payload["path"] = repository_relative(result.root, root)
    _emit(ctx, payload, title="Evidence graph built")


@graph_app.command("serve")
def graph_serve(
    study: Annotated[str | None, typer.Argument(help="Study directory slug.")] = None,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the local Atlas in the default browser.")
    ] = False,
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
) -> None:
    """Serve the same static site used by GitHub Pages."""
    root = find_repository_root()
    try:
        serve_site(root / "build" / "site", study=study, port=port, open_browser=open_browser)
    except FileNotFoundError as error:
        Console(stderr=True).print(f"[red]{error}[/]")
        raise typer.Exit(EXIT_EXECUTION) from error
