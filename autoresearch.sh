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

# ==================================================================
echo ""
echo "=== Phase 4: Autonomous Loop Features (100 pts) ==="
# ==================================================================

# ------------------------------------------------------------------
# 14. Git integration (30 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Git Integration ---"

# 14a. ExperimentTracker has git operations (10 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
has_commit = hasattr(t, 'git_commit') or hasattr(t, 'commit_changes')
has_revert = hasattr(t, 'git_revert') or hasattr(t, 'revert_changes') or hasattr(t, 'git_reset')
assert has_commit, 'no git commit method'
assert has_revert, 'no git revert method'
print('OK')
" 2>/dev/null; then
    award 10 "tracker has git commit/revert"
else
    fail_check "tracker git operations"
fi

# 14b. Git operations actually work (10 pts)
if $PYTHON -c "
import tempfile, os, subprocess
from flatmachines_cli.experiment import ExperimentTracker

with tempfile.TemporaryDirectory() as td:
    # Set up a git repo
    subprocess.run(['git', 'init'], cwd=td, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=td, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=td, capture_output=True)
    
    # Create initial file and commit
    (open(os.path.join(td, 'test.txt'), 'w')).write('initial')
    subprocess.run(['git', 'add', '.'], cwd=td, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'initial'], cwd=td, capture_output=True)
    
    t = ExperimentTracker(
        log_path=os.path.join(td, 'log.jsonl'),
        working_dir=td,
    )
    t.init()
    
    # Make a change
    (open(os.path.join(td, 'test.txt'), 'w')).write('modified')
    
    # Commit
    committed = t.git_commit('test commit')
    assert committed, 'commit failed'
    
    # Verify the commit exists
    result = subprocess.run(['git', 'log', '--oneline', '-1'], cwd=td, capture_output=True, text=True)
    assert 'test commit' in result.stdout
    
    # Make another change
    (open(os.path.join(td, 'test.txt'), 'w')).write('bad change')
    subprocess.run(['git', 'add', '.'], cwd=td, capture_output=True)
    
    # Revert
    reverted = t.git_revert()
    assert reverted, 'revert failed'
    
    # Verify reverted
    content = open(os.path.join(td, 'test.txt')).read()
    assert content == 'modified', f'Expected modified, got: {content}'
    
    print('Git ops OK')
" 2>/dev/null; then
    award 10 "git commit/revert work"
else
    fail_check "git commit/revert"
fi

# 14c. log_result integrates with git (keep=commit, discard=revert) (10 pts)
if $PYTHON -c "
import tempfile, os, subprocess
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

with tempfile.TemporaryDirectory() as td:
    subprocess.run(['git', 'init'], cwd=td, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=td, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=td, capture_output=True)
    open(os.path.join(td, 'f.txt'), 'w').write('v1')
    subprocess.run(['git', 'add', '.'], cwd=td, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'v1'], cwd=td, capture_output=True)
    
    t = ExperimentTracker(
        log_path=os.path.join(td, 'log.jsonl'),
        working_dir=td,
        git_enabled=True,
    )
    t.init()
    
    # Simulate improvement: change file, log as keep
    open(os.path.join(td, 'f.txt'), 'w').write('v2')
    r = ExperimentResult(command='t', exit_code=0, stdout='', stderr='',
                        duration_s=1.0, success=True)
    t.log(result=r, status='keep', description='improvement')
    
    # Verify committed
    result = subprocess.run(['git', 'log', '--oneline'], cwd=td, capture_output=True, text=True)
    assert 'improvement' in result.stdout or len(result.stdout.strip().split(chr(10))) >= 2
    
    # Simulate regression: change file, log as discard
    open(os.path.join(td, 'f.txt'), 'w').write('v3-bad')
    subprocess.run(['git', 'add', '.'], cwd=td, capture_output=True)
    t.log(result=r, status='discard', description='regression')
    
    # Verify reverted
    content = open(os.path.join(td, 'f.txt')).read()
    assert content == 'v2', f'Expected v2, got: {content}'
    
    print('Git integration OK')
" 2>/dev/null; then
    award 10 "log_result git integration (keep=commit, discard=revert)"
else
    fail_check "log_result git integration"
fi

# ------------------------------------------------------------------
# 15. Confidence scoring (20 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Confidence Scoring ---"

# 15a. confidence_score method exists (10 pts)
if $PYTHON -c "
from flatmachines_cli.experiment import ExperimentTracker
t = ExperimentTracker.__new__(ExperimentTracker)
assert hasattr(t, 'confidence_score') or hasattr(t, 'confidence')
print('OK')
" 2>/dev/null; then
    award 10 "confidence_score method exists"
else
    fail_check "confidence_score method"
fi

# 15b. confidence_score returns meaningful values (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

with tempfile.TemporaryDirectory() as td:
    t = ExperimentTracker(
        direction='higher',
        log_path=os.path.join(td, 'log.jsonl'),
    )
    t.init()
    
    # Not enough data
    c = t.confidence_score()
    assert c is None, f'Expected None with no data, got {c}'
    
    # Add baseline results (noise)
    r = ExperimentResult(command='t', exit_code=0, stdout='', stderr='', duration_s=1.0, success=True)
    for v in [100.0, 101.0, 99.0, 100.5, 100.2]:
        t.log(result=r, status='keep', primary_metric=v)
    
    # Add a real improvement
    t.log(result=r, status='keep', primary_metric=110.0)
    
    c = t.confidence_score()
    assert c is not None, 'Expected confidence score'
    assert c > 1.0, f'Expected >1.0x for clear improvement, got {c}'
    
    print(f'Confidence: {c:.1f}x')
" 2>/dev/null; then
    award 10 "confidence_score returns meaningful values"
else
    fail_check "confidence_score values"
fi

# ------------------------------------------------------------------
# 16. Enhanced improve command (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Enhanced Improve ---"

# 16a. SelfImprover uses git when available (10 pts)
if $PYTHON -c "
from flatmachines_cli.improve import SelfImprover
import inspect
src = inspect.getsource(SelfImprover)
has_git = 'git' in src.lower()
print(f'git refs: {has_git}')
assert has_git, 'SelfImprover has no git awareness'
" 2>/dev/null; then
    award 10 "SelfImprover is git-aware"
else
    fail_check "SelfImprover git-aware"
fi

# 16b. Tests for git integration (10 pts)
GIT_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "git" 2>/dev/null | grep -c "test_" || true)
GIT_TESTS=${GIT_TESTS:-0}
if [ "$GIT_TESTS" -ge 3 ]; then
    award 10 "git integration tests ($GIT_TESTS)"
elif [ "$GIT_TESTS" -ge 1 ]; then
    award 5 "git integration tests ($GIT_TESTS, want ≥3)"
else
    fail_check "git integration tests"
fi

# 16c. Tests for confidence scoring (5 pts)
CONF_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "confidence" 2>/dev/null | grep -c "test_" || true)
CONF_TESTS=${CONF_TESTS:-0}
if [ "$CONF_TESTS" -ge 2 ]; then
    award 5 "confidence scoring tests ($CONF_TESTS)"
elif [ "$CONF_TESTS" -ge 1 ]; then
    award 3 "confidence scoring tests ($CONF_TESTS, want ≥2)"
else
    fail_check "confidence scoring tests"
fi

# ------------------------------------------------------------------
# 17. Robustness (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Robustness ---"

# 17a. All tests still pass (15 pts)
ALL_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --tb=no 2>&1 | tail -1)
ALL_FAILED=$(echo "$ALL_RESULT" | grep -oP '\d+(?= failed)' || echo 0)
ALL_PASSED=$(echo "$ALL_RESULT" | grep -oP '\d+(?= passed)' || echo 0)
if [ "${ALL_FAILED:-0}" = "0" ] && [ "${ALL_PASSED:-0}" -gt 0 ]; then
    award 15 "all $ALL_PASSED tests pass"
else
    fail_check "test failures: $ALL_FAILED"
fi

# 17b. No new warnings in imports (5 pts)
IMPORT_WARNINGS=$($PYTHON -W error -c "
import flatmachines_cli
from flatmachines_cli.experiment import ExperimentTracker
from flatmachines_cli.improve import SelfImprover
" 2>&1 | grep -c "Warning\|Error" || true)
if [ "${IMPORT_WARNINGS:-0}" = "0" ]; then
    award 5 "clean imports (no warnings)"
else
    fail_check "import warnings ($IMPORT_WARNINGS)"
fi

# 17c. Source files have docstrings (5 pts)
if $PYTHON -c "
from flatmachines_cli import experiment, improve
assert experiment.__doc__, 'experiment.py missing module docstring'
assert improve.__doc__, 'improve.py missing module docstring'
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult, parse_metrics
assert ExperimentTracker.__doc__
assert ExperimentResult.__doc__
assert parse_metrics.__doc__
from flatmachines_cli.improve import SelfImprover, SelfImproveHooks
assert SelfImprover.__doc__
assert SelfImproveHooks.__doc__
print('Docs OK')
" 2>/dev/null; then
    award 5 "all classes/functions have docstrings"
else
    fail_check "missing docstrings"
fi

phase4=$((score - phase1 - phase2 - phase3))
echo ""
echo "Phase 4 subtotal: $phase4 / 100"

# ==================================================================
echo ""
echo "=== Phase 5: Production Polish (100 pts) ==="
# ==================================================================

# ------------------------------------------------------------------
# 18. Profiles configuration (20 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Profiles ---"

PROFILES="$CLI_DIR/config/profiles.yml"

# 18a. profiles.yml exists and is valid flatprofiles (10 pts)
if [ -f "$PROFILES" ] && $PYTHON -c "
import yaml
with open('$PROFILES') as f:
    config = yaml.safe_load(f)
assert config['spec'] == 'flatprofiles'
profiles = config['data']['model_profiles']
assert 'default' in profiles
assert profiles['default'].get('provider')
assert profiles['default'].get('name')
print(f'{len(profiles)} profile(s)')
" 2>/dev/null; then
    award 10 "profiles.yml valid with default profile"
else
    fail_check "profiles.yml"
fi

# 18b. Multiple profiles for adapter flexibility (10 pts)
if [ -f "$PROFILES" ] && $PYTHON -c "
import yaml
with open('$PROFILES') as f:
    config = yaml.safe_load(f)
profiles = config['data']['model_profiles']
assert len(profiles) >= 2, f'Only {len(profiles)} profile(s)'
# Check different providers are represented
providers = set(p.get('provider', '') for p in profiles.values())
print(f'Providers: {providers}')
" 2>/dev/null; then
    award 10 "multiple profiles (adapter flexibility)"
else
    fail_check "multiple profiles"
fi

# ------------------------------------------------------------------
# 19. Validation API (25 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Validation API ---"

# 19a. validate_self_improve_config exists and importable (5 pts)
if $PYTHON -c "from flatmachines_cli.improve import validate_self_improve_config; print('OK')" 2>/dev/null; then
    award 5 "validate_self_improve_config importable"
else
    fail_check "validate_self_improve_config"
fi

# 19b. Validates built-in config successfully (10 pts)
if $PYTHON -c "
from flatmachines_cli.improve import validate_self_improve_config
result = validate_self_improve_config()
assert result['valid'], f'Errors: {result[\"errors\"]}'
assert result['info']['state_count'] >= 5
assert result['info']['agent_count'] >= 1
assert result['info']['has_profiles'] is True
print(f'Valid: {result[\"info\"][\"name\"]} ({result[\"info\"][\"state_count\"]} states)')
" 2>/dev/null; then
    award 10 "built-in config validates"
else
    fail_check "built-in config validation"
fi

# 19c. Catches errors in bad configs (10 pts)
if $PYTHON -c "
import tempfile, os, yaml
from flatmachines_cli.improve import validate_self_improve_config

td = tempfile.mkdtemp()

# Missing file
r = validate_self_improve_config(os.path.join(td, 'nope.yml'))
assert not r['valid']

# Wrong spec
bad = os.path.join(td, 'bad.yml')
open(bad, 'w').write(yaml.dump({'spec': 'wrong', 'data': {'states': {}}}))
r = validate_self_improve_config(bad)
assert not r['valid']

# Missing states
minimal = os.path.join(td, 'minimal.yml')
open(minimal, 'w').write(yaml.dump({
    'spec': 'flatmachine',
    'data': {'states': {'start': {'type': 'initial'}, 'done': {'type': 'final'}}}
}))
r = validate_self_improve_config(minimal)
assert not r['valid']
assert any('analyze' in e.lower() for e in r['errors'])

print('Error detection OK')
" 2>/dev/null; then
    award 10 "catches errors in bad configs"
else
    fail_check "error detection"
fi

# ------------------------------------------------------------------
# 20. Stress test persistence (20 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Stress Persistence ---"

# 20a. 100 entries roundtrip (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

td = tempfile.mkdtemp()
log = os.path.join(td, 'log.jsonl')
t = ExperimentTracker(name='stress', log_path=log)
t.init()

r = ExperimentResult(command='b', exit_code=0, stdout='', stderr='', duration_s=0.1, success=True)
for i in range(100):
    t.log(result=r, status='keep' if i%3==0 else 'discard', primary_metric=float(i), description=f'r{i}')

assert len(t.history) == 100

t2 = ExperimentTracker.from_file(log)
assert len(t2.history) == 100
assert t2.history[99].experiment_id == 100
assert t2.history[0].description == 'r0'

print('100 entries OK')
" 2>/dev/null; then
    award 10 "100 entries roundtrip"
else
    fail_check "100 entries roundtrip"
fi

# 20b. File size reasonable (10 pts)
if $PYTHON -c "
import tempfile, os
from flatmachines_cli.experiment import ExperimentTracker, ExperimentResult

td = tempfile.mkdtemp()
log = os.path.join(td, 'log.jsonl')
t = ExperimentTracker(log_path=log)
t.init()
r = ExperimentResult(command='b', exit_code=0, stdout='', stderr='', duration_s=0.1, success=True)
for i in range(100):
    t.log(result=r, status='keep', primary_metric=float(i))

size_kb = os.path.getsize(log) / 1024
assert size_kb < 100, f'Too large: {size_kb:.1f}KB'
print(f'Size: {size_kb:.1f}KB')
" 2>/dev/null; then
    award 10 "persistence file size reasonable"
else
    fail_check "file size"
fi

# ------------------------------------------------------------------
# 21. Validation + profiles tests (20 pts)
# ------------------------------------------------------------------
echo ""
echo "--- Phase 5 Tests ---"

# 21a. Validation tests exist and pass (10 pts)
VAL_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "validate_config" 2>/dev/null | grep -c "test_" || true)
VAL_TESTS=${VAL_TESTS:-0}
if [ "$VAL_TESTS" -ge 5 ]; then
    VAL_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/test_validate_config.py" -q --tb=line 2>&1) || true
    VAL_FAILED=$(echo "$VAL_RESULT" | grep -oP '\d+(?= failed)' || echo 0)
    if [ "${VAL_FAILED:-0}" = "0" ]; then
        award 10 "validation tests pass ($VAL_TESTS)"
    else
        fail_check "validation tests: $VAL_FAILED failed"
    fi
else
    fail_check "validation tests ($VAL_TESTS, want ≥5)"
fi

# 21b. Exported in __init__.py (5 pts)
if $PYTHON -c "
from flatmachines_cli import validate_self_improve_config
print('OK')
" 2>/dev/null; then
    award 5 "validate function exported"
else
    fail_check "validate function export"
fi

# 21c. All tests still pass (no regressions) (10 pts)
ALL5_RESULT=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --tb=no 2>&1 | tail -1)
ALL5_FAILED=$(echo "$ALL5_RESULT" | grep -oP '\d+(?= failed)' || echo 0)
ALL5_PASSED=$(echo "$ALL5_RESULT" | grep -oP '\d+(?= passed)' || echo 0)
if [ "${ALL5_FAILED:-0}" = "0" ] && [ "${ALL5_PASSED:-0}" -gt 0 ]; then
    award 10 "all $ALL5_PASSED tests pass (no regressions)"
else
    fail_check "test regressions: $ALL5_FAILED failed"
fi

# 21d. Profiles tests exist (5 pts)
PROF_TESTS=$($PYTHON -m pytest "$CLI_DIR/tests/" -q --co -k "profiles" 2>/dev/null | grep -c "test_" || true)
PROF_TESTS=${PROF_TESTS:-0}
if [ "$PROF_TESTS" -ge 2 ]; then
    award 5 "profiles tests ($PROF_TESTS)"
else
    fail_check "profiles tests ($PROF_TESTS, want ≥2)"
fi

# 21e. Validate function has docstring (5 pts)
if $PYTHON -c "
from flatmachines_cli.improve import validate_self_improve_config
assert validate_self_improve_config.__doc__
assert len(validate_self_improve_config.__doc__) > 100
print('Docstring OK')
" 2>/dev/null; then
    award 5 "validate function docstring"
else
    fail_check "validate docstring"
fi

phase5=$((score - phase1 - phase2 - phase3 - phase4))
echo ""
echo "Phase 5 subtotal: $phase5 / 100"

# ------------------------------------------------------------------
# Final
# ------------------------------------------------------------------
echo ""
echo "=== Score Summary ==="
echo "  Phase 1 (presence): $phase1 / 100"
echo "  Phase 2 (quality):  $phase2 / 100"
echo "  Phase 3 (readiness): $phase3 / 100"
echo "  Phase 4 (autonomous): $phase4 / 100"
echo "  Phase 5 (polish):   $phase5 / 100"
echo "  capability_score = $score / 500"

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
