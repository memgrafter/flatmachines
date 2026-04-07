#!/bin/bash
set -euo pipefail

CLI_DIR="sdk/python/flatmachines_cli"
PYTHON="$CLI_DIR/.venv/bin/python"

# ===== Capability scoring =====
# Phase 1: Presence checks (100 pts) — infrastructure exists
# Phase 2: Quality checks (100 pts) — infrastructure works well
# Total: 200 points possible

score=0
test_count=0
source_loc=0

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

echo "=== Phase 1: Presence (100 pts) ==="

# ------------------------------------------------------------------
# 1. Experiment tracking module (25 points)
# ------------------------------------------------------------------
echo ""
echo "--- Experiment Tracking ---"

if $PYTHON -c "from flatmachines_cli.experiment import ExperimentTracker" 2>/dev/null; then
    award 5 "experiment module importable"
else
    fail_check "experiment module importable"
fi

if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
assert hasattr(t, 'init') or hasattr(t, 'initialize'), 'no init method'
assert hasattr(t, 'log') or hasattr(t, 'log_result'), 'no log method'
assert hasattr(t, 'run') or hasattr(t, 'run_command'), 'no run method'
print('API OK')
" 2>/dev/null; then
    award 5 "ExperimentTracker has core API"
else
    fail_check "ExperimentTracker core API"
fi

if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
import inspect
src = inspect.getsource(ExperimentTracker)
assert 'METRIC' in src or 'metric' in src.lower()
print('OK')
" 2>/dev/null; then
    award 5 "metric parsing capability"
else
    fail_check "metric parsing"
fi

if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
has_hist = hasattr(t, 'history') or hasattr(t, 'experiments') or hasattr(t, 'archive') or hasattr(t, 'results')
has_load = hasattr(t, 'load') or hasattr(t, 'load_history') or hasattr(t, 'from_file')
assert has_hist or has_load
print('OK')
" 2>/dev/null; then
    award 5 "experiment history/archive"
else
    fail_check "history/archive"
fi

if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
import inspect
src = inspect.getsource(ExperimentTracker)
has_keep = 'keep' in src.lower() or 'accept' in src.lower() or 'improved' in src.lower()
has_discard = 'discard' in src.lower() or 'reject' in src.lower() or 'revert' in src.lower()
assert has_keep and has_discard
print('OK')
" 2>/dev/null; then
    award 5 "keep/discard support"
else
    fail_check "keep/discard"
fi

# ------------------------------------------------------------------
# 2. Self-improvement machine config (25 points)
# ------------------------------------------------------------------
echo ""
echo "--- Machine Config ---"

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
    award 5 "config exists"
else
    fail_check "config file"
fi

if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
assert config.get('spec') == 'flatmachine'
assert 'states' in config['data']
print(f'{len(config[\"data\"][\"states\"])} states')
" 2>/dev/null; then
    award 5 "valid flatmachine YAML"
else
    fail_check "valid config"
fi

if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = set(config['data']['states'].keys())
assert any('analy' in s.lower() or 'assess' in s.lower() or 'benchmark' in s.lower() for s in states)
assert any('eval' in s.lower() or 'test' in s.lower() or 'check' in s.lower() for s in states)
print('OK')
" 2>/dev/null; then
    award 5 "analyze + evaluate states"
else
    fail_check "analyze/evaluate states"
fi

if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = set(config['data']['states'].keys())
assert any('implement' in s.lower() or 'code' in s.lower() or 'modify' in s.lower() or 'work' in s.lower() or 'improve' in s.lower() for s in states)
print('OK')
" 2>/dev/null; then
    award 5 "implement state"
else
    fail_check "implement state"
fi

if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
state_order = list(states.keys())
has_loop = False
for sname, sdata in states.items():
    for t in sdata.get('transitions', []):
        to_s = t.get('to', '')
        if to_s in state_order:
            from_idx = state_order.index(sname)
            to_idx = state_order.index(to_s)
            if to_idx < from_idx:
                has_loop = True
has_loop = has_loop or config['data'].get('max_steps')
assert has_loop
print('OK')
" 2>/dev/null; then
    award 5 "loop structure"
else
    fail_check "loop structure"
fi

# ------------------------------------------------------------------
# 3. CLI Integration (15 points)
# ------------------------------------------------------------------
echo ""
echo "--- CLI Integration ---"

if $PYTHON -c "from flatmachines_cli.improve import SelfImprover" 2>/dev/null; then
    award 5 "improve module"
else
    fail_check "improve module"
fi

if $PYTHON -c "
import flatmachines_cli
assert hasattr(flatmachines_cli, 'ExperimentTracker') or hasattr(flatmachines_cli, 'experiment')
assert hasattr(flatmachines_cli, 'SelfImprover') or hasattr(flatmachines_cli, 'improve')
print('OK')
" 2>/dev/null; then
    award 5 "package exports"
else
    fail_check "package exports"
fi

if $PYTHON -c "
import inspect
from flatmachines_cli.main import main
src = inspect.getsource(main)
assert 'improve' in src or 'self-improve' in src or 'experiment' in src
print('OK')
" 2>/dev/null; then
    award 5 "CLI subcommand"
else
    fail_check "CLI subcommand"
fi

# ------------------------------------------------------------------
# 4. Test Coverage (20 points)
# ------------------------------------------------------------------
echo ""
echo "--- Test Coverage ---"

EXP_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "experiment" 2>/dev/null | grep -c "test_" || true)
EXP_TESTS=${EXP_TESTS:-0}
if [ "$EXP_TESTS" -ge 5 ]; then
    award 10 "experiment tests ($EXP_TESTS)"
elif [ "$EXP_TESTS" -ge 1 ]; then
    award 5 "experiment tests ($EXP_TESTS, want ≥5)"
else
    fail_check "experiment tests"
fi

IMP_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "improve or self_improve" 2>/dev/null | grep -c "test_" || true)
IMP_TESTS=${IMP_TESTS:-0}
if [ "$IMP_TESTS" -ge 5 ]; then
    award 10 "improve tests ($IMP_TESTS)"
elif [ "$IMP_TESTS" -ge 1 ]; then
    award 5 "improve tests ($IMP_TESTS, want ≥5)"
else
    fail_check "improve tests"
fi

# ------------------------------------------------------------------
# 5. Self-Contained (15 points)
# ------------------------------------------------------------------
echo ""
echo "--- Self-Contained ---"

if ! grep -r "hyperagent\|HyperAgent" "$CLI_DIR/flatmachines_cli/" 2>/dev/null | grep -v ".pyc" | grep -q .; then
    award 5 "no external agent deps"
else
    fail_check "external agent deps found"
fi

if ! grep -r "pi.autoresearch\|pi_autoresearch" "$CLI_DIR/flatmachines_cli/" 2>/dev/null | grep -v ".pyc" | grep -q "import"; then
    award 5 "no pi-autoresearch dep"
else
    fail_check "pi-autoresearch dep"
fi

if [ -f "$CLI_DIR/flatmachines_cli/experiment.py" ]; then
    if $PYTHON -c "
import ast
with open('$CLI_DIR/flatmachines_cli/experiment.py') as f:
    tree = ast.parse(f.read())
external = {'hyperagents', 'pi_autoresearch', 'autoresearch'}
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mod = getattr(node, 'module', '') or ''
        names = [a.name for a in getattr(node, 'names', [])]
        for x in [mod] + names:
            assert x.lower() not in external, f'imports {x}'
print('OK')
" 2>/dev/null; then
        award 5 "experiment.py self-contained"
    else
        fail_check "experiment.py has external deps"
    fi
else
    fail_check "experiment.py missing"
fi

phase1=$score
echo ""
echo "Phase 1 subtotal: $phase1 / 100"

# ==================================================================
echo ""
echo "=== Phase 2: Quality (100 pts) ==="
# ==================================================================

# ------------------------------------------------------------------
# 6. End-to-end experiment loop (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- E2E Experiment Loop ---"

# 6a. Tracker can run a command, parse metrics, log, and query (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker

with tempfile.TemporaryDirectory() as td:
    t = ExperimentTracker(
        name='e2e-test',
        metric_name='score',
        direction='higher',
        log_path=os.path.join(td, 'log.jsonl'),
        working_dir=td,
    )
    t.init()
    
    # Run command that outputs metrics
    r = t.run(\"echo 'METRIC score=42' && echo 'METRIC speed=1.5'\")
    assert r.success, f'command failed: {r.error}'
    assert r.metrics['score'] == 42.0
    assert r.metrics['speed'] == 1.5
    
    # Log and verify
    entry = t.log(result=r, status='keep', description='e2e test')
    assert entry.primary_metric == 42.0
    assert t.best_metric() == 42.0
    assert t.is_improved(50.0)
    assert not t.is_improved(30.0)
    
    # Second run
    r2 = t.run(\"echo 'METRIC score=55'\")
    entry2 = t.log(result=r2, status='keep', description='better')
    assert t.best_metric() == 55.0
    assert len(t.history) == 2
    
    print('E2E OK')
" 2>/dev/null; then
    award 10 "full experiment loop works"
else
    fail_check "experiment loop e2e"
fi

# 6b. Persistence round-trip (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

with tempfile.TemporaryDirectory() as td:
    log = os.path.join(td, 'log.jsonl')
    
    # Create and populate
    t1 = ExperimentTracker(name='persist', metric_name='val', direction='lower', log_path=log)
    t1.init()
    r = ExperimentResult(command='test', exit_code=0, stdout='', stderr='', duration_s=1.0, 
                         metrics={'val': 5.0}, success=True)
    t1.log(result=r, status='keep', description='run1', tags=['perf'], notes={'key': 'val'})
    t1.log(result=r, status='discard', description='run2', primary_metric=8.0)
    
    # Restore from file
    t2 = ExperimentTracker.from_file(log)
    assert t2.name == 'persist'
    assert t2.metric_name == 'val'
    assert t2.direction == 'lower'
    assert len(t2.history) == 2
    assert t2.history[0].tags == ['perf']
    assert t2.history[0].notes == {'key': 'val'}
    assert t2.best_metric() == 5.0  # lower is better
    
    # Resume with new entry
    t2.init()
    entry = t2.log(result=r, status='keep', description='run3', primary_metric=3.0)
    assert entry.experiment_id == 3
    assert t2.best_metric() == 3.0
    
    print('Persist OK')
" 2>/dev/null; then
    award 10 "persistence round-trip"
else
    fail_check "persistence round-trip"
fi

# 6c. Error handling (5 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker

with tempfile.TemporaryDirectory() as td:
    t = ExperimentTracker(log_path=os.path.join(td, 'log.jsonl'), working_dir=td)
    t.init()
    
    # Timeout
    r = t.run('sleep 10', timeout=0.5)
    assert not r.success
    assert 'timed out' in (r.error or '')
    
    # Bad command
    r2 = t.run('exit 42')
    assert not r2.success
    assert r2.exit_code == 42
    
    # Missing metric gracefully handled
    r3 = t.run('echo hello')
    assert r3.metrics == {}
    entry = t.log(result=r3, status='keep')
    assert entry.primary_metric == 0.0  # default when metric missing
    
    print('Error handling OK')
" 2>/dev/null; then
    award 5 "error handling"
else
    fail_check "error handling"
fi

# ------------------------------------------------------------------
# 7. SelfImprover integration (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- SelfImprover Integration ---"

# 7a. Full evaluate cycle (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.improve import SelfImprover

with tempfile.TemporaryDirectory() as td:
    imp = SelfImprover(
        target_dir=td,
        benchmark_command=\"echo 'METRIC score=42'\",
        metric_name='score',
        direction='higher',
        log_path=os.path.join(td, 'log.jsonl'),
        working_dir=td,
    )
    
    # Benchmark
    r = imp.run_benchmark()
    assert r.success
    assert r.metrics['score'] == 42.0
    
    # Evaluate
    ev = imp.evaluate(r)
    assert ev['improved'] is True  # first result
    assert ev['metric_value'] == 42.0
    
    # Log
    imp.log_improvement(r, 'keep', 'baseline')
    
    # Second benchmark (worse)
    r2 = imp.tracker.run(\"echo 'METRIC score=30'\")
    ev2 = imp.evaluate(r2)
    assert ev2['improved'] is False
    assert ev2['delta'] == -12.0
    
    print('Evaluate OK')
" 2>/dev/null; then
    award 10 "evaluate cycle"
else
    fail_check "evaluate cycle"
fi

# 7b. SelfImproveHooks action dispatch (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.improve import SelfImprover, SelfImproveHooks

with tempfile.TemporaryDirectory() as td:
    imp = SelfImprover(
        target_dir=td,
        benchmark_command=\"echo 'METRIC score=42'\",
        metric_name='score',
        direction='higher',
        log_path=os.path.join(td, 'log.jsonl'),
        working_dir=td,
    )
    hooks = SelfImproveHooks(imp)
    
    # Evaluate action
    ctx = {'iteration': 0, 'consecutive_failures': 0, 'best_score': None, 'improvement_history': []}
    ctx = hooks.on_action('evaluate_improvement', ctx)
    assert ctx['current_score'] == 42.0
    assert ctx['last_status'] == 'improved'
    assert ctx['best_score'] == 42.0
    assert ctx['iteration'] == 1
    
    # Archive action
    ctx['last_hypothesis'] = 'test'
    ctx = hooks.on_action('archive_result', ctx)
    assert len(ctx['improvement_history']) == 1
    
    # Unknown action passthrough
    ctx2 = hooks.on_action('unknown', {'key': 'val'})
    assert ctx2 == {'key': 'val'}
    
    print('Hooks OK')
" 2>/dev/null; then
    award 10 "hooks action dispatch"
else
    fail_check "hooks dispatch"
fi

# 7c. Summary and noise floor (5 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.improve import SelfImprover
from flatmachines_cli.experiment import ExperimentResult

with tempfile.TemporaryDirectory() as td:
    imp = SelfImprover(
        target_dir=td,
        benchmark_command='echo test',
        log_path=os.path.join(td, 'log.jsonl'),
    )
    
    s = imp.summary()
    assert 'name' in s
    assert 'total_experiments' in s
    assert s['total_experiments'] == 0
    
    # Add some results to test noise floor
    for val in [10.0, 10.1, 9.9, 10.0, 10.2]:
        r = ExperimentResult(command='t', exit_code=0, stdout='', stderr='',
                            duration_s=1.0, success=True)
        imp.tracker.log(result=r, status='keep', primary_metric=val)
    
    nf = imp.tracker.noise_floor()
    assert nf is not None
    assert nf < 1.0  # Should be small for nearly-constant values
    
    print('Summary OK')
" 2>/dev/null; then
    award 5 "summary and noise floor"
else
    fail_check "summary/noise floor"
fi

# ------------------------------------------------------------------
# 8. Machine config quality (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Config Quality ---"

# 8a. Config has agent references (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
agents = config['data'].get('agents', {})
assert len(agents) > 0, 'no agents'
print(f'{len(agents)} agent(s)')
" 2>/dev/null; then
    award 5 "config has agents"
else
    fail_check "config agents"
fi

# 8b. Config has proper input/output (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
ctx = config['data'].get('context', {})
# Must have input references
has_input = any('input.' in str(v) for v in ctx.values())
assert has_input, 'no input references in context'
# Must have final state with output
states = config['data']['states']
final = [s for s in states.values() if s.get('type') == 'final']
assert final and final[0].get('output'), 'no final output'
print('IO OK')
" 2>/dev/null; then
    award 5 "config has proper I/O"
else
    fail_check "config I/O"
fi

# 8c. Config has action states for evaluate/archive (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
actions = set()
for s in states.values():
    a = s.get('action')
    if a:
        actions.add(a)
assert 'evaluate_improvement' in actions or 'evaluate' in actions, f'no evaluate action: {actions}'
print(f'Actions: {actions}')
" 2>/dev/null; then
    award 5 "config has evaluate action"
else
    fail_check "evaluate action"
fi

# 8d. Config has conditional transitions (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
states = config['data']['states']
cond_count = 0
for s in states.values():
    for t in s.get('transitions', []):
        if t.get('condition'):
            cond_count += 1
assert cond_count >= 2, f'only {cond_count} conditional transitions'
print(f'{cond_count} conditional transitions')
" 2>/dev/null; then
    award 5 "conditional transitions"
else
    fail_check "conditional transitions"
fi

# 8e. Config uses metadata properly (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
meta = config.get('metadata', {})
assert meta.get('description'), 'no description'
assert meta.get('tags'), 'no tags'
assert 'self-improvement' in meta['tags'] or 'self_improvement' in meta['tags'] or 'improve' in str(meta['tags']).lower()
print('Metadata OK')
" 2>/dev/null; then
    award 5 "config metadata"
else
    fail_check "config metadata"
fi

# ------------------------------------------------------------------
# 9. Test quality (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Test Quality ---"

# 9a. All new tests pass (10 pts)
NEW_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/test_experiment.py" "$CLI_DIR/tests/test_improve.py" -q --tb=line 2>&1) || true
NEW_FAILED=$(echo "$NEW_RESULT" | grep -oP '\d+(?= failed)' || echo 0)
NEW_PASSED=$(echo "$NEW_RESULT" | grep -oP '\d+(?= passed)' || echo 0)
NEW_PASSED=${NEW_PASSED:-0}
if [ "${NEW_FAILED:-0}" = "0" ] && [ "$NEW_PASSED" -gt 0 ]; then
    award 10 "all new tests pass ($NEW_PASSED)"
else
    fail_check "new tests: $NEW_FAILED failed"
fi

# 9b. Self-improvement-specific integration tests (5 pts)
if $PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "self_improve_integration" 2>/dev/null | grep -q "test_"; then
    INTEG_COUNT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "self_improve_integration" 2>/dev/null | grep -c "test_" || true)
    award 5 "self-improve integration tests ($INTEG_COUNT)"
else
    fail_check "self-improve integration tests"
fi

# 9c. Test covers edge cases (≥40 total new tests) (5 pts)
TOTAL_NEW=$((${EXP_TESTS:-0} + ${IMP_TESTS:-0}))
if [ "$TOTAL_NEW" -ge 40 ]; then
    award 5 "thorough test coverage ($TOTAL_NEW tests)"
elif [ "$TOTAL_NEW" -ge 20 ]; then
    award 3 "good test coverage ($TOTAL_NEW tests, want ≥40)"
else
    fail_check "test coverage ($TOTAL_NEW tests, want ≥40)"
fi

# 9d. Test file structure (separate test files for each module) (5 pts)
if [ -f "$CLI_DIR/tests/test_experiment.py" ] && [ -f "$CLI_DIR/tests/test_improve.py" ]; then
    award 5 "separate test files"
else
    fail_check "separate test files"
fi

phase2=$((score - phase1))
echo ""
echo "Phase 2 subtotal: $phase2 / 100"

# ==================================================================
echo ""
echo "=== Phase 3: Real-World Readiness (100 pts) ==="
# ==================================================================

# ------------------------------------------------------------------
# 10. Agent configs exist and are valid (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Agent Configs ---"

# 10a. Analyzer agent config exists and valid (5 pts)
ANALYZER="$CLI_DIR/config/agents/analyzer.yml"
if [ -f "$ANALYZER" ] && $PYTHON -c "
import yaml
with open('$ANALYZER') as f:
    config = yaml.safe_load(f)
assert config['spec'] == 'flatagent'
assert config['data'].get('tools')
assert config['data'].get('system')
print('OK')
" 2>/dev/null; then
    award 5 "analyzer agent config"
else
    fail_check "analyzer agent config"
fi

# 10b. Implementer agent config exists and valid (5 pts)
IMPLEMENTER="$CLI_DIR/config/agents/implementer.yml"
if [ -f "$IMPLEMENTER" ] && $PYTHON -c "
import yaml
with open('$IMPLEMENTER') as f:
    config = yaml.safe_load(f)
assert config['spec'] == 'flatagent'
tools = {t['function']['name'] for t in config['data']['tools']}
assert tools >= {'read', 'bash', 'write', 'edit'}, f'missing tools: {tools}'
print('OK')
" 2>/dev/null; then
    award 5 "implementer agent config (all 4 tools)"
else
    fail_check "implementer agent config"
fi

# 10c. Agents use profile-based model (adapter-agnostic) (5 pts)
if $PYTHON -c "
import yaml
for path in ['$ANALYZER', '$IMPLEMENTER']:
    with open(path) as f:
        config = yaml.safe_load(f)
    model = config['data']['model']
    assert isinstance(model, str), f'{path}: model should be profile string, got {model}'
print('OK')
" 2>/dev/null; then
    award 5 "agents use profile-based model (adapter-agnostic)"
else
    fail_check "agents profile-based model"
fi

# 10d. Agent refs in machine config resolve to existing files (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
from pathlib import Path
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
config_dir = Path('$CONFIG_FOUND').parent
agents = config['data'].get('agents', {})
for name, ref in agents.items():
    if isinstance(ref, str):
        resolved = config_dir / ref
        assert resolved.exists(), f'Agent {name} -> {ref} not found at {resolved}'
print(f'{len(agents)} agent ref(s) resolve')
" 2>/dev/null; then
    award 5 "agent refs resolve to existing files"
else
    fail_check "agent refs resolve"
fi

# 10e. Machine config states reference declared agents (5 pts)
if [ -n "$CONFIG_FOUND" ] && $PYTHON -c "
import yaml
with open('$CONFIG_FOUND') as f:
    config = yaml.safe_load(f)
declared = set(config['data'].get('agents', {}).keys())
used = set()
for sdata in config['data']['states'].values():
    a = sdata.get('agent')
    if a: used.add(a)
undeclared = used - declared
assert not undeclared, f'States reference undeclared agents: {undeclared}'
assert used, 'No states reference any agents'
print(f'Used: {used}, all declared')
" 2>/dev/null; then
    award 5 "states reference declared agents"
else
    fail_check "states reference declared agents"
fi

# ------------------------------------------------------------------
# 11. Self-improvement integration tests (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Integration Tests ---"

# 11a. Integration test file exists (5 pts)
if [ -f "$CLI_DIR/tests/test_self_improve_integration.py" ]; then
    award 5 "integration test file exists"
else
    fail_check "integration test file"
fi

# 11b. Integration tests pass (10 pts)
if [ -f "$CLI_DIR/tests/test_self_improve_integration.py" ]; then
    INTEG_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/test_self_improve_integration.py" -q --tb=line 2>&1) || true
    INTEG_FAILED=$(echo "$INTEG_RESULT" | grep -oP '\d+(?= failed)' || echo 0)
    INTEG_PASSED=$(echo "$INTEG_RESULT" | grep -oP '\d+(?= passed)' || echo 0)
    INTEG_PASSED=${INTEG_PASSED:-0}
    if [ "${INTEG_FAILED:-0}" = "0" ] && [ "$INTEG_PASSED" -gt 0 ]; then
        award 10 "integration tests pass ($INTEG_PASSED)"
    else
        fail_check "integration tests: $INTEG_FAILED failed"
    fi
else
    fail_check "integration tests (no file)"
fi

# 11c. Tests cover config validation (5 pts)
if $PYTHON -m pytest "$CLI_DIR/tests/test_self_improve_integration.py" -q --co -k "config" 2>/dev/null | grep -q "test_"; then
    CFG_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/test_self_improve_integration.py" -q --co -k "config" 2>/dev/null | grep -c "test_" || true)
    award 5 "config validation tests ($CFG_TESTS)"
else
    fail_check "config validation tests"
fi

# 11d. Tests cover adapter compatibility (5 pts)
if $PYTHON -m pytest "$CLI_DIR/tests/test_self_improve_integration.py" -q --co -k "adapter or compatibility or profile" 2>/dev/null | grep -q "test_"; then
    ADAPT_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/test_self_improve_integration.py" -q --co -k "adapter or compatibility or profile" 2>/dev/null | grep -c "test_" || true)
    award 5 "adapter compatibility tests ($ADAPT_TESTS)"
else
    fail_check "adapter compatibility tests"
fi

# ------------------------------------------------------------------
# 12. Real self-improvement on own codebase (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Self-Benchmark ---"

# 12a. SelfImprover can benchmark flatmachines_cli itself (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.improve import SelfImprover

td = tempfile.mkdtemp()
imp = SelfImprover(
    target_dir='$CLI_DIR',
    benchmark_command=\"$PYTHON -m pytest $CLI_DIR/tests/ -q --tb=no 2>&1 | tail -1 | grep -oP '\\\\d+(?= passed)' | xargs -I{} echo 'METRIC test_count={}'\",
    metric_name='test_count',
    direction='higher',
    log_path=os.path.join(td, 'log.jsonl'),
    working_dir='.',
)
r = imp.run_benchmark()
assert r.success, f'Failed: {r.error}'
tc = r.metrics.get('test_count', 0)
assert tc > 500, f'Expected >500 tests, got {tc}'
print(f'Self-benchmark: {tc} tests')
" 2>/dev/null; then
    award 10 "self-benchmark works on own codebase"
else
    fail_check "self-benchmark on own codebase"
fi

# 12b. ExperimentTracker can track its own test runs (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker

td = tempfile.mkdtemp()
t = ExperimentTracker(
    name='self-track',
    metric_name='test_count',
    direction='higher',
    log_path=os.path.join(td, 'log.jsonl'),
    working_dir='.',
)
t.init()

# Run actual tests on ourselves
r = t.run('$PYTHON -m pytest $CLI_DIR/tests/test_experiment.py -q --tb=no 2>&1 | tail -1')
assert r.success
entry = t.log(result=r, status='keep', description='self-test')
assert entry.primary_metric >= 0

# Verify persistence
t2 = ExperimentTracker.from_file(os.path.join(td, 'log.jsonl'))
assert len(t2.history) == 1

print('Self-tracking OK')
" 2>/dev/null; then
    award 10 "self-tracking works"
else
    fail_check "self-tracking"
fi

# 12c. Summary report is meaningful (5 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.improve import SelfImprover

td = tempfile.mkdtemp()
imp = SelfImprover(
    target_dir='$CLI_DIR',
    benchmark_command=\"echo 'METRIC score=100'\",
    metric_name='score',
    direction='higher',
    log_path=os.path.join(td, 'log.jsonl'),
)
r = imp.run_benchmark()
imp.log_improvement(r, 'keep', 'baseline')

s = imp.summary()
assert s['total_experiments'] == 1
assert s['kept'] == 1
assert s['best_metric'] == 100.0
assert s['name']
print(f'Summary: {s}')
" 2>/dev/null; then
    award 5 "meaningful summary report"
else
    fail_check "summary report"
fi

# ------------------------------------------------------------------
# 13. Documentation and TODOs (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Documentation ---"

# 13a. todos.txt exists with upstream notes (5 pts)
if [ -f "todos.txt" ] && grep -qi "flatmachines_cli\|flatagent\|upstream\|shim\|sdk" todos.txt 2>/dev/null; then
    award 5 "todos.txt has upstream notes"
else
    fail_check "todos.txt upstream notes"
fi

# 13b. Inspiration artifact exists (analysis of HyperAgents/autoresearch patterns) (10 pts)
if [ -f "autoresearch.context.md" ] && $PYTHON -c "
content = open('autoresearch.context.md').read()
# Must have substantial analysis, not just mentions
assert len(content) > 2000, f'Too short: {len(content)}'
sections = content.lower()
has_patterns = 'pattern' in sections or 'architecture' in sections
has_essence = 'essence' in sections or 'core' in sections
assert has_patterns and has_essence, 'Missing pattern analysis'
print('Context doc OK')
" 2>/dev/null; then
    award 10 "inspiration artifact (context doc)"
else
    fail_check "inspiration artifact"
fi

# 13c. autoresearch.md updated with what's been tried (5 pts)
if $PYTHON -c "
content = open('autoresearch.md').read()
assert 'What' in content and 'Tried' in content
assert len(content) > 1000
print('OK')
" 2>/dev/null; then
    award 5 "autoresearch.md maintained"
else
    fail_check "autoresearch.md"
fi

# 13d. No changes outside sdk/python/flatmachines_cli + notes (5 pts)
# Check that we haven't modified core SDK files
if ! git diff --name-only HEAD~3 2>/dev/null | grep -E "^sdk/python/(flatmachines|flatagents)/" | grep -v flatmachines_cli | grep -q .; then
    award 5 "no out-of-scope changes"
else
    fail_check "out-of-scope changes detected"
fi

phase3=$((score - phase1 - phase2))
echo ""
echo "Phase 3 subtotal: $phase3 / 100"

# ------------------------------------------------------------------
# Final
# ------------------------------------------------------------------
echo ""
echo "=== Score Summary ==="
echo "  Phase 1 (presence): $phase1 / 100"
echo "  Phase 2 (quality):  $phase2 / 100"
echo "  Phase 3 (readiness): $phase3 / 100"
echo "  capability_score = $score / 300"

# Count all passing tests
TEST_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --tb=no 2>&1 | tail -1)
test_count=$(echo "$TEST_RESULT" | grep -oP '\d+(?= passed)' || echo 0)
source_loc=$(wc -l "$CLI_DIR/flatmachines_cli/"*.py 2>/dev/null | tail -1 | awk '{print $1}')

echo "  test_count = $test_count"
echo "  source_loc = $source_loc"
echo ""

echo "METRIC capability_score=$score"
echo "METRIC test_count=$test_count"
echo "METRIC source_loc=$source_loc"
