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

echo "--- Tool Loop Demo Runner (Python) ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if ! command -v uv &> /dev/null; then
  echo "❌ uv is not installed."
  exit 1
fi

if [ ! -d "$VENV_PATH" ]; then
  uv venv "$VENV_PATH"
fi

if [ "$LOCAL_INSTALL" = true ]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
  uv pip install --python "$VENV_PATH/bin/python" -e "$REPO_ROOT/sdk/python/flatagents[litellm]"
else
  uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

"$VENV_PATH/bin/python" -m flatagent_tool_loop.main "${PASSTHROUGH_ARGS[@]}"
