#!/usr/bin/env bash
set -euo pipefail

# Keep this file only when the bundle starts a service or allocates a resource.
# It must return only after the resource is ready or a bounded health check fails.
exit 0
