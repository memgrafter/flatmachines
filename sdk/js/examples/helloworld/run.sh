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

echo "--- FlatAgent HelloWorld Demo Runner ---"

# Get the directory the script is located in
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
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
    echo "  - Building flatagents from local source..."
    cd ../../
    npm run build
    cd "$SCRIPT_DIR"
fi

echo "  - Installing helloworld demo package..."
npm install

# 2. Build TypeScript
echo "🏗️  Building TypeScript..."
npm run build

# 3. Run the Demo
echo "🚀 Running demo..."
echo "---"
node dist/helloworld/main.js
echo "---"

echo "✅ Demo complete!"
