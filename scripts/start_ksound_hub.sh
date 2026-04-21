#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"

cd "$REPO_DIR"

if [[ -x "$VENV_DIR/bin/ksound-hub" ]]; then
  exec "$VENV_DIR/bin/ksound-hub"
fi

if [[ -x "$VENV_DIR/bin/python" ]]; then
  export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
  exec "$VENV_DIR/bin/python" -m ksound_hub.app
fi

export PYTHONPATH="$REPO_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m ksound_hub.app
