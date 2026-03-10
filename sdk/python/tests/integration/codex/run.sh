#!/bin/bash
set -e

VENV_PATH=".venv"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if ! command -v uv &> /dev/null; then
    echo "uv is required: https://docs.astral.sh/uv/"
    exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../flatmachines[flatagents]"
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../flatagents[litellm]"
uv pip install --python "$VENV_PATH/bin/python" pytest pytest-asyncio httpx

"$VENV_PATH/bin/python" -m pytest -q test_codex_backend_integration.py
