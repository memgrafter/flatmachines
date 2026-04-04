#!/bin/bash
# Benchmark: count passing tests for flatmachines_cli productionization
set -eo pipefail

CLI_DIR="sdk/python/flatmachines_cli"
PYTHON="$CLI_DIR/.venv/bin/python"

# Run pytest, capture results
TEST_OUTPUT=$($PYTHON -m pytest "$CLI_DIR/tests/" -v --tb=short 2>&1) || true

# Count results from the summary line (e.g., "218 passed, 2 failed")
PASSED=$(echo "$TEST_OUTPUT" | grep -oP '\d+(?= passed)' || echo 0)
FAILED=$(echo "$TEST_OUTPUT" | grep -oP '\d+(?= failed)' || echo 0)
ERRORS=$(echo "$TEST_OUTPUT" | grep -oP '\d+(?= error)' || echo 0)

# Handle empty values
PASSED=${PASSED:-0}
FAILED=${FAILED:-0}
ERRORS=${ERRORS:-0}
TOTAL=$((PASSED + FAILED + ERRORS))

# Print test output for debugging (last 30 lines)
echo "$TEST_OUTPUT" | tail -30

echo ""
echo "METRIC tests_passing=$PASSED"
echo "METRIC tests_failing=$FAILED"
echo "METRIC tests_error=$ERRORS"
echo "METRIC tests_total=$TOTAL"

# Exit 0 as long as some tests pass
if [ "$PASSED" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
    exit 1
fi
exit 0
