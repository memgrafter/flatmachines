#!/bin/bash
set -e

# --- Configuration ---
VENV_PATH=".venv"

# --- Parse Arguments ---
LOCAL_INSTALL=false
# Debug is ON by default. Disable with CODING_MACHINE_DISCORD_DEBUG=false
DEBUG_MODE="${CODING_MACHINE_DISCORD_DEBUG:-true}"
COMMAND="run"
PY_MODULE="tool_use_discord.main"
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        run|restart)
            COMMAND="$1"
            shift
            ;;
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --debug|-d)
            DEBUG_MODE=true
            shift
            ;;
        --no-debug)
            DEBUG_MODE=false
            shift
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

# --- Script Logic ---
echo "--- Coding Machine Discord Runner ---"

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

if [[ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]]; then
    PASSTHROUGH_ARGS=("all" "--db-path" "../data/coding_machine_discord.sqlite")
fi

if [[ "$COMMAND" == "restart" ]]; then
    echo "Restart requested: stopping existing $PY_MODULE processes..."
    pkill -f "$PY_MODULE" || true
    sleep 1
fi

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

echo "  - Installing tool_use_discord package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# 3. Run
echo "Running..."
echo "---"
if [[ "${DEBUG_MODE,,}" == "0" || "${DEBUG_MODE,,}" == "false" || "${DEBUG_MODE,,}" == "no" || "${DEBUG_MODE,,}" == "off" ]]; then
    echo "Debug logging disabled"
    PYTHONUNBUFFERED=1 "$VENV_PATH/bin/python" -u -m "$PY_MODULE" "${PASSTHROUGH_ARGS[@]}"
else
    echo "Debug logging enabled (LOG_LEVEL=DEBUG, FLATAGENTS_LOG_LEVEL=DEBUG)"
    LOG_LEVEL=DEBUG FLATAGENTS_LOG_LEVEL=DEBUG PYTHONUNBUFFERED=1 "$VENV_PATH/bin/python" -u -m "$PY_MODULE" "${PASSTHROUGH_ARGS[@]}"
fi
echo "---"
echo "Done!"
