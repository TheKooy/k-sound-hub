#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Compatibility wrapper only.
# The old script name must never start the obsolete V1 profile/runtime.
exec "$REPO_DIR/scripts/start_ksound_hub_v2.sh" "$@"
