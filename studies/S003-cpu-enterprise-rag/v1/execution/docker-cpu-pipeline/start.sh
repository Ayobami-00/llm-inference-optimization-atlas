#!/usr/bin/env bash
set -euo pipefail

exec uv run python -m atlas.studies.runners.s003_lifecycle start \
  --bundle-dir "${ATLAS_BUNDLE_DIR:?ATLAS_BUNDLE_DIR is required}"
