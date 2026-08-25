from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def inspect_cache(cache_root: Path) -> dict[str, Any]:
    files = (
        [path for path in cache_root.rglob("*") if path.is_file()]
        if cache_root.exists()
        else []
    )
    by_area: dict[str, dict[str, int]] = {}
    for path in files:
        relative = path.relative_to(cache_root)
        area = relative.parts[0] if relative.parts else "root"
        summary = by_area.setdefault(area, {"files": 0, "bytes": 0})
        summary["files"] += 1
        summary["bytes"] += path.stat().st_size
    return {
        "path": str(cache_root),
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "areas": dict(sorted(by_area.items())),
    }


def prune_cache(cache_root: Path) -> dict[str, int]:
    before = inspect_cache(cache_root)
    if cache_root.exists():
        resolved = cache_root.resolve()
        if resolved.name != "cache" or resolved.parent.name != ".atlas":
            raise ValueError(f"Refusing to prune unexpected cache path: {resolved}")
        for child in cache_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    return {"removed_files": int(before["files"]), "removed_bytes": int(before["bytes"])}
