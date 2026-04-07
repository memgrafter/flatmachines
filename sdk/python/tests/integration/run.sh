#!/bin/bash
# Integration Test Runner
# Runs all integration tests in isolated virtual environments
#
# Usage:
#   ./run.sh          # skip live tests (default)
#   ./run.sh --live   # include live tests (hits real APIs, costs money)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASSTHROUGH_ARGS=("$@")

echo "=============================================="
echo "FlatAgents Integration Tests"
if [[ " ${PASSTHROUGH_ARGS[*]} " =~ " --live " ]]; then
    echo "  (including live tests — hits real APIs)"
fi
echo "=============================================="
echo ""

# Track results
PASSED=0
FAILED=0
FAILED_TESTS=""

# Find and run all test suites
for test_dir in "$SCRIPT_DIR"/*/; do
    if [ -f "$test_dir/run.sh" ]; then
        test_name=$(basename "$test_dir")
        echo "Running: $test_name"
        echo "----------------------------------------------"
        
        if "$test_dir/run.sh" "${PASSTHROUGH_ARGS[@]}"; then
            echo "✓ $test_name PASSED"
            ((PASSED++))
        else
            echo "✗ $test_name FAILED"
            ((FAILED++))
            FAILED_TESTS="$FAILED_TESTS $test_name"
        fi
        echo ""
    fi
done

# Summary
echo "=============================================="
echo "Results: $PASSED passed, $FAILED failed"
echo "=============================================="

if [ $FAILED -gt 0 ]; then
    echo "Failed tests:$FAILED_TESTS"
    exit 1
fi

echo "All integration tests passed!"
