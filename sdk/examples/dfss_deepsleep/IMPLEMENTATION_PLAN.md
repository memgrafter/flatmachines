# DFSS Deep Sleep — Implementation Plan

## The core design question

`dfss_pipeline` has ~500 lines of Python orchestration in `main.py` + `scheduler.py`.
The point of `dfss_deepsleep` is to move that orchestration **into the machine**.
The question is: what goes into machine states/transitions vs hook actions vs thin runner glue?

## Architecture mapping

### What pipeline does in Python → where it goes in deepsleep

| Pipeline Python code | Deepsleep equivalent |
|---|---|
| `scheduler.run()` async loop (pick → dispatch → wait FIRST_COMPLETED → refill) | **Scheduler machine loop** (states + transitions) |
| `scheduler.score()` / `pick_next()` | **Hook action** `pick_batch` (already done) |
| `scheduler.ResourcePool` + gate toggle | **Hook action** `toggle_gate` + context state |
| `main.dispatch()` (claim → execute task machine → complete/fail/retry → enqueue children) | **Hook action** `dispatch_and_settle` OR `foreach` dispatch + `process_results` action |
| `main._seed_roots()` + work pool push | **Hook action** `seed_work` |
| `main._load_pending_candidates()` + rebuild | **Hook action** `hydrate_candidates` |
| `main.release_by_worker()` on resume | **Hook action** `release_stale` |
| `main._post_run_report()` + cleanup | **Hook action** `report_and_cleanup` |
| `main._toggle_slow_gate()` background task | **`launch` state** running a gate-toggle machine, OR periodic action in scheduler loop |
| Signal on task completion → wake scheduler | **`signal_ready` action** (task machine) + `wait_for` (scheduler) |
| Ctrl+C → stop_event → checkpoint | **Machine checkpoint on `wait_for`** (native) |

### Key constraint: `foreach` is batch-barrier, not continuous-fill

Pipeline's `scheduler.run()` dispatches one task at a time, refills on FIRST_COMPLETED.
Machine's `foreach` + `mode: settled` launches all items and waits for all to finish.

**This is an acceptable behavioral difference.** The machine version processes in batches
(pick N → run N → process results → loop). Same priorities, same scoring, same outcomes,
slightly different throughput profile. The batch size controls granularity.

This is the right tradeoff — trying to replicate continuous-fill inside the machine
would mean fighting the abstraction for no real gain.

---

## Current state (what exists and what's broken)

### What works
- Task machine config (`config/task_machine.yml`) — correct
- Scoring logic in hooks — now isomorphic with pipeline (previous fix)
- `pick_batch` / `process_results` — work on in-memory context
- Unit tests for scoring and batch selection — pass
- Scheduler machine config — has correct state flow shape

### What's missing or broken
1. **Runner** (`main.py`) runs task-only generation loop, not the scheduler machine
2. **No durable backends** — everything is MemoryBackend, no SQLite
3. **`pick_batch`** reads from `context._candidates` only — no durable hydration
4. **`process_results`** updates context only — doesn't persist to work pool
5. **`signal_ready`** is a no-op
6. **No retry/fail/poison lifecycle**
7. **No resume** (release stale claims, rebuild from DB)
8. **No resource gates** (slow gate open/closed)
9. **No seeding** of designed roots into durable pool
10. **No completion reporting or checkpoint cleanup**

---

## Implementation plan

### Step 1 — New hook actions for durable lifecycle

**File:** `python/src/flatagent_dfss_deepsleep/hooks.py`

Add these actions to `on_action` dispatch:

| Action | What it does | Pipeline equivalent |
|---|---|---|
| `seed_work` | Push initial root tasks into work pool | `_seed_roots()` |
| `hydrate_candidates` | Load pending rows from SQLite work pool into `context._candidates` | `_load_pending_candidates()` |
| `release_stale` | Call `pool.release_by_worker("scheduler")` on resume | resume path in `_run_pipeline()` |
| `claim_batch` | For each item in `context.batch`, atomically claim in work pool | `_claim_selected_candidate()` |
| `settle_results` | For each result: complete/fail in pool, enqueue children, handle retries | `dispatch()` result handling |
| `toggle_gate` | Flip `context.resources.slow.gate_open` | `_toggle_slow_gate()` |
| `check_done` | Query unfinished work count from pool, set `context.all_done` | `_unfinished_work_count()` |
| `report_and_cleanup` | Print summary, optionally delete completed checkpoints | `_post_run_report()` |

**Key change:** hooks constructor receives `work_backend` and `signal_backend` (already
has slots for these — they just need to be used).

`pick_batch` needs one addition: **resource capacity filtering**. Currently it picks
without checking if fast/slow slots are available. Add `context.resources` tracking
and filter candidates by available capacity (matching pipeline's `pick_next` which
checks `pool.available`).

### Step 2 — Redesign scheduler machine states

**File:** `config/scheduler_machine.yml`

```yaml
states:
  # ── Bootstrap ──
  init:
    type: initial
    transitions:
      - condition: "context.resume"
        to: release_stale
      - to: seed

  seed:
    action: seed_work
    transitions:
      - to: hydrate

  release_stale:
    action: release_stale
    transitions:
      - to: hydrate

  # ── Main loop ──
  hydrate:
    action: hydrate_candidates
    transitions:
      - to: pick

  pick:
    action: pick_batch
    transitions:
      - condition: "context.batch"
        to: claim
      - condition: "context.all_done"
        to: report
      - to: sleep

  claim:
    action: claim_batch
    transitions:
      - condition: "context.claimed_batch"
        to: dispatch
      - to: pick    # all claims lost race, re-pick

  dispatch:
    foreach: "context.claimed_batch"
    as: task
    machine: task_runner
    input:
      task_id: "{{ task.task_id }}"
      root_id: "{{ task.root_id }}"
      depth: "{{ task.depth }}"
      resource_class: "{{ task.resource_class }}"
      has_expensive_descendant: "{{ task.has_expensive_descendant }}"
      distance_to_nearest_slow_descendant: "{{ task.distance_to_nearest_slow_descendant }}"
    mode: settled
    output_to_context:
      batch_results: "output"
    on_error: settle
    transitions:
      - to: settle

  settle:
    action: settle_results
    transitions:
      - to: check_done

  check_done:
    action: check_done
    transitions:
      - condition: "context.all_done"
        to: report
      - to: hydrate    # immediate next batch (no sleep between batches)

  # ── Deep sleep ──
  sleep:
    wait_for: "dfss/ready"
    timeout: 0
    transitions:
      - to: hydrate

  # ── Finish ──
  report:
    action: report_and_cleanup
    transitions:
      - to: done

  done:
    type: final
    output:
      roots: "context.roots"
      summary: "context.summary"
```

**Notable decisions:**
- `hydrate` before every pick (single source of truth from DB)
- `claim` is separate from `pick` (atomic DB claims can fail)
- `check_done` queries DB, not just context
- `sleep` only entered when `pick` finds nothing runnable but work remains
- No `wait_for` on initial entry — only sleeps when blocked
- Gate toggling: see Step 3

### Step 3 — Gate toggle approach

Two options:

**Option A — `launch` a gate-toggle machine (matches pipeline's background task)**
```yaml
  seed:
    action: seed_work
    launch: gate_toggler
    launch_input:
      interval: "{{ context.gate_interval }}"
    transitions:
      - to: hydrate
```
The gate machine loops: sleep → toggle → signal scheduler → sleep.
Problem: needs shared mutable state for `resources.slow.gate_open`.

**Option B — Action in scheduler loop (simpler, good enough)**
Add `toggle_gate` check inside `pick_batch` or as a separate action before `pick`.
Gate flips based on elapsed time since last toggle. No background task needed.

**Recommendation: Option B.** The machine already loops. Checking elapsed time in
`pick_batch` (or a pre-pick action) is simpler and fully testable without launch complexity.

### Step 4 — Runner (thin glue)

**File:** `python/src/flatagent_dfss_deepsleep/scheduler_main.py`

This should be ~60 lines. All it does:

1. Parse args (same CLI as pipeline)
2. Create `SQLiteCheckpointBackend` + `SQLiteWorkBackend`
3. Create `DeepSleepHooks(work_backend=..., signal_backend=..., ...)`
4. Create `FlatMachine(config_file="scheduler_machine.yml", hooks=..., persistence=...)`
5. `machine.execute(input={...})` — single call
6. If result is `_waiting`, print "sleeping, resume with --resume"
7. If `--resume`, call `machine.execute(resume_from=execution_id)`
8. Print final status

That's it. **All orchestration logic lives in the machine + hooks.**

Keep old `main.py` as `tree_demo.py` for reference.

### Step 5 — Signal wiring

**Task machine** `signal_ready` action: actually call
`self.signal_backend.send("dfss/ready", {"reason": "task_complete"})`.

**Scheduler machine** `sleep` state: `wait_for: "dfss/ready"` consumes signal,
wakes, transitions to `hydrate`.

For unit tests: use `MemorySignalBackend`.
For runner: use `SQLiteSignalBackend`.

### Step 6 — Retry/poison lifecycle in `settle_results`

For each result in batch:
- Success → `pool.complete(work_id, output)`, enqueue children via `pool.push()`
- Error + attempts < max → `pool.fail(work_id, error)` (returns to pending), log retry
- Error + attempts >= max → poisoned (terminal), increment root terminal failures

This directly mirrors pipeline's `dispatch()` error handling.

### Step 7 — Resume path

When `--resume`:
- Runner loads execution_id from meta table (or queries checkpoint backend)
- Passes `resume=True` in machine input
- Machine enters `release_stale` → `hydrate` → normal loop
- `release_stale` action calls `pool.release_by_worker("scheduler")`

### Step 8 — Tests

**Unit tests** (expand existing `test_hooks.py`):
- `seed_work` creates items in work pool
- `hydrate_candidates` loads from pool correctly
- `claim_batch` atomically claims and handles race
- `settle_results` with success/retry/terminal paths
- `check_done` reflects pool state
- Gate toggle timing logic

**Integration tests** (new `test_scheduler_integration.py`):
- Fresh run completes designed roots (same assertion as pipeline)
- Stop + resume completes remaining work
- Terminal failures after max attempts
- Gate affects which tasks are selectable

**Parity tests** (new `test_parity.py`):
- Given same seed/roots/depth: deepsleep and pipeline produce same root completion set
- Same designed roots trigger same scheduling priorities

---

## Execution order

1. **Step 1** — Hook actions (durable lifecycle). Tests first.
2. **Step 2** — Scheduler machine YAML redesign.
3. **Step 3** — Gate toggle in pick action.
4. **Step 4** — Thin runner (`scheduler_main.py`).
5. **Step 5** — Signal wiring (task → scheduler wake).
6. **Step 6** — Retry/poison in settle_results.
7. **Step 7** — Resume path.
8. **Step 8** — Integration + parity tests.

Steps 1–3 can be one PR. Steps 4–5 second PR. Steps 6–7 third PR. Step 8 throughout.

---

## What stays out of the machine (thin runner only)

- CLI arg parsing
- Backend construction (`SQLiteCheckpointBackend`, `SQLiteWorkBackend`)
- `FlatMachine(...)` instantiation
- Single `machine.execute()` call
- Resume: load execution_id, `machine.execute(resume_from=...)`
- Print final waiting/complete status

**Everything else is in machine states + hook actions.**
