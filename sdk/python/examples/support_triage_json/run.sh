#!/bin/bash
set -e

VENV_PATH=".venv"

# Parse arguments
LOCAL_INSTALL=false
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l) LOCAL_INSTALL=true; shift ;;
        *) PASSTHROUGH_ARGS+=("$1"); shift ;;
    esac
done

echo "--- Support Triage JSON Demo Runner ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create venv
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
fi

# Install (PyPI by default, local with --local flag)
if [ "$LOCAL_INSTALL" = true ]; then
    uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../..[litellm]"
else
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# Run
"$VENV_PATH/bin/python" -m support_triage_json.main "${PASSTHROUGH_ARGS[@]}"
