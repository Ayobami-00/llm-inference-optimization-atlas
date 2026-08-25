#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE=${ATLAS_PROFILE:-quick}
WORK_DIR=${ATLAS_WORK_DIR:-"$BUNDLE_DIR/.atlas/work"}

exec python3 "$BUNDLE_DIR/src/main.py" --profile "$PROFILE" --work-dir "$WORK_DIR"
