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

echo "--- FlatAgent Coding Agent Demo Runner ---"

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

# Ensure skills are available for codebase explorer
SKILLS_LINK="$SCRIPT_DIR/../.skills"
if [[ ! -e "$SKILLS_LINK" ]]; then
    if [[ -n "$CODEX_HOME" && -d "$CODEX_HOME/skills" ]]; then
        ln -s "$CODEX_HOME/skills" "$SKILLS_LINK"
        echo "🔗 Linked skills from: $CODEX_HOME/skills"
    elif [[ -d "$HOME/.codex/skills" ]]; then
        ln -s "$HOME/.codex/skills" "$SKILLS_LINK"
        echo "🔗 Linked skills from: $HOME/.codex/skills"
    fi
fi

if [[ ! -f "$SKILLS_LINK/codebase_explorer/machine.yml" ]]; then
    echo "❌ Missing codebase_explorer skill."
    echo "   Create a symlink: ln -s /path/to/skills \"$SKILLS_LINK\""
    exit 1
fi

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
    echo "  - Building flatagents from local source..."
    cd "$JS_SDK_PATH"
    npm run build
    cd "$SCRIPT_DIR"
fi

echo "  - Installing coding_agent demo package..."
npm install

# 2. Build TypeScript
echo "🏗️  Building TypeScript..."
npm run build

# 3. Run the Demo
echo "🚀 Running demo..."
echo "---"
node dist/coding_agent/main.js "${PASSTHROUGH_ARGS[@]}"
echo "---"

echo "✅ Demo complete!"
