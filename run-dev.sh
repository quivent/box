#!/usr/bin/env bash
# Run boxd locally. Creates .venv on first run (uv if present, else venv+pip).
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv
    uv pip install --python .venv/bin/python -r requirements.txt
  else
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
  fi
fi

exec .venv/bin/python -m boxd
