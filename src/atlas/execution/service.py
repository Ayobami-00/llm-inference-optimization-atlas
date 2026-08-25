from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.schemas import SchemaCatalog
from atlas.studies import find_study
from atlas.utilities.serialization import load_data


class ExecutionError(RuntimeError):
    """An execution lifecycle operation failed."""


@dataclass(frozen=True)
class Bundle:
    study_root: Path
    root: Path
    data: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def list_bundles(root: Path, study: str) -> list[str]:
    study_root = find_study(root, study)
    execution_root = study_root / "execution"
    if not execution_root.exists():
        return []
    return sorted(
        path.name for path in execution_root.iterdir() if (path / "execution.yaml").is_file()
    )


def find_bundle(root: Path, study: str, name: str) -> Bundle:
    study_root = find_study(root, study)
    bundle_root = study_root / "execution" / name
    manifest = bundle_root / "execution.yaml"
    if not manifest.is_file():
        raise ExecutionError(f"No execution bundle {name!r} in {study_root.parent.name}")
    data = load_data(manifest)
    if not isinstance(data, dict):
        raise ExecutionError(f"Execution manifest must be an object: {manifest}")
    schema_root = root / "reference" / "schemas" / "v1"
    catalog = SchemaCatalog(schema_root)
    schema_identifier = data.get("$schema")
    if not isinstance(schema_identifier, str):
        raise ExecutionError(f"Execution manifest has no $schema: {manifest}")
    errors = catalog.validate(data, schema_identifier)
    if errors:
        message = "; ".join(f"{error.path}: {error.message}" for error in errors)
        raise ExecutionError(f"Invalid execution manifest: {message}")
    _check_platform(data)
    return Bundle(study_root, bundle_root, data)


def _check_platform(data: dict[str, Any]) -> None:
    operating_system = platform.system().lower()
    os_name = {"darwin": "macos", "linux": "linux", "windows": "windows-wsl"}.get(
        operating_system, operating_system
    )
    machine = platform.machine().lower()
    architecture = "aarch64" if machine in {"arm64", "aarch64"} else machine
    supported = any(
        item.get("os") == os_name and item.get("architecture") == architecture
        for item in data.get("platforms", [])
        if isinstance(item, dict)
    )
    if not supported:
        raise ExecutionError(f"Bundle does not support {os_name}/{architecture}")


def bundle_plan(bundle: Bundle, cache_root: Path) -> dict[str, Any]:
    artifacts = []
    total = 0
    for artifact in bundle.data.get("artifacts", []):
        expected = int(artifact["size_bytes"])
        total += expected
        destination = cache_root / "artifacts" / artifact["sha256"] / artifact["name"]
        artifacts.append(
            {
                "name": artifact["name"],
                "size_bytes": expected,
                "license": artifact["license"],
                "url": artifact["url"],
                "cached": destination.is_file() and _sha256(destination) == artifact["sha256"],
            }
        )
    return {"artifacts": artifacts, "total_size_bytes": total}


def prepare_bundle(bundle: Bundle, cache_root: Path) -> list[Path]:
    prepared = []
    for artifact in bundle.data.get("artifacts", []):
        destination = cache_root / "artifacts" / artifact["sha256"] / artifact["name"]
        if destination.is_file() and _sha256(destination) == artifact["sha256"]:
            prepared.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".partial")
        temporary.unlink(missing_ok=True)
        try:
            with (
                urllib.request.urlopen(artifact["url"], timeout=60) as response,
                temporary.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
            if temporary.stat().st_size != artifact["size_bytes"]:
                raise ExecutionError(
                    f"Size mismatch for {artifact['name']}: expected {artifact['size_bytes']}, "
                    f"received {temporary.stat().st_size}"
                )
            actual = _sha256(temporary)
            if actual != artifact["sha256"]:
                raise ExecutionError(
                    f"Checksum mismatch for {artifact['name']}: expected {artifact['sha256']}, "
                    f"received {actual}"
                )
            temporary.replace(destination)
            prepared.append(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return prepared


def _entrypoint(bundle: Bundle, name: str, work_dir: Path, profile: str) -> int:
    relative = bundle.data.get("entrypoints", {}).get(name)
    if not relative:
        return 0
    script = (bundle.root / relative).resolve()
    try:
        script.relative_to(bundle.root.resolve())
    except ValueError as error:
        raise ExecutionError(f"Entrypoint escapes bundle root: {relative}") from error
    if not script.is_file():
        raise ExecutionError(f"Missing {name} entrypoint: {script}")
    environment = os.environ.copy()
    environment.update(
        {
            "ATLAS_PROFILE": profile,
            "ATLAS_WORK_DIR": str(work_dir),
            "ATLAS_BUNDLE_DIR": str(bundle.root),
            "ATLAS_CACHE_DIR": str(bundle.study_root.parents[2] / ".atlas" / "cache"),
            "ATLAS_REPOSITORY_ROOT": str(bundle.study_root.parents[2]),
        }
    )
    command = [str(script)] if os.access(script, os.X_OK) else ["bash", str(script)]
    timeout_key = "cleanup_seconds" if name == "destroy" else "run_seconds"
    timeout = int(bundle.data.get("timeouts", {}).get(timeout_key, 1800))
    try:
        result = subprocess.run(
            command,
            cwd=bundle.root,
            env=environment,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ExecutionError(f"{name} timed out after {timeout} seconds") from error
    return result.returncode


def default_work_dir(root: Path, bundle: Bundle) -> Path:
    study_name = bundle.study_root.parent.name
    return root / ".atlas" / "work" / study_name / bundle.root.name / _timestamp()


def start_bundle(root: Path, bundle: Bundle, profile: str = "quick") -> Path:
    work_dir = default_work_dir(root, bundle)
    work_dir.mkdir(parents=True, exist_ok=False)
    code = _entrypoint(bundle, "start", work_dir, profile)
    if code:
        raise ExecutionError(f"start failed with exit code {code}")
    return work_dir


def destroy_bundle(bundle: Bundle, work_dir: Path, profile: str = "quick") -> None:
    code = _entrypoint(bundle, "destroy", work_dir, profile)
    if code:
        raise ExecutionError(f"destroy failed with exit code {code}")


def run_bundle(root: Path, bundle: Bundle, profile: str) -> Path:
    if profile not in {"quick", "full"}:
        raise ExecutionError("Profile must be quick or full")
    work_dir = default_work_dir(root, bundle)
    work_dir.mkdir(parents=True, exist_ok=False)
    started = False
    run_error: BaseException | None = None
    try:
        if bundle.data.get("entrypoints", {}).get("start"):
            code = _entrypoint(bundle, "start", work_dir, profile)
            if code:
                raise ExecutionError(f"start failed with exit code {code}")
            started = True
        code = _entrypoint(bundle, "run", work_dir, profile)
        if code:
            raise ExecutionError(f"run failed with exit code {code}; draft retained at {work_dir}")
    except BaseException as error:
        run_error = error
    finally:
        if started or bundle.data.get("cleanup", {}).get("required"):
            try:
                destroy_bundle(bundle, work_dir, profile)
            except ExecutionError:
                if run_error is None:
                    raise
    if run_error is not None:
        raise run_error
    return work_dir
