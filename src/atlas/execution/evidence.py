from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.identities import next_identifier
from atlas.metrics import validate_result_tables
from atlas.utilities.serialization import load_data, yaml_writer
from atlas.validation import Validator

RUN_ID = re.compile(r"^R[0-9]{4}$")
REQUIRED_FILES = (
    "run.yaml",
    "environment.json",
    "artifacts.yaml",
    "metrics/requests.parquet",
    "metrics/samples.parquet",
    "metrics/summary.json",
    "quality/results.json",
    "outputs/responses.jsonl",
    "logs/README.md",
    "checksums.sha256",
)


@dataclass(frozen=True)
class EvidenceReport:
    path: Path
    run_id: str | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": str(self.path),
            "run_id": self.run_id,
            "errors": list(self.errors),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    errors = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            digest, relative = line.split(maxsplit=1)
        except ValueError:
            errors.append(f"{path}:{number}: malformed checksum line")
            continue
        relative = relative.lstrip("*")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"{path}:{number}: invalid SHA-256 digest")
        if relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"{path}:{number}: unsafe checksum path {relative}")
            continue
        values[relative] = digest
    return values, errors


def validate_evidence(root: Path, draft: Path) -> EvidenceReport:
    draft = draft.resolve()
    errors = [
        f"Missing required evidence file: {relative}"
        for relative in REQUIRED_FILES
        if not (draft / relative).is_file()
    ]
    run_id = None
    run_path = draft / "run.yaml"
    if run_path.is_file():
        report = Validator(root).validate_path(run_path)
        errors.extend(f"{issue.path}{issue.location}: {issue.message}" for issue in report.errors)
        run = load_data(run_path)
        if isinstance(run, dict):
            run_id = run.get("id") if isinstance(run.get("id"), str) else None
            if run.get("outcome") != "complete":
                errors.append("Only complete runs can be promoted")
            quality = run.get("quality", {})
            if not isinstance(quality, dict) or quality.get("passed") is not True:
                errors.append("The required quality gate did not pass")
    errors.extend(validate_result_tables(draft / "metrics"))
    checksum_path = draft / "checksums.sha256"
    if checksum_path.is_file():
        expected, checksum_errors = _manifest(checksum_path)
        errors.extend(checksum_errors)
        for relative, digest in expected.items():
            candidate = draft / relative
            if not candidate.is_file():
                errors.append(f"Checksum references missing file: {relative}")
            elif _sha256(candidate) != digest:
                errors.append(f"Checksum mismatch: {relative}")
        for relative in REQUIRED_FILES:
            if relative != "checksums.sha256" and relative not in expected:
                errors.append(f"Required file absent from checksum manifest: {relative}")
    return EvidenceReport(draft, run_id, tuple(errors))


def _experiment_directory(root: Path, reference: str) -> Path:
    match = re.fullmatch(r"atlas://experiment/(E[0-9]{4})@v[1-9][0-9]*", reference)
    if not match:
        raise ValueError(f"Invalid experiment reference: {reference}")
    matches = list((root / "studies").glob(f"S*-*/v*/experiments/{match.group(1)}"))
    if len(matches) != 1:
        raise ValueError(f"Expected one experiment for {reference}; found {len(matches)}")
    return matches[0]


def _rewrite_run_identity(path: Path, run_id: str) -> None:
    run_path = path / "run.yaml"
    run = load_data(run_path)
    if not isinstance(run, dict):
        raise ValueError("Run record must be an object")
    run["id"] = run_id
    run["slug"] = f"run-{run_id.lower()}"
    run["title"] = f"Run {run_id}"
    with run_path.open("w") as stream:
        yaml_writer().dump(run, stream)

    manifest_paths = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.name != "checksums.sha256"
    )
    lines = [
        f"{_sha256(candidate)}  {candidate.relative_to(path).as_posix()}"
        for candidate in manifest_paths
    ]
    (path / "checksums.sha256").write_text("\n".join(lines) + "\n")


def promote_evidence(root: Path, draft: Path, run_id: str | None = None) -> Path:
    report = validate_evidence(root, draft)
    if not report.ok:
        raise ValueError("Draft evidence is invalid: " + "; ".join(report.errors))
    run = load_data(draft / "run.yaml")
    if not isinstance(run, dict):
        raise ValueError("Run record must be an object")
    allocated = run_id or next_identifier(root, "run")
    if not RUN_ID.fullmatch(allocated):
        raise ValueError(f"Invalid run ID: {allocated}")
    if run_id is not None and report.run_id not in {run_id, "R0000"}:
        raise ValueError(f"Run record ID {report.run_id} does not match requested {run_id}")
    experiment = run.get("experiment")
    if not isinstance(experiment, str):
        raise ValueError("Run record has no experiment reference")
    destination = _experiment_directory(root, experiment) / "runs" / allocated
    if destination.exists():
        raise FileExistsError(f"Accepted evidence is immutable: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{allocated}.promoting")
    if temporary.exists():
        raise FileExistsError(f"Stale promotion directory exists: {temporary}")
    try:
        shutil.copytree(draft, temporary)
        if report.run_id != allocated:
            _rewrite_run_identity(temporary, allocated)
        rewritten = validate_evidence(root, temporary)
        if not rewritten.ok:
            raise ValueError("Promoted evidence became invalid: " + "; ".join(rewritten.errors))
        temporary.replace(destination)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination
