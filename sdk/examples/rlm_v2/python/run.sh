#!/usr/bin/env bash
# Run the RLM v2 example
#
# Usage:
#   ./run.sh --demo
#   ./run.sh --local --demo
#   ./run.sh --file doc.txt --task "Question"

set -e

VENV_PATH=".venv"
LOCAL_INSTALL=false
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "--- RLM v2 Runner ---"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

cd "$SCRIPT_DIR"

if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    echo "  - Installing flatmachines from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH[flatagents]"
    echo "  - Installing flatagents from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH[litellm]"
else
    echo "  - Installing flatmachines from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatmachines[flatagents]"
    echo "  - Installing flatagents from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

echo "  - Installing rlm_v2 package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

if [ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]; then
    "$VENV_PATH/bin/python" -m rlm_v2.main --demo
else
    "$VENV_PATH/bin/python" -m rlm_v2.main "${PASSTHROUGH_ARGS[@]}"
fi
