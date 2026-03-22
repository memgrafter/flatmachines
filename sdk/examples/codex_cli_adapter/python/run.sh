#!/bin/bash
set -e

VENV_PATH=".venv"
LOCAL_INSTALL=false
TEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l) LOCAL_INSTALL=true; shift ;;
        --test-cache|--test-fanout-cache) TEST_ARGS+=("$1"); shift ;;
        *) shift ;;
    esac
done

# Default to --test-cache if no test flag given
if [ ${#TEST_ARGS[@]} -eq 0 ]; then
    TEST_ARGS=("--test-cache")
fi

echo "--- Codex CLI Cache Demo ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

find_project_root() {
    local dir="$1"
    while [[ "$dir" != "/" ]]; do
        if [[ -e "$dir/.git" ]]; then echo "$dir"; return 0; fi
        dir="$(dirname "$dir")"
    done
    echo "Error: Could not find project root" >&2; return 1
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

if ! command -v codex &> /dev/null; then
    echo "❌ Error: 'codex' CLI not found on PATH."
    echo "   Install Codex CLI: npm install -g @openai/codex"
    exit 1
fi

echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    FLATMACHINES_EXTRAS=$(grep -oE 'flatmachines\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")
    FLATAGENTS_EXTRAS=$(grep -oE 'flatagents\[[^]]+\]' pyproject.toml | head -1 | grep -oE '\[[^]]+\]' || echo "")
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH$FLATMACHINES_EXTRAS"
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH$FLATAGENTS_EXTRAS"
fi
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

echo "🚀 Running: ${TEST_ARGS[*]}"
echo "---"
"$VENV_PATH/bin/python" -m codex_cli_example.main "${TEST_ARGS[@]}"
echo "---"
echo "✅ Done!"
