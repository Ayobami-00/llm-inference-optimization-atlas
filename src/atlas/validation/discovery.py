from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from atlas.constants import IGNORED_DIRECTORY_NAMES, TEMPLATE_PARTS


def is_ignored(path: Path, root: Path, *, include_templates: bool = False) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = path
    if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts):
        return True
    return not include_templates and all(part in relative.parts for part in TEMPLATE_PARTS)


def discover_data_files(
    target: Path, root: Path, *, include_templates: bool = False
) -> Iterator[Path]:
    if target.is_file():
        if target.suffix.lower() in {".json", ".yaml", ".yml"}:
            yield target
        return
    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".yaml", ".yml"}:
            continue
        if not is_ignored(path, root, include_templates=include_templates):
            yield path
