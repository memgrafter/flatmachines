#!/bin/bash
set -e

# --- Parse Arguments ---
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

echo "--- Coding Machine CLI (JS) Runner ---"

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

echo "📁 Project root: $PROJECT_ROOT"
echo "📁 JS SDK: $JS_SDK_PATH"

cd "$SCRIPT_DIR"

# 0. Ensure Node.js and npm are installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js first."
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm first."
    exit 1
fi

# 1. Install Dependencies
echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    echo "  - Using local flatmachines SDK..."
    cd "$JS_SDK_PATH"
    npm run build
    cd "$SCRIPT_DIR"
    npm pkg set dependencies.@memgrafter/flatmachines="file:../../../js/packages/flatmachines"
else
    npm pkg set dependencies.@memgrafter/flatmachines="^2.5.0"
fi

echo "  - Installing coding_machine_cli demo package..."
npm install

# 2. Build TypeScript
echo "🏗️  Building TypeScript..."
npm run build

# 3. Run
echo "🚀 Running..."
echo "---"
node dist/tool_use_cli/main.js "${PASSTHROUGH_ARGS[@]}"
echo "---"

echo "✅ Done!"
