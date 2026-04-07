#!/bin/bash
set -e

# Let Ctrl-C propagate cleanly
trap 'echo ""; echo "Cancelled."; exit 130' INT

# --- Configuration ---
VENV_PATH=".venv"

# --- Parse Arguments ---
LOCAL_INSTALL=false
WORKING_DIR=""
STATEMENT_PARTS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        -w|--working-dir)
            WORKING_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./run.sh [options] <statement>"
            echo ""
            echo "Interprets a statement and adds it to INTERPRETATIONS.md"
            echo ""
            echo "Options:"
            echo "  -w, --working-dir DIR  Working directory (default: cwd)"
            echo "  -l, --local            Install flatmachines/flatagents from local source"
            echo "  -h, --help             Show this help"
            echo ""
            echo "Examples:"
            echo '  ./run.sh "I would like to simplify the flatmachines interface."'
            echo '  ./run.sh -w ~/myproject "What if state machines are wrong?"'
            exit 0
            ;;
        *)
            STATEMENT_PARTS+=("$1")
            shift
            ;;
    esac
done

if [ ${#STATEMENT_PARTS[@]} -eq 0 ]; then
    echo "❌ No statement provided."
    echo 'Usage: ./run.sh "Your statement here"'
    exit 1
fi

STATEMENT="${STATEMENT_PARTS[*]}"

echo "--- Interpreter Machine ---"
echo "💬 Statement: \"$STATEMENT\""

# Get the directory the script is located in
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_DIR="$SCRIPT_DIR/python"

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

# Change to the python dir for uv
cd "$PYTHON_DIR"

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
if [ ! -d "$VENV_PATH" ]; then
    echo "🔧 Creating virtual environment..."
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment exists."
fi

# 3. Install Dependencies
echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    FLATAGENTS_EXTRAS=$(grep -oE 'flatagents\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")
    FLATMACHINES_EXTRAS=$(grep -oE 'flatmachines\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")

    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH$FLATMACHINES_EXTRAS"
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH$FLATAGENTS_EXTRAS"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$PYTHON_DIR"

# 4. Build run arguments
RUN_ARGS=("$STATEMENT")

# Default working dir to the script's directory, not cwd (which is python/ after cd)
if [ -z "$WORKING_DIR" ]; then
    WORKING_DIR="$SCRIPT_DIR"
fi
RUN_ARGS+=("-w" "$WORKING_DIR")

# 5. Run
echo "🚀 Interpreting..."
echo "---"
"$VENV_PATH/bin/python" -m interpreter_machine.main "${RUN_ARGS[@]}"
echo "---"
echo "✅ Done."
