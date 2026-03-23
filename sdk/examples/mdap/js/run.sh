#!/bin/bash
set -e

# --- Parse Arguments ---
LOCAL_INSTALL=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo "--- FlatAgent MDAP Demo Runner ---"

# Get the directory the script is located in
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Establish project root by walking up to find .git
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
    echo "  - Using local flatagents SDK..."
    cd "$JS_SDK_PATH"
    npm run build
    cd "$SCRIPT_DIR"
    # Swap to local dependency
    npm pkg set dependencies.@memgrafter/flatagents="file:../../../js/packages/flatagents"
else
    # Ensure we're using the npm package
    npm pkg set dependencies.@memgrafter/flatagents="^2.5.0"
fi

echo "  - Installing mdap demo package..."
npm install

# 2. Build TypeScript
echo "🏗️  Building TypeScript..."
npm run build

# 3. Run the Demo
echo "🚀 Running demo..."
echo "---"
node dist/mdap/demo.js
echo "---"

echo "✅ Demo complete!"
