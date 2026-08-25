from __future__ import annotations

import os
from pathlib import Path


class RepositoryNotFoundError(RuntimeError):
    """Raised when no Atlas repository can be found."""


def is_repository_root(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (
        path / "reference" / "schemas" / "v1"
    ).is_dir()


def find_repository_root(start: Path | None = None) -> Path:
    configured = os.environ.get("ATLAS_REPOSITORY")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append((start or Path.cwd()).resolve())
    candidates.append(Path(__file__).resolve().parents[3])

    for candidate in candidates:
        for path in (candidate, *candidate.parents):
            if is_repository_root(path):
                return path.resolve()
    raise RepositoryNotFoundError(
        "No Atlas repository found. Run inside the repository or set ATLAS_REPOSITORY."
    )


def repository_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
