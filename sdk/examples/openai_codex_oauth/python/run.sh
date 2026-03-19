#!/bin/bash
set -euo pipefail

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
      PASSTHROUGH_ARGS+=("$@")
      break
      ;;
    *)
      PASSTHROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

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

if ! command -v uv &> /dev/null; then
  echo "uv is required: https://docs.astral.sh/uv/"
  exit 1
fi

if [[ ! -d "$VENV_PATH" ]]; then
  uv venv "$VENV_PATH"
fi

if [[ "$LOCAL_INSTALL" == true ]]; then
  uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_SDK_PATH"
fi

uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

export FLATAGENTS_CODEX_AUTH_FILE="$SCRIPT_DIR/config/auth.json"

if [[ ${#PASSTHROUGH_ARGS[@]} -gt 0 ]]; then
  "$VENV_PATH/bin/python" -m openai_codex_oauth_example.main "${PASSTHROUGH_ARGS[@]}"
else
  "$VENV_PATH/bin/python" -m openai_codex_oauth_example.main
fi
