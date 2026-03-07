#!/bin/bash
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
    return 1
}

PROJECT_ROOT="$(find_project_root "$SCRIPT_DIR")"
FLATAGENTS_SDK_PATH="$PROJECT_ROOT/sdk/python/flatagents"
FLATMACHINES_SDK_PATH="$PROJECT_ROOT/sdk/python/flatmachines"

cd "$SCRIPT_DIR"

if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
fi

if [ "$LOCAL_INSTALL" = true ]; then
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH[flatagents]"
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH[litellm]"
else
    uv pip install --python "$VENV_PATH/bin/python" "flatmachines[flatagents]"
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

"$VENV_PATH/bin/python" -m clone_machine.main "${PASSTHROUGH_ARGS[@]}"
