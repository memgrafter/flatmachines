#!/bin/bash
# Run parity tests. Pass a specific file or glob to filter.
# Usage:
#   bash test.sh                              # all parity tests
#   bash test.sh signals-core.parity.test.ts  # single suite
set -e
cd "$(dirname "$0")/../.."
npx vitest run tests/parity/${1:-}
