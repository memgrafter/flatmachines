# Handoff: Closing the Outer Loop

> **Status:** Inner loop (autoresearch pattern) is solid and e2e verified with codex. Outer loop (HyperAgents pattern) has infrastructure built but is not usable end-to-end. This doc specifies what's needed to make it real.
>
> **Updated 2026-04-07:** Corrected after code review. Removed phantom `.self_improve/config.yml` loading path — the machine YAML (`self_improve.yml`) already accepts all outer loop knobs as `{{ input.X }}` templates. The gap is purely CLI flag wiring, not a new config system.

---

## What's Built vs What's Wired

| Component | Code exists | Exposed to user | Actually works e2e |
|-----------|------------|-----------------|-------------------|
| EvaluationSpec (firewall) | ✅ | ✅ via machine input | ✅ verified |
| Scoped edits | ✅ | ✅ via machine input | ✅ verified |
| Fail-fast checks | ✅ | ✅ via machine input | ✅ verified |
| Log-redirect-and-grep | ✅ | ✅ automatic | ✅ verified |
| Archive (all variants) | ✅ | ❌ no user path | ⚠️ stores entries but `parent_commit: None` without isolation |
| Parent selection | ✅ | ❌ `max_generations` hardcoded to 1, no CLI flag | ❌ |
| Worktree isolation | ✅ | ❌ `enable_isolation` not in CLI, never set to True | ❌ never activates |
| Diff/patch lineage | ✅ | ❌ depends on isolation | ❌ |
| Agent understands tree | ❌ | ❌ | ❌ prompt shows flat list, no branching context |

**The bottom line:** Setting `max_generations: 3` in the YAML without isolation just runs the inner loop 3× on the same codebase. There's no code divergence, no branching, no evolutionary search. It's `iterations: 9` with extra bookkeeping.

---

## 4 Changes to Close the Gap

### 1. Auto-enable isolation when `max_generations > 1`

In `_make_self_improve_handler` (main.py), auto-enable isolation when the user sets generations > 1:

```python
# In _make_self_improve_handler's inner handler function:
max_gen = context.get("max_generations", 1)
if isinstance(max_gen, str):
    max_gen = int(max_gen)
enable_isolation = max_gen > 1

improver = SelfImprover(
    ...
    enable_isolation=enable_isolation,
)
```

No separate `enable_isolation` flag needed. The contract is: `max_generations > 1` = tree search = isolation on.

**Requires:** The target dir must be a git repo. Error clearly if not.

### 2. Fix commit hash storage in `_extract_and_archive`

Currently `_extract_and_archive` stores `context.get("last_commit")` in metadata, but `_commit_inner` only sets `last_commit` when isolation is active. Even with isolation enabled (after fix #1), the final state of the worktree needs an explicit commit before extraction.

Fix: commit all changes in the worktree *inside* `_extract_and_archive`, before extracting the diff:

```python
def _extract_and_archive(self, context):
    generation = context.get("generation", 0)
    isolation = self._improver.isolation
    wt_path = context.get("worktree_path", self._improver.target_dir)

    # Commit everything before extracting so we have a real commit hash
    commit = None
    if isolation is not None:
        commit = isolation.commit_worktree(wt_path, f"gen-{generation} final")

    # Extract diff
    patch_file = ""
    if isolation is not None:
        patch_file = isolation.extract_diff(wt_path, generation)

    entry = self._improver.archive.add(
        ...
        metadata={"commit": commit, ...},
    )
```

Then in `_create_worktree`, branching from `parent_commit` gives the child generation the parent's actual code state — no need for `apply_patches`:

```python
parent_commit = context.get("parent_commit")  # From archive entry metadata
wt_path = isolation.create_worktree(generation, parent_commit)
# Branching from parent_commit already has the code — skip apply_patches
```

This is the difference between "all generations start from the same baseline" (useless) and "generation 3 builds on generation 1's improvements" (actual tree search).

### 3. Give the agent tree context

The agent prompt currently says "Read the archive summary" which is a flat TSV. For tree search, the agent needs to know:

- Which generation it's branching from and what that generation tried
- What sibling generations tried (and their scores)
- What the full lineage looks like

Add to `_select_parent` in `improve.py`:
```python
# Populate sibling context for the agent
parent = archive.get(context["parent_id"])
if parent:
    siblings = [archive.get(cid) for cid in parent.children]
    context["parent_score"] = parent.score
    context["sibling_summary"] = [
        {"id": s.generation_id, "score": s.score,
         "description": s.metadata.get("description", "")}
        for s in siblings if s
    ]
```

Add to the `improve` state prompt in `self_improve.yml`:
```
## Lineage
You are generation {{ context.generation }}, branching from generation {{ context.parent_id }}.
Parent score: {{ context.parent_score }}

## What's been tried (other branches from same parent)
{% for sibling in context.sibling_summary %}
- Gen {{ sibling.id }}: {{ sibling.description }} → score {{ sibling.score }}
{% endfor %}

## Full archive
cat .self_improve/archive_summary.tsv
```

### 4. Add CLI flags for outer loop

The machine YAML already accepts `max_generations` and `parent_selection` as input. Just add CLI flags and pass them through.

In `main.py`, add to the `improve` subparser:

```python
improve_parser.add_argument(
    "--generations", "-g",
    type=int,
    default=1,
    help="Number of generations (1 = linear hill-climbing, >1 = tree search with worktree isolation)",
)
improve_parser.add_argument(
    "--parent-selection",
    default="best",
    choices=["best", "score_child_prop", "random"],
    help="Parent selection strategy for multi-generation search (default: best)",
)
```

Pass them as machine input in the `--run` path:

```python
result = _run_async(run_once(
    ...
    max_generations=args.generations,
    parent_selection=args.parent_selection,
))
```

That's it — the machine YAML templates (`{{ input.max_generations }}`, `{{ input.parent_selection }}`) already handle the rest.

---

## Sequencing

```
1. Auto-enable isolation for max_generations>1  ← 15 min, 5 lines in main.py
2. Fix commit storage in _extract_and_archive   ← 20 min, commit before extract
3. Agent tree context in prompt + _select_parent ← 30 min, hooks + YAML prompt
4. CLI flags (--generations, --parent-selection) ← 15 min, argparse + pass-through
```

Total: ~80 minutes. After this, `--generations 3 --parent-selection score_child_prop` does real evolutionary tree search with code divergence, and the agent understands it's exploring branches.

---

## What This Does NOT Cover

- **Docker isolation** — worktrees are sufficient. Docker is a future `IsolationBackend`.
- **Self-referential improvement** — Phase 3, requires the outer loop to be battle-tested first.
- **Ensemble** — requires stored predictions, not just scores. Phase 3.
- **Multi-domain eval** — most users have one benchmark. Phase 3.
- **`.self_improve/config.yml` convenience wrapper** — design-improve-init.md describes a flat YAML the user edits instead of passing CLI flags. Nice-to-have, not a prerequisite. The machine YAML is the config.

---

## How to Verify

Run with `--generations 3` on the test project:

```bash
flatmachines improve /tmp/converged-test \
  --benchmark "bash benchmark.sh" \
  --metric speed_ms \
  --direction lower \
  --generations 3 \
  --parent-selection best \
  --git \
  --run
```

Expected:
1. Gen 0: agent optimizes fibonacci → scores ~6ms
2. Gen 1 (child of 0): agent optimizes multiply → scores ~3ms  
3. Gen 2 (child of 1 or 0, depending on selection): tries something else

Archive should show a tree, not a line. Different generations should have different code changes. `git worktree list` during the run should show isolated worktrees.
