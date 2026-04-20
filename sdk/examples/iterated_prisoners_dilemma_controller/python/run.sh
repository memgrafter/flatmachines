#!/bin/bash
set -e

VENV_PATH=".venv"
LOCAL_INSTALL=false
DEBUG=false
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --local|-l)
      LOCAL_INSTALL=true
      shift
      ;;
    --debug|-d)
      DEBUG=true
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

if ! command -v uv &> /dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -d "$VENV_PATH" ]; then
  uv venv "$VENV_PATH"
fi

if [ "$LOCAL_INSTALL" = true ]; then
  uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH[flatagents]"
  uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

if [ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]; then
  PASSTHROUGH_ARGS=("--rounds" "10")
fi

if [ "$DEBUG" = true ]; then
  echo "Debug enabled (LOG_LEVEL=DEBUG, FLATAGENTS_LOG_LEVEL=DEBUG, IPD_DEBUG_MESSAGES=1, IPD_DEBUG_PROMPTS=1)"
  LOG_LEVEL=DEBUG FLATAGENTS_LOG_LEVEL=DEBUG IPD_DEBUG_MESSAGES=1 IPD_DEBUG_PROMPTS=1 PYTHONUNBUFFERED=1 \
    "$VENV_PATH/bin/python" -u -m ipd_controller.main --debug "${PASSTHROUGH_ARGS[@]}"
else
  "$VENV_PATH/bin/python" -m ipd_controller.main "${PASSTHROUGH_ARGS[@]}"
fi
