#!/bin/bash
set -e

# --- Configuration ---
VENV_PATH=".venv"

# --- Parse Arguments ---
LOCAL_INSTALL=false
TASK=""
MULTI_STATE=false
WORKING_DIR=""
MACHINE_CONFIG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --multi-state)
            MULTI_STATE=true
            shift
            ;;
        --with-refs)
            MACHINE_CONFIG="machine_with_refs.yml"
            shift
            ;;
        -p|--print)
            TASK="$2"
            shift 2
            ;;
        -w|--working-dir)
            WORKING_DIR="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# --- Script Logic ---
echo "--- Claude Code Adapter Demo Runner ---"

# Get the directory the script is located in
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

echo "📁 Project root: $PROJECT_ROOT"
echo "📁 FlatAgents SDK: $FLATAGENTS_SDK_PATH"
echo "📁 FlatMachines SDK: $FLATMACHINES_SDK_PATH"

# Change to the script's directory so `uv` can find pyproject.toml
cd "$SCRIPT_DIR"

# 0. Ensure uv is installed
if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 1. Ensure claude CLI is installed
if ! command -v claude &> /dev/null; then
    echo "❌ Error: 'claude' CLI not found on PATH."
    echo "   Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi

# 2. Create Virtual Environment
echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

# 3. Install Dependencies
echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    FLATAGENTS_EXTRAS=$(grep -oE 'flatagents\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")
    FLATMACHINES_EXTRAS=$(grep -oE 'flatmachines\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")

    echo "  - Installing flatmachines from local source${FLATMACHINES_EXTRAS}..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH$FLATMACHINES_EXTRAS"
    echo "  - Installing flatagents from local source${FLATAGENTS_EXTRAS}..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH$FLATAGENTS_EXTRAS"
else
    echo "  - Installing from PyPI (deps from pyproject.toml)..."
fi

echo "  - Installing claude-code-example package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# 4. Build run arguments
RUN_ARGS=()
if [ -n "$TASK" ]; then
    RUN_ARGS+=("-p" "$TASK")
else
    RUN_ARGS+=("-p" "Say hello and list the files in the current directory")
fi

if [ "$MULTI_STATE" = true ]; then
    RUN_ARGS+=("--multi-state")
fi

if [ -n "$MACHINE_CONFIG" ]; then
    RUN_ARGS+=("--config" "$MACHINE_CONFIG")
fi

if [ -n "$WORKING_DIR" ]; then
    RUN_ARGS+=("-w" "$WORKING_DIR")
fi

# 5. Run the Demo
echo "🚀 Running demo..."
echo "---"
"$VENV_PATH/bin/python" -m claude_code_example.main "${RUN_ARGS[@]}"
echo "---"

echo "✅ Demo complete!"
