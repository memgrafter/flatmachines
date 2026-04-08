#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"

RESULT=$(.venv/bin/python -m pytest tests/ -q --tb=no 2>&1 | tail -1)
PASSED=$(echo "$RESULT" | grep -oP '\d+(?= passed)' || echo 0)
FAILED=$(echo "$RESULT" | grep -oP '\d+(?= failed)' || echo 0)
TOTAL=$((PASSED + FAILED))

echo "METRIC tests_passing=$PASSED"
echo "METRIC tests_failing=$FAILED"
echo "METRIC tests_total=$TOTAL"

# Success as long as we got results
[ "$TOTAL" -gt 0 ]
