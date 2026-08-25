from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas.graph import GraphCompiler


class SiteBuildError(RuntimeError):
    """The static Atlas explorer could not be built."""


@dataclass(frozen=True)
class SiteBuild:
    path: Path
    files: int
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {"ok": True, "path": str(self.path), "files": self.files, "bytes": self.bytes}


def build_site(root: Path) -> SiteBuild:
    GraphCompiler(root).build()
    npm = shutil.which("npm")
    if not npm:
        raise SiteBuildError("npm is not installed or not on PATH")
    if not (root / "site" / "node_modules").is_dir():
        raise SiteBuildError("Frontend dependencies are absent; run `npm install --prefix site`")
    result = subprocess.run(
        [npm, "run", "build", "--prefix", "site"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise SiteBuildError((result.stderr or result.stdout).strip())
    output = root / "build" / "site"
    required = ("index.html", "404.html", "data/manifest.json", "data/graph.json")
    missing = [relative for relative in required if not (output / relative).is_file()]
    if missing:
        raise SiteBuildError(f"Static build is incomplete: {', '.join(missing)}")
    files = [path for path in output.rglob("*") if path.is_file()]
    return SiteBuild(output, len(files), sum(path.stat().st_size for path in files))
