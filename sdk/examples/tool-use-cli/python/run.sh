#!/bin/bash
set -e

# --- Configuration ---
VENV_PATH=".venv"

# --- Parse Arguments ---
LOCAL_INSTALL=false
STANDALONE=false
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --standalone|-s)
            STANDALONE=true
            PASSTHROUGH_ARGS+=("--standalone")
            shift
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

# --- Script Logic ---
echo "--- Tool Use CLI Runner ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

find_project_root() {
    local dir="$1"
    while [[ "$dir" != "/" ]]; do
        if [[ -e "$dir/.git" ]]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo "Error: Could not find project root (no .git found)" >&2
    return 1
}

PROJECT_ROOT="$(find_project_root "$SCRIPT_DIR")"
FLATAGENTS_SDK_PATH="$PROJECT_ROOT/sdk/python/flatagents"
FLATMACHINES_SDK_PATH="$PROJECT_ROOT/sdk/python/flatmachines"

echo "📁 Project root: $PROJECT_ROOT"

cd "$SCRIPT_DIR"

# 1. Create Virtual Environment
echo "Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "Virtual environment already exists."
fi

# 2. Install Dependencies
echo "Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    echo "  - Installing from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH[flatagents]"
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH[litellm]"
else
    echo "  - Installing from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatmachines[flatagents]"
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

echo "  - Installing tool_use_cli package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# 3. Run
echo "Running..."
echo "---"
"$VENV_PATH/bin/python" -m tool_use_cli.main "${PASSTHROUGH_ARGS[@]}"
echo "---"
echo "Done!"
