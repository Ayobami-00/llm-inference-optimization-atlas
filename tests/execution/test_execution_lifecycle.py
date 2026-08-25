from __future__ import annotations

from pathlib import Path

import pytest

from atlas.execution.service import Bundle, ExecutionError, run_bundle


def _script(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)


def test_cleanup_runs_after_execution_failure(tmp_path: Path) -> None:
    study_root = tmp_path / "studies" / "S001-test" / "v1"
    bundle_root = study_root / "execution" / "fake"
    bundle_root.mkdir(parents=True)
    _script(bundle_root / "start.sh", "touch \"$ATLAS_WORK_DIR/started\"\n")
    _script(bundle_root / "run.sh", "exit 17\n")
    _script(bundle_root / "destroy.sh", "touch \"$ATLAS_WORK_DIR/destroyed\"\n")
    bundle = Bundle(
        study_root,
        bundle_root,
        {
            "entrypoints": {
                "start": "start.sh",
                "run": "run.sh",
                "destroy": "destroy.sh",
            },
            "timeouts": {"run_seconds": 10, "cleanup_seconds": 10},
            "cleanup": {"required": True, "idempotent": True},
        },
    )

    with pytest.raises(ExecutionError, match="exit code 17"):
        run_bundle(tmp_path, bundle, "quick")

    work_dirs = list((tmp_path / ".atlas" / "work" / "S001-test" / "fake").iterdir())
    assert len(work_dirs) == 1
    assert (work_dirs[0] / "started").exists()
    assert (work_dirs[0] / "destroyed").exists()
