#!/bin/bash
set -e

PYTHON_BIN="${PYTHON_BIN:-python3}"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$SCRIPT_DIR"
exec "$PYTHON_BIN" main.py "$@"
