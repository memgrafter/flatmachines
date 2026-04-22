#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install deps if needed
if [ ! -d "$SCRIPT_DIR/node_modules" ]; then
    echo "Installing dependencies..."
    (cd "$SCRIPT_DIR" && npm install --silent)
fi

# Run the TypeScript generator (defaults to assets/, Python SDK, JS SDK; bundles all spec .d.ts files including prompt.d.ts)
(cd "$SCRIPT_DIR" && npx tsx generate-spec-assets.ts "$@")
