from __future__ import annotations

from pathlib import Path

from atlas.validation import Validator


def test_targeted_strict_validation_uses_repository_wide_identity_index() -> None:
    root = Path(__file__).resolve().parents[2]
    target = (
        root / "studies" / "S001-cpu-interactive-chat" / "v1" / "configurations" / "CFG001.yaml"
    )

    report = Validator(root).validate_path(target, strict=True)

    assert report.ok, report.issues
    assert report.checked_files == 1
