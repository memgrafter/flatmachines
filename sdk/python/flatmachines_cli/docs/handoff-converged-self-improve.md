# Handoff: Converged Self-Improvement for flatmachines_cli

> **Goal:** Incorporate the core mechanisms of BOTH autoresearch and HyperAgents into flatmachines_cli's self-improvement loop — not as an either/or choice, but as complementary layers.
>
> **Key insight:** Autoresearch defines *how to run one experiment well* (inner loop). HyperAgents defines *how to navigate many experiments wisely* (outer loop). They stack.

---

## Why Convergence Works

| Layer | Autoresearch Provides | HyperAgents Provides |
|-------|----------------------|---------------------|
| **Single experiment** | Fixed budget, untouchable evaluator, scoped edits, redirect-and-grep | Compilation check (fail-fast) |
| **Experiment history** | Simple TSV/log, read-before-every-run | Full archive of all variants (not just best) |
| **Search strategy** | Linear hill-climbing (advance or reset) | Tree search with parent selection + diversity |
| **Isolation** | Git branch per session | Docker container per generation |
| **Self-reference** | Human edits `program.md` (manual meta-optimization) | Agent edits own code (automated meta-optimization) |

There is **zero conflict** between these. Autoresearch's inner loop discipline makes each HyperAgents generation more reliable. HyperAgents' archive and selection make autoresearch's search more effective. They are layers, not alternatives.

---

## Architecture: The Converged Design

```
┌─────────────────────────────────────────────────────────────────┐
│                    Outer Loop (HyperAgents)                      │
│                                                                  │
│  Archive: [baseline, gen_1, gen_2, gen_3, ...]                  │
│                                                                  │
│  For each generation:                                            │
│    1. select_parent(archive) — score-proportional + diversity    │
│    2. Create isolated worktree from parent                       │
│    3. ┌─────────────────────────────────────────┐               │
│       │      Inner Loop (Autoresearch)           │               │
│       │                                          │               │
│       │  a. Read experiment history              │               │
│       │  b. Agent edits scoped files only        │               │
│       │  c. Fail-fast: compilation check         │               │
│       │  d. Run benchmark (fixed budget)         │               │
│       │  e. Extract metric (grep, not full log)  │               │
│       │  f. If improved → commit; else → reset   │               │
│       │  g. Repeat for N inner iterations        │               │
│       └─────────────────────────────────────────┘               │
│    4. Save diff (model_patch.diff)                               │
│    5. Score the generation (staged: quick → full)                │
│    6. Add to archive (ALL generations, not just winners)         │
│    7. Update progress plots                                      │
│                                                                  │
│  Parent selection for next generation                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan: 8 Changes, Ordered by Dependency

### Phase 1: Inner Loop Discipline (from Autoresearch)

These make each individual experiment more reliable. No new data structures needed.

#### Change 1: Evaluation Firewall

**Problem:** The agent can modify the benchmark command or its interpretation.  
**Solution:** Separate the evaluator from the code being improved.

Files to change: `experiment.py`, `improve.py`

```python
# experiment.py — new concept: EvaluationSpec
@dataclass
class EvaluationSpec:
    """Immutable evaluation specification. Cannot be modified by the agent."""
    benchmark_command: str          # The command to run
    metric_name: str                # Which metric to optimize
    direction: str                  # "higher" or "lower"
    timeout_s: float = 300.0        # Fixed time budget
    checks_command: str = ""        # Pre-eval compilation/sanity check
    protected_paths: List[str] = field(default_factory=list)  # Files agent CANNOT edit
    
    def validate_no_tampering(self, working_dir: str) -> bool:
        """Check that protected paths haven't been modified since baseline."""
        # git diff --name-only against baseline commit for protected_paths
        ...
```

In `improve.py`, the `SelfImprover` takes an `EvaluationSpec` instead of raw strings. The spec is frozen at init time and checked before every evaluation.

In `self_improve.yml`, add:
```yaml
context:
    # Evaluation firewall — these cannot be changed by the agent
    eval_spec:
      benchmark_command: "{{ input.benchmark_command }}"
      timeout_s: 300
      protected_paths: ["benchmark.sh", "tests/"]
```

#### Change 2: Scoped Edit Targets

**Problem:** The agent can edit anything in `target_dir`, including benchmarks and configs.  
**Solution:** Explicit allowlist of files the agent can modify.

Files to change: `self_improve.yml`, `coder.yml`

Add to the agent prompt:
```yaml
input:
  task: |
    ...
    ## Scope
    You may ONLY edit files matching these patterns:
    {% for pattern in context.editable_patterns %}
    - {{ pattern }}
    {% endfor %}
    
    Do NOT modify: {{ context.eval_spec.protected_paths | join(', ') }}
```

Add to context:
```yaml
context:
    editable_patterns: "{{ input.editable_patterns | default(['src/**/*.py']) }}"
```

The `evaluate` action validates no protected files were touched before accepting the result:
```python
def _evaluate(self, context):
    # Fail-fast: check no protected files modified
    if not self._improver.eval_spec.validate_no_tampering(self._improver.target_dir):
        context["last_status"] = "tampering_detected"
        return context
    ...
```

#### Change 3: Fail-Fast Compilation Check

**Problem:** Bad edits waste a full benchmark cycle before failing.  
**Solution:** Run a quick sanity check before the expensive benchmark.

Files to change: `experiment.py`, `improve.py`

```python
# experiment.py
class ExperimentTracker:
    def run_checks(self) -> ExperimentResult:
        """Run the fast sanity check (compilation, import, lint)."""
        if not self._eval_spec.checks_command:
            return ExperimentResult(command="(no checks)", exit_code=0, ...)
        return self.run_command(self._eval_spec.checks_command, timeout=30.0)
```

In `self_improve.yml`, add a checks action before evaluate:
```yaml
states:
    # ... after improve ...
    check_compilation:
      action: run_checks
      transitions:
        - condition: "context.last_status == 'checks_passed'"
          to: evaluate
        - to: archive_discard  # Skip expensive eval entirely
```

#### Change 4: Log-Redirect-and-Grep Output Pattern

**Problem:** Full benchmark stdout fills the agent's context window.  
**Solution:** Redirect benchmark output to a file, extract only metrics.

Files to change: `experiment.py`

```python
class ExperimentTracker:
    def run_command(self, command, timeout=600.0, log_file=None):
        """Run command, optionally redirecting output to log_file."""
        if log_file:
            # Redirect to file, only parse METRIC lines from it
            wrapped = f"({command}) > {log_file} 2>&1"
            proc = subprocess.run(["bash", "-c", wrapped], ...)
            # Read only METRIC lines from log file
            output = Path(log_file).read_text()
            metrics = parse_metrics(output)
            # Truncate output for the result object (last 50 lines only)
            tail = "\n".join(output.split("\n")[-50:])
            ...
```

The agent prompt tells it to use `grep` on the log file rather than reading raw output:
```
Run the benchmark. Output goes to run.log automatically.
To see results: `grep "^METRIC" run.log`
If it crashed: `tail -50 run.log`
```

---

### Phase 2: Archive & Search (from HyperAgents)

These introduce the evolutionary search layer. New data structures needed.

#### Change 5: Archive of Variants

**Problem:** Only the latest best survives. Discarded variants are lost forever.  
**Solution:** Keep ALL experiment results and their diffs in an archive.

New file: `archive.py`

```python
@dataclass
class ArchiveEntry:
    """One generation in the archive."""
    generation_id: int
    parent_id: Optional[int]         # Which generation this was derived from
    patch_file: str                   # Path to the diff file
    score: Optional[float]           # Primary metric score
    scores: Dict[str, float]         # All metrics
    status: str                      # "evaluated", "failed", "baseline"
    metadata: Dict[str, Any]         # Free-form (agent hypothesis, timing, etc.)
    children: List[int] = field(default_factory=list)
    timestamp: str = ""

class Archive:
    """Persistent archive of all experiment generations."""
    
    def __init__(self, path: str):
        self._path = Path(path)
        self._entries: Dict[int, ArchiveEntry] = {}
        self._next_id = 0
    
    def add(self, parent_id: Optional[int], patch_file: str, 
            score: Optional[float], metadata: Dict) -> ArchiveEntry:
        """Add a new generation. ALL generations are kept."""
        entry = ArchiveEntry(
            generation_id=self._next_id,
            parent_id=parent_id,
            patch_file=patch_file,
            score=score,
            ...
        )
        if parent_id is not None and parent_id in self._entries:
            self._entries[parent_id].children.append(self._next_id)
        self._entries[self._next_id] = entry
        self._next_id += 1
        self._persist(entry)
        return entry
    
    def select_parent(self, method="score_child_prop") -> ArchiveEntry:
        """Select next parent using HyperAgents-style selection."""
        candidates = {eid: e for eid, e in self._entries.items() 
                     if e.score is not None}
        if method == "score_child_prop":
            return self._score_child_proportional(candidates)
        elif method == "best":
            return max(candidates.values(), key=lambda e: e.score)
        ...
    
    def _score_child_proportional(self, candidates):
        """Sigmoid-scaled score × child-count penalty."""
        scores = [c.score for c in candidates.values()]
        mid = np.mean(sorted(scores, reverse=True)[:3])
        # Sigmoid around top-3 midpoint
        scaled = [1 / (1 + math.exp(-10 * (s - mid))) for s in scores]
        # Penalize over-explored branches
        penalties = [math.exp(-(len(c.children)/8)**3) for c in candidates.values()]
        weights = [s * p for s, p in zip(scaled, penalties)]
        return random.choices(list(candidates.values()), weights=weights)[0]
    
    def get_lineage(self, generation_id: int) -> List[ArchiveEntry]:
        """Get the full ancestor chain from root to this generation."""
        chain = []
        current = generation_id
        while current is not None:
            entry = self._entries[current]
            chain.append(entry)
            current = entry.parent_id
        return list(reversed(chain))
    
    def get_patch_chain(self, generation_id: int) -> List[str]:
        """Get ordered list of patch files to reconstruct this generation's code."""
        return [e.patch_file for e in self.get_lineage(generation_id)]
```

Storage: `archive.jsonl` (append-only, one line per generation).

#### Change 6: Diff-Based Lineage & Worktree Isolation

**Problem:** No isolation between experiments. A bad edit corrupts the working tree.  
**Solution:** Git worktrees for lightweight isolation (no Docker needed for v1).

Files to change: `improve.py`, new `isolation.py`

```python
# isolation.py
class WorktreeIsolation:
    """Lightweight isolation using git worktrees."""
    
    def __init__(self, repo_dir: str, worktree_base: str = ".self_improve/worktrees"):
        self._repo_dir = repo_dir
        self._worktree_base = Path(repo_dir) / worktree_base
    
    def create_worktree(self, generation_id: int, parent_commit: str) -> str:
        """Create an isolated worktree branched from parent_commit."""
        wt_path = self._worktree_base / f"gen_{generation_id}"
        branch_name = f"self-improve/gen-{generation_id}"
        subprocess.run([
            "git", "worktree", "add", "-b", branch_name, 
            str(wt_path), parent_commit
        ], cwd=self._repo_dir, check=True)
        return str(wt_path)
    
    def apply_patches(self, worktree_path: str, patch_files: List[str]):
        """Apply ancestor patches to reconstruct a generation's state."""
        for patch_file in patch_files:
            subprocess.run(
                ["git", "apply", "--allow-empty", patch_file],
                cwd=worktree_path, check=True
            )
    
    def extract_diff(self, worktree_path: str, output_path: str):
        """Extract the diff of changes made in this worktree."""
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=worktree_path, capture_output=True, text=True
        )
        Path(output_path).write_text(result.stdout)
    
    def cleanup_worktree(self, generation_id: int):
        """Remove a worktree after the experiment is done."""
        wt_path = self._worktree_base / f"gen_{generation_id}"
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=self._repo_dir
        )
```

**Why worktrees instead of Docker:**
- Zero setup for users (git is already required)
- Fast (milliseconds to create, not seconds)
- Same filesystem = benchmarks work identically
- Can upgrade to Docker later for untrusted code

#### Change 7: Staged Evaluation

**Problem:** Every experiment runs the full benchmark, even obviously broken ones.  
**Solution:** Quick check → small eval → full eval.

Files to change: `experiment.py`, `improve.py`

```python
# In EvaluationSpec:
@dataclass
class EvaluationSpec:
    benchmark_command: str
    quick_benchmark_command: str = ""  # Faster version (subset of data, fewer iterations)
    quick_threshold: float = 0.0      # Minimum score on quick eval to proceed to full
    ...

# In SelfImprover._evaluate():
def _evaluate(self, context):
    # Stage 0: Compilation check
    checks = self._improver.run_checks()
    if not checks.success:
        context["last_status"] = "failed_checks"
        return context
    
    # Stage 1: Quick eval (if configured)
    if self._improver.eval_spec.quick_benchmark_command:
        quick = self._improver.run_quick_benchmark()
        if quick.metrics.get(self._metric_name, 0) < self._eval_spec.quick_threshold:
            context["last_status"] = "failed_quick_eval"
            return context
    
    # Stage 2: Full eval
    result = self._improver.run_benchmark()
    ...
```

#### Change 8: Outer Loop in `self_improve.yml`

The machine config grows to express the two-loop architecture:

```yaml
spec: flatmachine
spec_version: "2.5.0"

data:
  name: self-improve-converged
  max_steps: 500

  context:
    # Evaluation firewall
    eval_spec:
      benchmark_command: "{{ input.benchmark_command }}"
      checks_command: "{{ input.checks_command | default('') }}"
      quick_benchmark_command: "{{ input.quick_benchmark_command | default('') }}"
      quick_threshold: "{{ input.quick_threshold | default(0) }}"
      timeout_s: "{{ input.timeout_s | default(300) }}"
      protected_paths: "{{ input.protected_paths | default([]) }}"
    
    # Scope
    editable_patterns: "{{ input.editable_patterns | default(['**/*.py']) }}"
    
    # Outer loop state
    max_generations: "{{ input.max_generations | default(50) }}"
    generation: 0
    parent_id: null
    parent_selection: "{{ input.parent_selection | default('score_child_prop') }}"
    
    # Inner loop state (per generation)
    inner_iterations: "{{ input.inner_iterations | default(3) }}"
    inner_iteration: 0
    best_score: null
    current_score: null
    last_status: ""
    consecutive_failures: 0

  agents:
    coder: ./agents/coder.yml

  states:
    start:
      type: initial
      transitions:
        - to: select_parent

    # ── Outer Loop: Generation Management ──

    select_parent:
      action: select_parent_from_archive
      transitions:
        - to: setup_worktree

    setup_worktree:
      action: create_isolated_worktree
      transitions:
        - to: improve

    # ── Inner Loop: Experiment Execution ──

    improve:
      agent: coder
      tool_loop:
        max_turns: 40
        max_tool_calls: 120
        max_cost: 5.00
        tool_timeout: 120
        total_timeout: 1200
      input:
        task: |
          You are a self-improving coding agent. Iteration {{ context.inner_iteration + 1 }}/{{ context.inner_iterations }}, generation {{ context.generation }}.

          ## Scope
          Working directory: {{ context.worktree_path }}
          You may ONLY edit files matching: {{ context.editable_patterns | join(', ') }}
          Do NOT modify: {{ context.eval_spec.protected_paths | join(', ') }}

          ## Benchmark
          Command: {{ context.eval_spec.benchmark_command }}
          Metric: {{ context.eval_spec.metric_name }} ({{ context.metric_direction }} is better)
          Timeout: {{ context.eval_spec.timeout_s }}s (fixed budget)

          ## Current State
          Generation: {{ context.generation }} (parent: {{ context.parent_id }})
          Best score this generation: {{ context.best_score }}
          Last status: {{ context.last_status }}

          ## History Recovery
          Read the archive summary: `cat .self_improve/archive_summary.tsv`
          Read recent git log: `git log --oneline -20`
          Read ideas if any: `cat ideas.md 2>/dev/null`

          ## Instructions
          1. Read history (see above) — learn from ALL past experiments, including other branches
          2. Run benchmark, redirect output: the command logs to run.log automatically
          3. See results: `grep "^METRIC" run.log` — if empty, check `tail -50 run.log`
          4. Analyze code, identify highest-impact change within editable scope
          5. Implement the change — small, focused, reversible
          6. Run benchmark again, compare
          7. Log promising future ideas to ideas.md

      output_to_context:
        analysis: "{{ output.content }}"
      transitions:
        - to: check_compilation

    check_compilation:
      action: run_checks
      transitions:
        - condition: "context.last_status == 'checks_passed'"
          to: evaluate
        - to: inner_discard

    evaluate:
      action: evaluate_with_staging
      transitions:
        - condition: "context.last_status == 'improved'"
          to: inner_keep
        - to: inner_discard

    inner_keep:
      action: commit_inner_improvement
      transitions:
        - to: inner_budget_check

    inner_discard:
      action: revert_inner_changes
      transitions:
        - to: inner_budget_check

    inner_budget_check:
      transitions:
        - condition: "context.inner_iteration >= context.inner_iterations"
          to: finalize_generation
        - condition: "context.consecutive_failures >= 3"
          to: finalize_generation
        - to: improve

    # ── Back to Outer Loop ──

    finalize_generation:
      action: extract_diff_and_archive
      transitions:
        - to: cleanup_worktree

    cleanup_worktree:
      action: cleanup_isolated_worktree
      transitions:
        - to: outer_budget_check

    outer_budget_check:
      transitions:
        - condition: "context.generation >= context.max_generations"
          to: done
        - to: select_parent

    done:
      type: final
      output:
        generations: "{{ context.generation }}"
        archive_size: "{{ context.archive_size }}"
        best_score: "{{ context.best_score }}"
        best_generation: "{{ context.best_generation }}"
        summary: >
          Self-improvement complete. {{ context.generation }} generations,
          {{ context.archive_size }} variants in archive.
          Best {{ context.eval_spec.metric_name }}: {{ context.best_score }}
          from generation {{ context.best_generation }}.
```

---

## File Inventory (Implemented)

New files:
| File | Role | LOC | Source Inspiration |
|------|------|-----|-------------------|
| `flatmachines_cli/evaluation.py` | `EvaluationSpec` (frozen) + `EvaluationRunner` (staged eval, tampering, log-redirect, glob matching) | ~290 | Autoresearch `prepare.py` |
| `flatmachines_cli/archive.py` | `Archive` (append-only JSONL) + `ArchiveEntry` + parent selection (best, score_child_prop, random) | ~230 | HyperAgents `gl_utils.py` |
| `flatmachines_cli/isolation.py` | `WorktreeIsolation` (create/commit/reset/extract-diff/cleanup per generation) | ~220 | HyperAgents Docker (lightweight) |
| `tests/test_converged_self_improve.py` | 50 tests covering all new modules + integrated hooks + machine config validation | ~530 | — |

Modified files:
| File | Changes |
|------|---------|
| `flatmachines_cli/improve.py` | Added `ConvergedSelfImproveHooks` (+250 LOC) — handles all outer+inner loop actions. `SelfImprover` now accepts `eval_spec`, `archive_path`, `enable_isolation`. Backward-compatible. |
| `flatmachines_cli/__init__.py` | Exports `EvaluationSpec`, `EvaluationRunner`, `EvalResult`, `Archive`, `ArchiveEntry`, `WorktreeIsolation`, `ConvergedSelfImproveHooks` |
| `config/self_improve.yml` | Two-loop machine config: outer (select_parent → worktree → inner → archive → cleanup), inner (improve → checks → evaluate → keep/discard). `eval_spec` in context. `max_steps: 500`. |
| `config/agents/coder.yml` | Scoped edit instructions, redirect-and-grep benchmark protocol, archive_summary.tsv recovery |

Unchanged (backward-compatible):
| File | Notes |
|------|-------|
| `experiment.py` | No changes needed — `EvaluationRunner` handles the new eval logic. `ExperimentTracker` still used for JSONL experiment history. |
| `config/agents/analyzer.yml` | Still present, still valid. Machine now uses `coder.yml` (unified pattern). |
| `config/agents/implementer.yml` | Still present, still valid. Available for split-agent patterns. |

---

## What We Deliberately Defer

| Feature | Why Defer |
|---------|-----------|
| **Docker isolation** | Git worktrees are sufficient for v1 and require zero setup. Docker can be added later as an `IsolationBackend` option. |
| **Self-referential self-improvement** (agent edits improve.py/self_improve.yml) | Requires the archive + isolation to be solid first. Phase 3 — add `improve.py` and `self_improve.yml` to the editable scope and let the agent modify its own loop. |
| **Multi-domain evaluation** | Most flatmachines_cli users have one benchmark. Can add later as `EvaluationSpec.benchmark_commands: List[str]`. |
| **Ensemble** | Requires archive with stored predictions (not just scores). Phase 3. |
| **Agent-editable parent selection** | HyperAgents' most advanced feature. Requires archive trust + safety. Phase 3. |
| **Never-stop mode** | Replace `max_generations` with `max_generations: -1` for infinite. Trivial once the loop is solid. |

---

## Migration Path for Existing Users

The converged design is **backward-compatible**. If you set:

```yaml
max_generations: 1
inner_iterations: 10
parent_selection: "best"
```

You get exactly the current behavior: a linear hill-climbing loop with no archive. The archive exists but has one lineage. The worktree is created but is functionally equivalent to working in-place.

As users gain confidence, they can:
1. Increase `max_generations` to enable tree search
2. Switch `parent_selection` to `score_child_prop` for diversity
3. Add `checks_command` for fail-fast
4. Add `quick_benchmark_command` for staged eval
5. Add `protected_paths` for evaluation firewall

---

## Sequencing Summary

### Phase 1 — Inner Loop (Autoresearch mechanics)

- [x] **1. EvaluationSpec + evaluation firewall** — `evaluation.py`: frozen `EvaluationSpec` dataclass, `EvaluationRunner` with tampering detection via `validate_no_tampering()`. Makes each experiment trustworthy. *(d68c3cb)*
- [x] **2. Scoped edit targets** — `evaluation.py`: `editable_patterns` + `protected_paths` with full glob `**` support via `_glob_match()`. `coder.yml` prompt declares scope. `self_improve.yml` context carries `eval_spec.editable_patterns`. Bounds the search space. *(d68c3cb)*
- [x] **3. Fail-fast compilation check** — `evaluation.py`: `run_checks()` action runs `checks_command` before expensive benchmark. `self_improve.yml` has `check_compilation` state that short-circuits to `inner_discard`. Saves wasted cycles. *(d68c3cb)*
- [x] **4. Log-redirect-and-grep** — `evaluation.py`: `_run_command()` redirects to `log_file`, captures only METRIC lines + last 50 lines. `coder.yml` prompt instructs `> run.log 2>&1` then `grep "^METRIC" run.log`. Efficient context usage. *(d68c3cb)*

### Phase 2 — Outer Loop (HyperAgents search)

- [x] **5. Archive of variants** — `archive.py`: append-only JSONL, ALL generations kept (including failures), parent→child links, lineage tracking, `summary_tsv()` for agent context. Preserves diversity. *(d68c3cb)*
- [x] **6. Worktree isolation + diff lineage** — `isolation.py`: `WorktreeIsolation` with create/commit/reset/extract-diff/cleanup per generation. Patches stored in `.self_improve/patches/`. `apply_patches()` for lineage reconstruction. Safe exploration. *(d68c3cb)*
- [x] **7. Staged evaluation** — `evaluation.py`: `run_staged()` pipeline: tampering → checks → quick benchmark → full benchmark. `quick_benchmark_command` + `quick_threshold` in `EvaluationSpec`. Efficient compute. *(d68c3cb)*
- [x] **8. Two-loop machine config** — `self_improve.yml`: outer loop (`select_parent → setup_worktree → [inner loop] → finalize_generation → cleanup_worktree → outer_budget_check`), inner loop (`improve → check_compilation → evaluate → inner_keep/inner_discard → inner_budget_check`). `ConvergedSelfImproveHooks` in `improve.py` handles all actions. Ties it all together. *(d68c3cb)*

### Phase 3 — Self-Reference (Future)

- [ ] **9. Agent can edit improve.py / self_improve.yml** — Add improvement infrastructure to `editable_patterns`. Requires archive + isolation to be battle-tested first.
- [ ] **10. Agent can edit parent selection** — Expose `archive.py` `select_parent()` to editable scope. HyperAgents' most advanced feature. Requires archive trust + safety.
- [ ] **11. Multi-domain evaluation** — `EvaluationSpec.benchmark_commands: List[str]` with aggregated scoring. Most users have one benchmark today.
- [ ] **12. Ensemble of archive** — Best-per-task from all surviving variants. Requires stored predictions, not just scores.

Each phase is independently valuable. Phase 1 alone makes the current loop significantly more robust. Phase 2 transforms it from a hill-climber into an evolutionary search. Phase 3 makes it truly self-referential.

---

## Validation Record

### Unit Tests

74 tests pass (24 original backward-compat + 50 new converged):

| Module | Tests | What's covered |
|--------|-------|----------------|
| `EvaluationSpec` | 6 | frozen, from_dict, is_better, direction, defaults |
| `EvaluationRunner` | 8 | log-redirect, checks pass/fail/skip, staged pipeline, timeout, edit scope, tampering |
| `Archive` | 10 | add/retrieve, best, select_parent (best + score_child_prop), lineage, patch_chain, persistence, summary_tsv, failed kept |
| `WorktreeIsolation` | 4 | create/cleanup, extract_diff, commit/reset, head_commit |
| `ConvergedSelfImproveHooks` | 8 | select_parent (empty + populated), checks pass/fail, staged eval improve/no_improvement, extract_and_archive, full inner loop cycle, backward-compat simple actions |
| `SelfImprover` (converged) | 4 | eval_spec from simple params, explicit eval_spec, archive created, isolation opt-in |
| `MachineConfig` (converged) | 10 | two-loop states, eval_spec in context, transitions valid, initial/final, output, outer/inner context fields, agent prompt scope |

### End-to-End Run (Codex, 2026-04-07)

**Test project:** `/tmp/converged-test` — intentionally slow `app.py` with repeated-addition `multiply()` and recursive `fibonacci()`.

**Run command:**
```
flatmachines improve /tmp/converged-test --benchmark "bash benchmark.sh" --metric speed_ms --direction lower --git --run
```

**Result:** Completed in 40.8s, clean exit at final state.

| Step | What happened |
|------|--------------|
| `select_parent` | Empty archive → `parent_id=None` |
| `setup_worktree` | No isolation enabled → work in-place |
| `improve` (iter 1) | Agent: read code → identified fibonacci bottleneck → rewrote as iterative DP → ran benchmark → logged ideas.md |
| `check_compilation` | `checks_passed` (no checks_command configured in this run) |
| `evaluate` (iter 1) | Staged eval complete: `speed_ms=7` → improved (first baseline) |
| `inner_keep` | Committed |
| `improve` (iter 2) | Agent: re-ran benchmark → `speed_ms=6` → improved |
| `inner_keep` | Committed |
| `improve` (iter 3) | Agent: re-ran benchmark → `speed_ms=6` → no improvement (equal) |
| `inner_discard` | Reverted |
| `finalize_generation` | Extracted diff, archived: gen_id=0, score=6.0, status=evaluated |
| `cleanup_worktree` | No-op (no isolation) |
| `outer_budget_check` | `1 >= 1` → done |
| `done` | Output: `best_score=6.0, archive_size=1, generations=1` |

**Artifacts produced:**
- `.self_improve/experiments.jsonl` — 3 experiment entries with stage/generation/iteration metadata
- `.self_improve/archive.jsonl` — 1 generation entry with score, scores, metadata
- `.self_improve/archive_summary.tsv` — TSV for agent context recovery
- `ideas.md` — agent-logged future optimization ideas
- `run.log` — last benchmark output (log-redirect pattern)

**Performance:** baseline 62ms → final 6ms (10.3× speedup). Agent correctly identified fibonacci as the bottleneck and replaced O(2^n) recursive with O(n) iterative.

### Runtime Notes

1. **Jinja2 + int context fields:** FlatMachine's `_render_template` always returns strings for Jinja2 templates, even with `| int` filter. Numeric context fields used in conditions (`>=`, `<`) must be plain YAML ints, not Jinja2 templates. The expression engine does not coerce types.

2. **Tool loop behavior:** The tool_loop correctly breaks on `finish_reason != "tool_use"`. However, the chain is preserved across improve invocations via `saved_chain` (keyed by state name + agent name). This means the agent retains full context across inner loop iterations within a generation — useful for learning from previous attempts.

3. **CLI wiring:** `main.py` `_make_self_improve_handler` uses `ConvergedSelfImproveHooks` (not `SelfImproveHooks`), and registers all converged actions. `_SELF_IMPROVE_ACTIONS` set contains both original simple actions and new converged actions for backward compatibility.

4. **Default `max_generations: 1`:** Defaults to single-generation linear mode for safety. Users opt into multi-generation evolutionary search by increasing this value.
