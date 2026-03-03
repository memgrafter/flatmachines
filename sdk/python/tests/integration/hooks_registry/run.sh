#!/bin/bash
set -e

VENV_PATH=".venv"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "--- HooksRegistry Integration Tests ---"

if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

echo "📦 Installing dependencies..."
echo "  - Installing flatmachines from local source..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../flatmachines[flatagents]"
echo "  - Installing flatagents from local source..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../../../flatagents[litellm]"
echo "  - Installing test dependencies..."
uv pip install --python "$VENV_PATH/bin/python" pytest pytest-asyncio

echo "🧪 Running hooks registry integration tests..."
echo "---"
"$VENV_PATH/bin/python" -m pytest test_hooks_registry.py -v
echo "---"

echo "✅ Hooks registry tests complete!"
