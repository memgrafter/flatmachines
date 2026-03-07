#!/bin/bash
set -e

# --- Configuration ---
VENV_PATH=".venv"

# --- Parse Arguments ---
LOCAL_INSTALL=true
while [[ $# -gt 0 ]]; do
    case $1 in
        --pypi)
            LOCAL_INSTALL=false
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# --- Script Logic ---
echo "--- FlatMachines Signals Integration Tests ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 0. Ensure uv is installed
if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 1. Create Virtual Environment
echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

# 2. Install Dependencies
echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    echo "  - Installing flatmachines from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../../flatmachines[flatagents]"
    echo "  - Installing flatagents from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../../flatagents[litellm]"
else
    echo "  - Installing flatmachines from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatmachines[flatagents]"
    echo "  - Installing flatagents from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

echo "  - Installing test dependencies..."
uv pip install --python "$VENV_PATH/bin/python" pytest pytest-asyncio

# 3. Run the Tests
echo "🧪 Running signals integration tests..."
echo "---"
"$VENV_PATH/bin/python" -m pytest test_*.py -v
echo "---"

echo "✅ Signals integration tests complete!"
