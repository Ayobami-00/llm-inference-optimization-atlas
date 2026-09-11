#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${ATLAS_S004_DEPENDENCY_PATH:-/workspace/atlas-deps}:${ATLAS_REPOSITORY_ROOT:?ATLAS_REPOSITORY_ROOT is required}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${ATLAS_PYTHON_BIN:-python}" -m atlas.studies.runners.s004_lifecycle destroy \
  --profile "${ATLAS_PROFILE:-quick}" \
  --work-dir "${ATLAS_WORK_DIR:?ATLAS_WORK_DIR is required}"
