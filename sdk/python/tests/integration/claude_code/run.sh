#!/bin/bash
# Claude Code Adapter — Live Integration Tests
#
# Runs against the real claude binary + API.
# Requires: claude on PATH, valid auth, internet access.
#
# This script only passes --live to pytest when explicitly requested.
# Without --live, all tests are skipped (safe for CI).
#
# Usage:
#   ./run.sh                 # skipped unless --live is passed
#   ./run.sh --live          # run live tests
#   ./run.sh --local --live  # local source + live tests

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_DIR="$SCRIPT_DIR/../../../"
FLATAGENTS_DIR="$SDK_DIR/flatagents"
FLATMACHINES_DIR="$SDK_DIR/flatmachines"
VENV_PATH="$SCRIPT_DIR/.venv"

# --- Parse Arguments ---
LOCAL_INSTALL=false
LIVE=false
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --live)
            LIVE=true
            PYTEST_ARGS+=("--live")
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "Claude Code Adapter — Live Integration Tests"
echo "=============================================="

# --- Check prerequisites ---
if ! command -v claude &>/dev/null; then
    echo "SKIP: claude binary not found on PATH"
    exit 0
fi

echo "claude version: $(claude --version 2>&1)"

# --- Setup venv ---
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment..."
    uv venv "$VENV_PATH" --python python3.12 2>/dev/null || uv venv "$VENV_PATH" --python python3
fi

echo "Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATAGENTS_DIR" -e "$FLATMACHINES_DIR" pytest pytest-asyncio -q
else
    uv pip install --python "$VENV_PATH/bin/python" flatagents flatmachines pytest pytest-asyncio -q
fi

# --- Run tests ---
echo ""
echo "Running tests..."
echo ""

if [ "$LIVE" = false ]; then
    echo "NOTE: --live not passed; Claude Code live tests will be skipped."
fi

"$VENV_PATH/bin/python" -m pytest "$SCRIPT_DIR/test_claude_code_live.py" -v --tb=short -x "${PYTEST_ARGS[@]}" 2>&1

echo ""
echo "Claude Code integration tests passed!"
