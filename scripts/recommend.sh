#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${JQUANTS_API_KEY:-}" ]]; then
  echo "ERROR: set JQUANTS_API_KEY first." >&2
  echo "Example: export JQUANTS_API_KEY='your_api_key_here'" >&2
  exit 2
fi

if [[ -z "${PYTHON_BIN:-}" ]]; then
  VENV_PYTHON="$ROOT/.venv/bin/python"
  BUNDLED_PYTHON="/Users/unbearablefate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  if [[ -x "$VENV_PYTHON" ]]; then
    PYTHON_BIN="$VENV_PYTHON"
  elif [[ -x "$BUNDLED_PYTHON" ]]; then
    PYTHON_BIN="$BUNDLED_PYTHON"
  else
    PYTHON_BIN="python3"
  fi
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON_BIN" -m rakuten_quant.cli recommend "$@"
