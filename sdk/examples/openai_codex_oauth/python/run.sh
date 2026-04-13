#!/bin/bash
set -e

VENV_PATH=".venv"
LOCAL_INSTALL=false
PASSTHROUGH_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local|-l)
      LOCAL_INSTALL=true
      shift
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        PASSTHROUGH_ARGS+=("$1")
        shift
      done
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "--- OpenAI Codex OAuth Example (Python) ---"

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
  uv pip install --python "$VENV_PATH/bin/python" -e "$REPO_ROOT/sdk/python/flatagents"
else
  uv pip install --python "$VENV_PATH/bin/python" "flatagents"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

"$VENV_PATH/bin/python" -m openai_codex_oauth_example.main "${PASSTHROUGH_ARGS[@]}"
