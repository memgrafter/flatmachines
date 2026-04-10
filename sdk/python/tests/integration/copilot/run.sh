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
uv pip install --python "$VENV_PATH/bin/python" pytest pytest-asyncio httpx

if [ "$LIVE" = true ]; then
    echo "Running Copilot integration tests (including live tests)..."
    "$VENV_PATH/bin/python" -m pytest -q -s test_copilot_backend_integration.py test_copilot_oauth_live.py --live
else
    echo "Running Copilot integration tests (mocked + live tests skipped)..."
    "$VENV_PATH/bin/python" -m pytest -q test_copilot_backend_integration.py test_copilot_oauth_live.py
fi
