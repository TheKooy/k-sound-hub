#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/../.."

PY="$PWD/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

exec "$PY" "$PWD/tools/ui_preview/glass_mixer_preview_v13.py"
