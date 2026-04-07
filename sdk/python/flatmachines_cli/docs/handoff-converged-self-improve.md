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

## New File Inventory

| File | Role | Source Inspiration |
|------|------|--------------------|
| `archive.py` | Archive data structure + parent selection | HyperAgents `gl_utils.py` |
| `isolation.py` | Git worktree isolation | HyperAgents Docker (lightweight) |
| `evaluation.py` | `EvaluationSpec` + staged eval + tampering detection | Autoresearch `prepare.py` |
| `self_improve.yml` (updated) | Two-loop machine config | Both |
| `coder.yml` (updated) | Scoped prompt with redirect-and-grep | Autoresearch `program.md` |

Existing files that change:
| File | Changes |
|------|---------|
| `experiment.py` | Add `EvaluationSpec`, log-redirect, checks runner |
| `improve.py` | Wire in `Archive`, `WorktreeIsolation`, `EvaluationSpec`; new action handlers |

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

```
Phase 1 (Inner Loop — Autoresearch mechanics):
  1. EvaluationSpec + evaluation firewall     ← makes each experiment trustworthy
  2. Scoped edit targets                       ← bounds the search space
  3. Fail-fast compilation check               ← saves wasted cycles
  4. Log-redirect-and-grep                     ← efficient context usage

Phase 2 (Outer Loop — HyperAgents search):
  5. Archive of variants                       ← preserves diversity
  6. Worktree isolation + diff lineage         ← safe exploration
  7. Staged evaluation                         ← efficient compute
  8. Two-loop machine config                   ← ties it all together

Phase 3 (Self-Reference — Future):
  9. Agent can edit improve.py / self_improve.yml
  10. Agent can edit parent selection
  11. Multi-domain evaluation
  12. Ensemble of archive
```

Each phase is independently valuable. Phase 1 alone makes the current loop significantly more robust. Phase 2 transforms it from a hill-climber into an evolutionary search. Phase 3 makes it truly self-referential.
