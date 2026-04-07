# Handoff: Closing the Outer Loop

> **Status:** Inner loop (autoresearch pattern) is solid and e2e verified with codex. Outer loop (HyperAgents pattern) has infrastructure built but is not usable end-to-end. This doc specifies what's needed to make it real.

---

## What's Built vs What's Wired

| Component | Code exists | Exposed to user | Actually works e2e |
|-----------|------------|-----------------|-------------------|
| EvaluationSpec (firewall) | ✅ | ✅ via config.yml | ✅ verified |
| Scoped edits | ✅ | ✅ via config.yml | ✅ verified |
| Fail-fast checks | ✅ | ✅ via config.yml | ✅ verified |
| Log-redirect-and-grep | ✅ | ✅ automatic | ✅ verified |
| Archive (all variants) | ✅ | ❌ no user path | ⚠️ stores entries but no branching without isolation |
| Parent selection | ✅ | ❌ `generations` knob exists but meaningless without isolation | ❌ |
| Worktree isolation | ✅ | ❌ `enable_isolation` not in CLI or config | ❌ never activates |
| Diff/patch lineage | ✅ | ❌ depends on isolation | ❌ |
| Agent understands tree | ❌ | ❌ | ❌ prompt shows flat list, no branching context |

**The bottom line:** Setting `generations: 5` without isolation just runs the inner loop 5× on the same codebase. There's no code divergence, no branching, no evolutionary search. It's `iterations: 15` with extra bookkeeping.

---

## 4 Changes to Close the Gap

### 1. Enable isolation by default when `generations > 1`

In `_make_self_improve_handler` (main.py) or in `ConvergedSelfImproveHooks`, auto-enable isolation when the user sets generations > 1:

```python
# If user wants multi-generation, they need isolation
if context.get("max_generations", 1) > 1:
    enable_isolation = True
```

Expose in config.yml:
```yaml
generations: 3          # >1 automatically enables worktree isolation
```

No separate `enable_isolation` flag needed. The contract is: `generations > 1` = tree search = isolation on.

**Requires:** The target dir must be a git repo. Error clearly if not.

### 2. Apply parent patches in worktree

Currently `_create_worktree` creates a worktree and calls `apply_patches`, but the parent's commit hash is often `None` because `_extract_and_archive` doesn't reliably store it. Fix:

- After the inner loop completes, commit all kept changes in the worktree
- Store that commit hash in the archive entry metadata
- When creating a new worktree for a child generation, branch from the parent's commit

This is the difference between "all generations start from the same baseline" (useless) and "generation 3 builds on generation 1's improvements" (actual tree search).

```python
def _extract_and_archive(self, context):
    # ... existing code ...
    # Commit everything in the worktree before extracting
    commit = isolation.commit_worktree(wt_path, f"gen-{generation} final")
    # Store commit in archive entry
    entry = self._improver.archive.add(
        ...
        metadata={"commit": commit, ...},
    )
```

Then in `_create_worktree`:
```python
parent_commit = context.get("parent_commit")  # From archive entry metadata
wt_path = isolation.create_worktree(generation, parent_commit)
# No need to apply_patches — branching from parent_commit already has the code
```

### 3. Give the agent tree context

The agent prompt currently says "Read the archive summary" which is a flat TSV. For tree search, the agent needs to know:

- Which generation it's branching from and what that generation tried
- What sibling generations tried (and their scores)
- What the full lineage looks like

Add to the improve state prompt:
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

Add to `_select_parent`:
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

### 4. Expose in config.yml and CLI

In the `--init` scaffolded config:
```yaml
# Outer loop: evolutionary search
# 1 = linear hill-climbing (safe default)
# >1 = tree search with branching (requires git repo)
generations: 1

# Parent selection (only matters when generations > 1)
# "best" = always improve the best variant
# "score_child_prop" = explore diverse branches (recommended for generations > 3)
parent_selection: best
```

In CLI, `--run` reads these from config.yml and passes as machine input. The machine YAML uses plain ints (already done).

---

## Sequencing

```
1. Fix commit storage in archive          ← 30 min, enables real branching
2. Auto-enable isolation for generations>1 ← 15 min, wiring
3. Agent tree context in prompt            ← 30 min, prompt + select_parent
4. Expose in config.yml scaffold           ← 15 min, scaffold_self_improve
```

Total: ~90 minutes. After this, `generations: 3` with `parent_selection: score_child_prop` does real evolutionary tree search with code divergence, and the agent understands it's exploring branches.

---

## What This Does NOT Cover

- **Docker isolation** — worktrees are sufficient. Docker is a future `IsolationBackend`.
- **Self-referential improvement** — Phase 3, requires the outer loop to be battle-tested first.
- **Ensemble** — requires stored predictions, not just scores. Phase 3.
- **Multi-domain eval** — most users have one benchmark. Phase 3.

---

## How to Verify

Run with `generations: 3` on the test project:

```bash
flatmachines improve /tmp/converged-test \
  --benchmark "bash benchmark.sh" \
  --metric speed_ms \
  --direction lower \
  --run
```

Expected:
1. Gen 0: agent optimizes fibonacci → scores ~6ms
2. Gen 1 (child of 0): agent optimizes multiply → scores ~3ms  
3. Gen 2 (child of 1 or 0, depending on selection): tries something else

Archive should show a tree, not a line. Different generations should have different code changes. `git worktree list` during the run should show isolated worktrees.
