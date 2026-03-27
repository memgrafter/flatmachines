#!/bin/bash
set -e

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

echo "--- Listener OS Demo Runner (JS) ---"

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

if [ "$LOCAL_INSTALL" = true ]; then
  echo "  - Using local flatmachines SDK..."
  cd "$JS_SDK_PATH"
  npm run build
  cd "$SCRIPT_DIR"
  npm pkg set dependencies.@memgrafter/flatmachines="file:../../../js/packages/flatmachines"
else
  npm pkg set dependencies.@memgrafter/flatmachines="^2.5.0"
fi

echo "📦 Installing dependencies..."
npm install

echo "🏗️  Building TypeScript..."
npm run build

if [ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]; then
  TASK_ID="demo-os-$$"

  echo "🧼 Resetting demo state..."
  node dist/listener_os/main.js reset

  echo "🅿️  Parking machine on wait_for (task_id=${TASK_ID})..."
  node dist/listener_os/main.js park --task-id "$TASK_ID"

  echo "📨 Sending signal..."
  node dist/listener_os/main.js send --task-id "$TASK_ID" --approved true --reviewer run-sh --trigger none

  echo "🚚 Dispatching pending signals..."
  node dist/listener_os/main.js dispatch-once

  echo "📊 Final status:"
  node dist/listener_os/main.js status
else
  echo "🚀 Running command..."
  node dist/listener_os/main.js "${PASSTHROUGH_ARGS[@]}"
fi

echo "✅ Done!"
