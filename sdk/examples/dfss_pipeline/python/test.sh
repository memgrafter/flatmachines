#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/.venv"
PYTHON_BIN="$VENV_PATH/bin/python"

cd "$SCRIPT_DIR"

echo "=== DFSS Pipeline Test Suite ==="

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not found on PATH"
  exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
  uv venv "$VENV_PATH"
fi

uv pip install --python "$PYTHON_BIN" -e "$SCRIPT_DIR/../../../python/flatagents[litellm]"
uv pip install --python "$PYTHON_BIN" -e "$SCRIPT_DIR/../../../python/flatmachines[flatagents]"
uv pip install --python "$PYTHON_BIN" -e "$SCRIPT_DIR"
uv pip install --python "$PYTHON_BIN" pytest pytest-asyncio

"$PYTHON_BIN" -m pytest \
  tests/unit/test_dfss_*.py \
  tests/integration/test_dfss_pipeline.py \
  -q

echo "=== DFSS suite complete ==="
