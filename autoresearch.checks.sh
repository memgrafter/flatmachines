#!/bin/bash
# Checks: verify no regressions in flatmachines_cli
set -euo pipefail

CLI_DIR="sdk/python/flatmachines_cli"
PYTHON="$CLI_DIR/.venv/bin/python"

echo "=== Check 1: Package imports cleanly ==="
$PYTHON -c "import flatmachines_cli; print(f'Version: {flatmachines_cli.__version__}')"

echo "=== Check 2: All public API members accessible ==="
$PYTHON -c "
from flatmachines_cli import (
    DataBus, Slot, SlotValue,
    MACHINE_START, MACHINE_END,
    StatusProcessor, TokenProcessor, ToolProcessor, ContentProcessor, ErrorProcessor,
    CLIBackend, CLIHooks, Frontend, ActionHandler, TerminalFrontend,
    MachineIndex, MachineInfo,
    inspect_machine, validate_machine, show_context,
    FlatMachinesREPL,
)
print('All public API members accessible')
"

echo "=== Check 3: No syntax errors in all source files ==="
$PYTHON -c "
import py_compile
import glob
import sys
files = glob.glob('$CLI_DIR/flatmachines_cli/*.py')
for f in files:
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        print(f'Syntax error: {e}')
        sys.exit(1)
print(f'All {len(files)} source files compile cleanly')
"

echo "=== Check 4: No test failures (0 failures required) ==="
RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --tb=line 2>&1) || true
FAILED=$(echo "$RESULT" | grep -oP '\d+(?= failed)' || echo 0)
echo "$RESULT" | tail -5
if [ "$FAILED" != "0" ] && [ "$FAILED" != "" ]; then
    echo "FAIL: $FAILED test(s) failed"
    exit 1
fi

echo ""
echo "=== All checks passed ==="
