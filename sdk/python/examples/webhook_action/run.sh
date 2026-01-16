#!/bin/bash
set -e

# --- Configuration ---
VENV_PATH=".venv"

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

# --- Script Logic ---
echo "--- Webhook Action Demo Runner ---"

# Get the directory the script is located in
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the script's directory
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
    echo "  - Installing flatagents from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../..[litellm]"
else
    echo "  - Installing flatagents from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi

echo "  - Installing webhook_action package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# 3. Run the Demo
echo "🚀 Running demo in mock mode..."
echo "---"

# If no passthrough args, use default with --mock flag
if [ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]; then
    "$VENV_PATH/bin/python" -m webhook_action.main \
        "I absolutely love this product! It exceeded all my expectations." \
        --mock
else
    "$VENV_PATH/bin/python" -m webhook_action.main "${PASSTHROUGH_ARGS[@]}"
fi

echo "---"
echo "✅ Demo complete!"
echo ""
echo "💡 To run with custom text:"
echo "  ./run.sh 'Your text here' --mock"
echo ""
echo "💡 To run with a real webhook endpoint:"
echo "  ./run.sh 'Your text' --endpoint http://localhost:8000/analyze"
