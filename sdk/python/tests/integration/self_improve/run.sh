#!/bin/bash
set -e

VENV_PATH=".venv"
LIVE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --live)
            LIVE=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

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
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../flatmachines_cli"
uv pip install --python "$VENV_PATH/bin/python" pytest pytest-asyncio

if [ "$LIVE" = true ]; then
    echo "Running self-improve integration tests (including live tests)..."
    echo "WARNING: --live hits real Codex API and may incur cost."
    "$VENV_PATH/bin/python" -m pytest -q -s test_self_improve_live.py --live
else
    echo "Running self-improve integration tests (live tests skipped)..."
    "$VENV_PATH/bin/python" -m pytest -q test_self_improve_live.py
fi
