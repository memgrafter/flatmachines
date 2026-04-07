#!/bin/bash
set -euo pipefail

CLI_DIR="sdk/python/flatmachines_cli"
PYTHON="$CLI_DIR/.venv/bin/python"

# ===== Capability scoring =====
# Each capability is worth points. Total = capability_score.
# This avoids overfitting: we're measuring feature presence + correctness,
# not gaming a synthetic number.

score=0
test_count=0
source_loc=0

# --- Helper ---
award() {
    local points=$1
    local desc="$2"
    score=$((score + points))
    echo "  +${points}: ${desc}"
}

fail_check() {
    local desc="$1"
    echo "  +0: MISSING — ${desc}"
}

echo "=== Capability Assessment ==="

# ------------------------------------------------------------------
# 1. Experiment tracking module (25 points)
# ------------------------------------------------------------------
echo ""
echo "--- Experiment Tracking ---"

# 1a. Module exists and imports (5 pts)
if $PYTHON -c "from flatmachines_cli import experiment" 2>/dev/null; then
    award 5 "experiment module importable"
else
    # Try alternate location
    if $PYTHON -c "from flatmachines_cli.experiment import ExperimentTracker" 2>/dev/null; then
        award 5 "experiment module importable (ExperimentTracker)"
    else
        fail_check "experiment module importable"
    fi
fi

# 1b. ExperimentTracker class exists with core API (5 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
# Check it has the key methods
assert hasattr(t, 'init') or hasattr(t, 'initialize'), 'no init method'
assert hasattr(t, 'log') or hasattr(t, 'log_result'), 'no log method'
assert hasattr(t, 'run') or hasattr(t, 'run_command'), 'no run method'
print('API OK')
" 2>/dev/null; then
    award 5 "ExperimentTracker has core API (init/log/run)"
else
    fail_check "ExperimentTracker core API"
fi

# 1c. Metric parsing capability (5 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
# Check for metric parsing
import inspect
src = inspect.getsource(ExperimentTracker)
assert 'METRIC' in src or 'metric' in src.lower(), 'no metric handling'
print('Metric parsing OK')
" 2>/dev/null; then
    award 5 "ExperimentTracker has metric parsing"
else
    fail_check "metric parsing capability"
fi

# 1d. Experiment history/archive (5 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
has_history = hasattr(t, 'history') or hasattr(t, 'experiments') or hasattr(t, 'archive') or hasattr(t, 'results')
has_load = hasattr(t, 'load') or hasattr(t, 'load_history') or hasattr(t, 'from_file')
assert has_history or has_load, 'no history/archive capability'
print('History OK')
" 2>/dev/null; then
    award 5 "ExperimentTracker has history/archive"
else
    fail_check "experiment history/archive"
fi

# 1e. Keep/discard decision support (5 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
import inspect
src = inspect.getsource(ExperimentTracker)
has_keep = 'keep' in src.lower() or 'accept' in src.lower() or 'improved' in src.lower()
has_discard = 'discard' in src.lower() or 'reject' in src.lower() or 'revert' in src.lower()
assert has_keep and has_discard, f'keep={has_keep} discard={has_discard}'
print('Keep/discard OK')
" 2>/dev/null; then
    award 5 "ExperimentTracker has keep/discard support"
else
    fail_check "keep/discard decision support"
fi

# ------------------------------------------------------------------
# 2. Self-improvement machine config (25 points)  
# ------------------------------------------------------------------
echo ""
echo "--- Self-Improvement Machine Config ---"

# 2a. Config file exists (5 pts)
CONFIG_FOUND=""
for candidate in \
    "$CLI_DIR/config/self_improve.yml" \
    "$CLI_DIR/config/self_improve.yaml" \
    "$CLI_DIR/flatmachines_cli/config/self_improve.yml" \
    "$CLI_DIR/config/improve.yml"; do
    if [ -f "$candidate" ]; then
        CONFIG_FOUND="$candidate"
        break
    fi
done

if [ -n "$CONFIG_FOUND" ]; then
    award 5 "self-improvement config exists: $CONFIG_FOUND"
else
    fail_check "self-improvement machine config file"
fi

# 2b. Config is valid flatmachine YAML (5 pts)
if [ -n "$CONFIG_FOUND" ]; then
    if $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
assert config.get('spec') == 'flatmachine', f'spec={config.get(\"spec\")}'
assert 'data' in config
assert 'states' in config['data']
print(f'Valid flatmachine with {len(config[\"data\"][\"states\"])} states')
" 2>/dev/null; then
        award 5 "config is valid flatmachine YAML"
    else
        fail_check "config is valid flatmachine YAML"
    fi
else
    fail_check "config validation (no config)"
fi

# 2c. Has analyze/evaluate states (5 pts)
if [ -n "$CONFIG_FOUND" ]; then
    if $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
state_names = set(states.keys())
# Must have some form of analyze + evaluate
has_analyze = any(s for s in state_names if 'analy' in s.lower() or 'assess' in s.lower() or 'benchmark' in s.lower())
has_evaluate = any(s for s in state_names if 'eval' in s.lower() or 'test' in s.lower() or 'check' in s.lower())
assert has_analyze, f'no analyze state in {state_names}'
assert has_evaluate, f'no evaluate state in {state_names}'
print('Analyze + Evaluate states found')
" 2>/dev/null; then
        award 5 "config has analyze + evaluate states"
    else
        fail_check "analyze + evaluate states in config"
    fi
else
    fail_check "analyze/evaluate states (no config)"
fi

# 2d. Has implement/modify state (5 pts)
if [ -n "$CONFIG_FOUND" ]; then
    if $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
state_names = set(states.keys())
has_implement = any(s for s in state_names if 'implement' in s.lower() or 'code' in s.lower() or 'modify' in s.lower() or 'work' in s.lower() or 'improve' in s.lower())
assert has_implement, f'no implement state in {state_names}'
print('Implement state found')
" 2>/dev/null; then
        award 5 "config has implement/modify state"
    else
        fail_check "implement/modify state in config"
    fi
else
    fail_check "implement state (no config)"
fi

# 2e. Has loop structure (transitions back) (5 pts)
if [ -n "$CONFIG_FOUND" ]; then
    if $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
# Check for any backward transition (loop)
all_transitions = []
for sname, sdata in states.items():
    for t in sdata.get('transitions', []):
        all_transitions.append((sname, t.get('to', '')))
# A loop exists if some state transitions to an earlier state in the flow
state_order = list(states.keys())
has_loop = False
for from_s, to_s in all_transitions:
    if to_s in state_order:
        from_idx = state_order.index(from_s) if from_s in state_order else -1
        to_idx = state_order.index(to_s) if to_s in state_order else -1
        if to_idx < from_idx and to_idx >= 0:
            has_loop = True
            break
# Also check for explicit max_steps
has_loop = has_loop or config['data'].get('max_steps')
assert has_loop, 'no loop structure found'
print('Loop structure found')
" 2>/dev/null; then
        award 5 "config has loop/iteration structure"
    else
        fail_check "loop structure in config"
    fi
else
    fail_check "loop structure (no config)"
fi

# ------------------------------------------------------------------
# 3. CLI Integration (15 points)
# ------------------------------------------------------------------
echo ""
echo "--- CLI Integration ---"

# 3a. improve module exists (5 pts)
if $PYTHON -c "from flatmachines_cli import improve" 2>/dev/null || \
   $PYTHON -c "from flatmachines_cli.improve import SelfImprover" 2>/dev/null; then
    award 5 "improve module importable"
else
    fail_check "improve module importable"
fi

# 3b. Exported in __init__.py or accessible via CLI (5 pts)
if $PYTHON -c "
import flatmachines_cli
has_experiment = hasattr(flatmachines_cli, 'ExperimentTracker') or hasattr(flatmachines_cli, 'experiment')
has_improve = hasattr(flatmachines_cli, 'SelfImprover') or hasattr(flatmachines_cli, 'improve')
assert has_experiment or has_improve, 'not exported'
print('Exported OK')
" 2>/dev/null; then
    award 5 "new modules accessible via package"
else
    fail_check "new modules accessible via package"
fi

# 3c. CLI subcommand or REPL command for improve (5 pts)
if $PYTHON -c "
import inspect
from flatmachines_cli.main import main
src = inspect.getsource(main)
has_improve_cmd = 'improve' in src or 'self-improve' in src or 'self_improve' in src or 'experiment' in src
assert has_improve_cmd, 'no improve command in CLI'
print('CLI integration OK')
" 2>/dev/null || \
$PYTHON -c "
import inspect
from flatmachines_cli.repl import FlatMachinesREPL
src = inspect.getsource(FlatMachinesREPL)
has_improve_cmd = 'improve' in src or 'experiment' in src
assert has_improve_cmd, 'no improve command in REPL'
print('REPL integration OK')
" 2>/dev/null; then
    award 5 "improve command integrated in CLI/REPL"
else
    fail_check "improve command in CLI/REPL"
fi

# ------------------------------------------------------------------
# 4. Test Coverage for New Code (20 points)
# ------------------------------------------------------------------
echo ""
echo "--- Test Coverage ---"

# Count tests for experiment module
EXP_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "experiment" 2>/dev/null | grep -c "test_" || true)
EXP_TESTS=${EXP_TESTS:-0}
if [ "$EXP_TESTS" -ge 5 ]; then
    award 10 "experiment module has $EXP_TESTS tests (≥5)"
elif [ "$EXP_TESTS" -ge 1 ]; then
    award 5 "experiment module has $EXP_TESTS tests (≥1, want ≥5)"
else
    fail_check "experiment module tests"
fi

# Count tests for improve module
IMP_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "improve or self_improve" 2>/dev/null | grep -c "test_" || true)
IMP_TESTS=${IMP_TESTS:-0}
if [ "$IMP_TESTS" -ge 5 ]; then
    award 10 "improve module has $IMP_TESTS tests (≥5)"
elif [ "$IMP_TESTS" -ge 1 ]; then
    award 5 "improve module has $IMP_TESTS tests (≥1, want ≥5)"
else
    fail_check "improve module tests"
fi

# ------------------------------------------------------------------
# 5. Self-Contained (No External Dependencies) (15 points)
# ------------------------------------------------------------------
echo ""
echo "--- Self-Contained ---"

# 5a. No imports of hyperagents (5 pts)
if ! grep -r "hyperagent\|HyperAgent" "$CLI_DIR/flatmachines_cli/" 2>/dev/null | grep -v ".pyc" | grep -q .; then
    award 5 "no HyperAgents dependency"
else
    fail_check "no HyperAgents dependency"
fi

# 5b. No imports of pi-autoresearch (5 pts)
if ! grep -r "pi.autoresearch\|pi_autoresearch\|autoresearch" "$CLI_DIR/flatmachines_cli/" 2>/dev/null | grep -v ".pyc" | grep -v "# " | grep -q "import"; then
    award 5 "no pi-autoresearch dependency"
else
    fail_check "no pi-autoresearch dependency"
fi

# 5c. experiment.py doesn't shell out to external tools for core loop (5 pts)
if [ -f "$CLI_DIR/flatmachines_cli/experiment.py" ]; then
    if $PYTHON -c "
import ast, sys
with open('$CLI_DIR/flatmachines_cli/experiment.py') as f:
    tree = ast.parse(f.read())
# Check no imports of external self-improve tools
external = {'hyperagents', 'pi_autoresearch', 'autoresearch'}
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mod = getattr(node, 'module', '') or ''
        names = [a.name for a in getattr(node, 'names', [])]
        for x in [mod] + names:
            assert x.lower() not in external, f'imports {x}'
print('No external deps')
" 2>/dev/null; then
        award 5 "experiment.py is self-contained"
    else
        fail_check "experiment.py is self-contained"
    fi
else
    fail_check "experiment.py self-contained (file missing)"
fi

# ------------------------------------------------------------------
# Calculate total and emit metrics
# ------------------------------------------------------------------
echo ""
echo "=== Score Summary ==="
echo "  capability_score = $score / 100"

# Count all passing tests
TEST_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --tb=no 2>&1 | tail -1)
test_count=$(echo "$TEST_RESULT" | grep -oP '\d+(?= passed)' || echo 0)

# Count source LOC
source_loc=$(wc -l "$CLI_DIR/flatmachines_cli/"*.py 2>/dev/null | tail -1 | awk '{print $1}')

echo "  test_count = $test_count"
echo "  source_loc = $source_loc"
echo ""

echo "METRIC capability_score=$score"
echo "METRIC test_count=$test_count"
echo "METRIC source_loc=$source_loc"
