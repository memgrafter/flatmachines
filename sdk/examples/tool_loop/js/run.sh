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

echo "--- Tool Loop Demo Runner (JS) ---"

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
  echo "  - Using local flatagents SDK..."
  cd "$JS_SDK_PATH"
  npm run build
  cd "$SCRIPT_DIR"
  npm pkg set dependencies.@memgrafter/flatagents="file:../../../js/packages/flatagents"
else
  npm pkg set dependencies.@memgrafter/flatagents="^2.5.0"
fi

echo "📦 Installing dependencies..."
npm install

echo "🏗️  Building TypeScript..."
npm run build

echo "🚀 Running demo..."
node dist/tool_loop/main.js "${PASSTHROUGH_ARGS[@]}"

echo "✅ Done!"
