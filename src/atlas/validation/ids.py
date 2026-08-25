from __future__ import annotations

from pathlib import Path

from atlas.validation import ValidationReport, Validator


def check_ids(root: Path) -> ValidationReport:
    return Validator(root).validate_path(root, strict=True)
