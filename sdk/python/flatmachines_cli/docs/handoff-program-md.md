# Handoff: program.md Pattern

> **Status:** Self-improve loop works e2e with CLI flags. This doc specifies the shift to agent-driven discovery via `program.md`.

---

## What Changes

The user stops configuring the benchmark, metric, and direction via CLI flags. Instead:

1. User writes `program.md` in their project root describing the goal (what to optimize, not how)
2. `flatmachines improve .` — that's the entire CLI
3. The agent reads `program.md`, figures out how to measure progress, writes/discovers a benchmark
4. The agent writes scores to `.self_improve/score.json`
5. The archive reads scores from there for parent selection

---

## program.md

The user's guidance on what to optimize. NOT a benchmark specification — the agent figures out measurement. Inspired by [autoresearch](https://github.com/karpathy/autoresearch)'s `program.md`.

Example for a training script:

```markdown
# program

Get the lowest val_bpb on the validation set. `train.py` is the training script.
`prepare.py` is the fixed evaluation harness — don't modify it.
Simpler is better, all else equal.
```

Example for a web service:

```markdown
# program

Improve request throughput for the API server in `src/`.
Don't modify tests or the database schema.
```

Example for this SDK:

```markdown
# program

Get all tests passing and improve code quality.
Protected: `benchmark.sh`, `tests/**`.
```

If no `program.md` exists, the agent explores the codebase, reads the README, understands the vision and goals of the project, and brainstorms a material improvement — not anchored to previous improvements.

---

## Self-Referential Improvement

The agent's working directory includes the improvement infrastructure itself. The agent CAN edit:

- `config/agent.yml` — its own prompt
- `config/self_improve.yml` — the machine config
- `improve.py` — the hook actions
- `archive.py` — the archive logic

This is the HyperAgents pattern: the meta-agent improves the improvement loop. The scope is the full working directory, not just "application code."

---

## Agent Owns the Lifecycle

The agent owns the full experiment cycle within its tool loop:

1. Explore codebase, read `program.md`
2. Determine what to measure and how (write/discover a benchmark)
3. Run benchmark, establish baseline
4. Edit code
5. Run benchmark again
6. If improved: `git commit`. If not: `git checkout -- . && git clean -fd`
7. Write `.self_improve/score.json` with final score
8. Repeat

There is no external `evaluate` state in the machine. The machine handles ONLY infrastructure: worktree creation, archive storage, parent selection, cleanup.

---

## .self_improve/score.json

The agent writes this file after measuring results. The archive reads it.

```json
{
  "metric": "val_bpb",
  "value": 0.9934,
  "direction": "lower"
}
```

Fields:
- `metric` — name of what was measured (agent-determined)
- `value` — the number
- `direction` — `"higher"` or `"lower"` (agent-determined)

The agent can update this file multiple times during a generation. The archive reads the final state when archiving.

**Note on heterogeneous metrics:** If different generations use different metrics, parent selection degrades to effectively random (scores aren't comparable). In practice this is unlikely since `program.md` is fixed across generations, keeping the goal stable. Known limitation, not a blocker.

---

## Changes Required

### 1. CLI (`main.py`)

Drop required flags. The `improve` subcommand becomes:

```
flatmachines improve [target_dir]        # defaults to .
flatmachines improve . --generations 3   # multi-gen
```

`--benchmark`, `--metric`, `--direction` are removed. `--generations` and `--parent-selection` stay — they're infrastructure.

### 2. Machine (`self_improve.yml`)

Context drops `eval_spec`, `benchmark_command`, `metric_name`, `metric_direction`. No `evaluate` state. Input to the agent is just `working_dir`.

```yaml
improve:
  agent: coder
  tool_loop:
    max_turns: 30
    max_tool_calls: 100
    max_cost: 2.00
    tool_timeout: 120
    total_timeout: 600
  input:
    working_dir: "{{ context.worktree_path | default(context.working_dir) }}"
```

States: `start → select_parent → setup_worktree → improve → archive_generation → cleanup_worktree → outer_budget_check → done`

No `evaluate` state — the agent evaluates within its tool loop.

### 3. Agent (`agent.yml`)

System prompt documents the lifecycle contract:

```yaml
system: |
  You are an expert coding assistant. You have access to tools for reading files,
  writing files, executing bash commands, and making surgical edits.

  You own the full experiment lifecycle. You determine what to measure,
  write or discover benchmarks, run them, edit code, and evaluate results.
  Commit improvements with git. Revert failures with git checkout.
  Write your final score to .self_improve/score.json.

user: |
  Improve the code at {{ input.working_dir }}.
  Read program.md if it exists for guidance on what to optimize.
```

### 4. Archive scoring (`improve.py`)

`_extract_and_archive` reads `.self_improve/score.json` instead of running a benchmark:

```python
score_path = Path(wt_path) / ".self_improve" / "score.json"
if score_path.exists():
    data = json.loads(score_path.read_text())
    score = data.get("value")
    scores = {data.get("metric", "score"): score}
```

### 5. Parent selection direction

Store direction from `score.json` in archive entry metadata. `select_parent("score_child_prop")` reads direction and flips comparison when `"lower"`.

### 6. `EvaluationSpec` and `EvaluationRunner`

Remove from machine context and critical path. Keep classes for backward compat but they're utilities the agent can use if it chooses, not infrastructure.

---

## What Stays

- `--generations` and `--parent-selection` CLI flags
- Worktree isolation (auto-enabled for generations > 1)
- Archive with parent→child links, lineage tracking
- Diff/patch storage per generation
- `archive_summary.tsv` for agent context across generations
- Debug logging in tool loop

## What Goes

- `--benchmark`, `--metric`, `--direction` CLI flags
- `eval_spec` in machine context
- `evaluate` state in machine
- `EvaluationRunner` in archive action
- External benchmark execution in `_extract_and_archive`

---

## Sequencing

```
1. Remove evaluate state from self_improve.yml        ← 5 min
2. Update agent.yml system prompt (lifecycle contract) ← 5 min
3. Add score.json reading to _extract_and_archive      ← 15 min
4. Strip machine context to just working_dir           ← 10 min
5. Simplify CLI flags                                  ← 15 min
6. Handle direction in parent selection                ← 15 min
7. Update tests                                        ← 15 min
```

Total: ~80 minutes.
