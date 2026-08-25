#!/usr/bin/env bash
set -euo pipefail

exec uv run python -m atlas.studies.runners.s002 \
  --profile "${ATLAS_PROFILE:-quick}" \
  --work-dir "${ATLAS_WORK_DIR:?ATLAS_WORK_DIR is required}"
