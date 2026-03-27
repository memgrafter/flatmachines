#!/bin/bash
set -e

LOCAL_INSTALL=false
TEST_ARGS=()
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --local|-l)
      LOCAL_INSTALL=true
      shift
      ;;
    --test-cache|--test-fanout-cache)
      TEST_ARGS+=("$1")
      shift
      ;;
    -h|--help)
      SHOW_HELP=true
      shift
      ;;
    *)
      echo "❌ Unknown flag: $1"
      echo "Usage: $0 [--local|-l] [--test-cache|--test-fanout-cache] [--help]"
      exit 1
      ;;
  esac
done

if [ ${#TEST_ARGS[@]} -eq 0 ] && [ "$SHOW_HELP" = false ]; then
  TEST_ARGS=("--test-cache")
fi

echo "--- Codex CLI Cache Demo (JS) ---"

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
  echo "Error: Could not find project root" >&2
  return 1
}

PROJECT_ROOT="$(find_project_root "$SCRIPT_DIR")"
JS_SDK_PATH="$PROJECT_ROOT/sdk/js"

cd "$SCRIPT_DIR"

if ! command -v node &> /dev/null; then
  echo "❌ Node.js is not installed."
  exit 1
fi
if ! command -v npm &> /dev/null; then
  echo "❌ npm is not installed."
  exit 1
fi
if ! command -v codex &> /dev/null; then
  echo "❌ 'codex' CLI not found on PATH"
  exit 1
fi

if [ "$LOCAL_INSTALL" = true ]; then
  cd "$JS_SDK_PATH"
  npm run build
  cd "$SCRIPT_DIR"
  npm pkg set dependencies.@memgrafter/flatmachines="file:../../../js/packages/flatmachines"
else
  npm pkg set dependencies.@memgrafter/flatmachines="^2.5.0"
fi

npm install
npm run build

if [ "$SHOW_HELP" = true ]; then
  node dist/codex_cli_example/main.js --help
else
  node dist/codex_cli_example/main.js "${TEST_ARGS[@]}"
fi
