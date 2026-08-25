from __future__ import annotations

SCHEMA_BASE = "https://ayobami-00.github.io/llm-inference-optimization-atlas/schemas/v1/"
ATLAS_REFERENCE_PREFIX = "atlas://"

EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_EXECUTION = 4
EXIT_INTEGRITY = 5
EXIT_EXTERNAL = 6

IGNORED_DIRECTORY_NAMES = {
    ".atlas",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "node_modules",
    "tests",
    "__pycache__",
}

TEMPLATE_PARTS = ("reference", "templates")
