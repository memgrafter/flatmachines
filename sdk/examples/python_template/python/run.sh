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

echo "--- Python Template Demo Runner ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Establish project root by walking up to find .git
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

echo "Project root: $PROJECT_ROOT"
echo "FlatAgents SDK: $FLATAGENTS_SDK_PATH"
echo "FlatMachines SDK: $FLATMACHINES_SDK_PATH"

cd "$SCRIPT_DIR"

# Ensure uv is installed
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Create venv
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment..."
    uv venv "$VENV_PATH"
else
    echo "Virtual environment already exists."
fi

# Install dependencies
echo "Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    FLATAGENTS_EXTRAS=$(grep -oE 'flatagents\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")
    FLATMACHINES_EXTRAS=$(grep -oE 'flatmachines\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")

    echo "  Installing flatmachines from local source${FLATMACHINES_EXTRAS}..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH$FLATMACHINES_EXTRAS"
    echo "  Installing flatagents from local source${FLATAGENTS_EXTRAS}..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH$FLATAGENTS_EXTRAS"
else
    echo "  Installing from PyPI (deps from pyproject.toml)..."
fi

echo "  Installing python-template package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# Run
echo "Running demo..."
echo "---"
"$VENV_PATH/bin/python" -m python_template.main "${PASSTHROUGH_ARGS[@]}"
echo "---"
echo "Demo complete!"
