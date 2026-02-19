#!/usr/bin/env bash
# Run the RLM v2 example
#
# Usage:
#   ./run.sh --demo
#   ./run.sh --local --demo
#   ./run.sh --file doc.txt --task "Question"
#
# By default this runner enables maximum information mode:
#   --inspect --inspect-level full --print-iterations --trace-dir ./traces

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

# Maximum information mode by default (unless caller already specifies these flags)
USER_ARGS_COUNT=${#PASSTHROUGH_ARGS[@]}

has_arg() {
    local needle="$1"
    for arg in "${PASSTHROUGH_ARGS[@]}"; do
        if [[ "$arg" == "$needle" ]]; then
            return 0
        fi
    done
    return 1
}

if ! has_arg "--inspect"; then
    PASSTHROUGH_ARGS+=("--inspect")
fi
if ! has_arg "--inspect-level"; then
    PASSTHROUGH_ARGS+=("--inspect-level" "full")
fi
if ! has_arg "--print-iterations"; then
    PASSTHROUGH_ARGS+=("--print-iterations")
fi
if ! has_arg "--trace-dir"; then
    PASSTHROUGH_ARGS+=("--trace-dir" "./traces")
fi

if [ "$USER_ARGS_COUNT" -eq 0 ]; then
    "$VENV_PATH/bin/python" -m rlm_v2.main --demo "${PASSTHROUGH_ARGS[@]}"
else
    "$VENV_PATH/bin/python" -m rlm_v2.main "${PASSTHROUGH_ARGS[@]}"
fi
