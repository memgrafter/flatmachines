# Handoff: program.md Pattern

> **Status:** Self-improve loop works e2e with CLI flags (`--benchmark`, `--metric`, `--direction`). This doc specifies the shift to agent-driven discovery via `program.md`.

---

## What Changes

The user stops configuring the benchmark, metric, and direction via CLI flags. Instead:

1. User writes `program.md` in their project root describing what to optimize
2. `flatmachines improve .` — that's the entire CLI
3. The agent reads `program.md`, figures out the benchmark, metric, and direction
4. The agent writes scores to `.self_improve/score.json`
5. The archive reads scores from there for parent selection

---

## program.md

The user's only interface. A prose file in the project root that tells the agent what to do. Inspired by [autoresearch](https://github.com/karpathy/autoresearch)'s `program.md`.

Example for a training script:

```markdown
# program

Optimize `train.py` to get the lowest val_bpb. Run it with `uv run train.py`.
The script trains for a fixed 5-minute budget. Output includes `val_bpb: X.XXXXX`.

Don't modify `prepare.py` — it's the fixed evaluation harness.
Simpler is better, all else equal.
```

Example for a web service:

```markdown
# program

Improve request throughput for the API server in `src/`.
Benchmark: `wrk -t4 -c100 -d10s http://localhost:8080/api/items`
The metric is requests/sec from wrk output.

Don't modify tests or the database schema.
```

Example for this SDK:

```markdown
# program

Increase the number of passing tests. Run `bash benchmark.sh` to measure.
Editable: `flatmachines_cli/**/*.py`, `config/**/*.yml`.
Protected: `benchmark.sh`, `tests/**`.
```

If no `program.md` exists, the agent explores the codebase and decides what to do.

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
- `metric` — name of what was measured
- `value` — the number
- `direction` — `"higher"` or `"lower"` (agent determines this)

The agent can update this file multiple times during a generation. The archive reads the final state when archiving.

---

## Changes Required

### 1. CLI (`main.py`)

Drop required flags. The `improve` subcommand becomes:

```
flatmachines improve [target_dir]        # defaults to .
flatmachines improve . --generations 3   # multi-gen
```

`--benchmark`, `--metric`, `--direction` become optional overrides that get written into a generated `program.md` if provided (for backward compat). `--generations` and `--parent-selection` stay — they're infrastructure.

### 2. Machine (`self_improve.yml`)

Context drops `eval_spec`, `benchmark_command`, `metric_name`, `metric_direction`. Input to the agent is just `working_dir`.

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

### 3. Agent (`agent.yml`)

```yaml
user: |
  Improve the code at {{ input.working_dir }}.
  Read program.md if it exists for instructions.
```

That's it. The agent reads `program.md` via bash/read tools, discovers the benchmark, runs it, edits code, measures again.

### 4. Archive scoring (`improve.py`)

`_extract_and_archive` reads `.self_improve/score.json` instead of running a benchmark:

```python
def _extract_and_archive(self, context):
    ...
    # Read agent-written score
    score = None
    scores = {}
    score_path = Path(wt_path) / ".self_improve" / "score.json"
    if score_path.exists():
        try:
            data = json.loads(score_path.read_text())
            score = data.get("value")
            scores = {data.get("metric", "score"): score}
            # Store direction for parent selection
            context["_score_direction"] = data.get("direction", "higher")
        except (json.JSONDecodeError, KeyError):
            pass

    entry = self._improver.archive.add(
        parent_id=context.get("parent_id"),
        patch_file=patch_file,
        score=score,
        scores=scores,
        ...
    )
```

### 5. Parent selection direction

`Archive.select_parent("score_child_prop")` currently assumes higher is better. Needs to respect direction from `score.json`. Store direction in archive metadata, flip comparison when direction is "lower".

### 6. `EvaluationSpec` and `EvaluationRunner`

These become optional utilities the agent can use if it wants, not required infrastructure. Remove them from the machine context. Keep the classes for backward compat but they're no longer in the critical path.

---

## What Stays

- `--generations` and `--parent-selection` CLI flags
- Worktree isolation (auto-enabled for generations > 1)
- Archive with parent→child links, lineage tracking
- Diff/patch storage per generation
- `archive_summary.tsv` for agent context across generations
- Debug logging in tool loop

---

## What Goes

- `--benchmark` (required → optional/removed)
- `--metric` (required → removed)
- `--direction` (required → removed)
- `eval_spec` in machine context
- `EvaluationRunner` in archive action
- External benchmark execution in `_extract_and_archive`

---

## Backward Compat

If user passes `--benchmark "bash bench.sh" --metric score --direction higher`, generate a `program.md` with those instructions and proceed as normal. The agent reads it and follows it. Same result, no special code path.

---

## Sequencing

```
1. Add score.json reading to _extract_and_archive   ← 15 min
2. Strip machine context to just working_dir         ← 10 min
3. Update agent.yml prompt                           ← 5 min
4. Simplify CLI flags                                ← 15 min
5. Handle direction in parent selection              ← 15 min
6. Backward compat: flags → program.md generation    ← 15 min
```

Total: ~75 minutes.
