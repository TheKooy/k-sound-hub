#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

PY="$PWD/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$PY" -m ksound_hub.glass_app "$@"
