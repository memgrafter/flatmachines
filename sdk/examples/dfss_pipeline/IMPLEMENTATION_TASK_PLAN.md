# DFSS Pipeline Example — Standalone Implementation Task Plan (with TDD)

## 1) Goal
Build a Python example that schedules dynamic task trees using depth-first saturation scheduling (DFSS), persists all work/checkpoints in SQLite, and cleanly resumes after interruption.

This plan is self-contained and includes implementation tasks, tests-first workflow, and acceptance criteria.

---

## 2) Deliverables

- [ ] `main.py` — CLI entrypoint, seeding, resume flow, scheduler orchestration, reporting
- [ ] `scheduler.py` — DFSS scoring + pick + run loop
- [ ] `task_machine.py` — single reusable FlatMachine config for every task
- [ ] `hooks.py` — deterministic designed trees + random tree behavior + transient failures
- [ ] `README.md` — run instructions + expected behavior + resume walkthrough
- [ ] `data/` runtime artifacts created at run-time (`dfss.sqlite`)

### New tests
- [ ] `../../python/tests/unit/test_dfss_task_machine.py`
- [ ] `../../python/tests/unit/test_dfss_hooks.py`
- [ ] `../../python/tests/unit/test_dfss_scheduler.py`
- [ ] `../../python/tests/integration/test_dfss_pipeline.py`

---

## 3) Functional behavior to implement

### 3.1 Task tree model
Each queued item is a task dict:

```python
{
  "task_id": str,                      # e.g. root-000/0.0.1
  "root_id": str,                      # e.g. root-000
  "depth": int,
  "resource_class": "fast" | "slow",
  "has_expensive_descendant": bool,
  "attempts": int,                     # optional scheduler retry count
}
```

### 3.2 Deterministic designed roots
Implement two deterministic roots to force key scheduling scenarios:

- `root-000` produces two simultaneous `slow` children at depth 2
- `root-001` has a depth-3 `slow` task gated behind `fast` predecessors marked with `has_expensive_descendant=True`

### 3.3 Random roots
All other roots spawn random children (0–2), random resource class, bounded by max depth.

### 3.4 Resources and gates
- `fast`: capacity 4 (always open)
- `slow`: capacity 2 (gate toggles open/closed periodically)

### 3.5 Scheduler behavior
- Prefer admitted roots first
- Prefer deeper work (DFS)
- Prefer tasks on roots nearer completion
- Boost `slow` work (scarce resource)
- Boost cheap predecessors that unblock expensive descendants
- Admit new roots only when policy allows (`max_active_roots`)

### 3.6 Error handling and retries
- Task machine uses **state-level** `on_error` transition to an `error_exit` final state
- Scheduler requeues errored items up to max attempts (example: 3)
- Terminal failures are logged and removed from pending count

### 3.7 Persistence and resume
- Use one SQLite DB file for both checkpoints and work pool
- Resume flow must:
  - release stale claimed work for scheduler worker id
  - reconstruct pending candidates from durable storage
  - report incomplete vs completed executions using event filtering

### 3.8 Post-run lifecycle operations
- Report total executions and completed executions
- Delete completed checkpoints via backend delete API

---

## 4) Technical decisions (explicit)

- [ ] Use `SQLiteCheckpointBackend(db_path=...)`
- [ ] Use `SQLiteWorkBackend(db_path=...).pool("tasks")`
- [ ] Use `FlatMachine(..., persistence=backend)` per dispatch
- [ ] Use `backend.list_execution_ids()` and `backend.list_execution_ids(event="machine_end")`
- [ ] Use `CheckpointManager(...).load_status()` for resumable status reporting
- [ ] Use `pool.release_by_worker("scheduler")` during resume

### Candidate scoring vs WorkPool FIFO
`WorkPool.claim()` is FIFO; DFSS needs global scoring. Implement a scheduler-owned in-memory candidate index:

- pending items are durable in WorkPool (SQLite)
- candidates are tracked in-memory for scoring
- on restart, rebuild candidate index from pending rows in SQLite
- assume single scheduler process for this example

---

## 5) TDD implementation roadmap

## Milestone A — test harness and fixtures

- [ ] Create test files listed above
- [ ] Add common fixtures:
  - [ ] temp sqlite path
  - [ ] deterministic random seed fixture
  - [ ] helper to create queue items

### Red tests to add first
- [ ] `test_dfss_task_machine.py::test_task_config_has_required_states`
- [ ] `test_dfss_hooks.py::test_designed_root_000_shape`
- [ ] `test_dfss_scheduler.py::test_score_prefers_deeper_active_work`

---

## Milestone B — `task_machine.py` (tests first)

### Tests (write first)
- [ ] `test_task_config_has_required_states`
- [ ] `test_execute_task_has_on_error_to_error_exit`
- [ ] `test_final_output_contains_typed_children_list`
- [ ] `test_error_exit_outputs_error_field`

### Implementation tasks
- [ ] Add `task_config()` returning flatmachine dict
- [ ] States:
  - [ ] `start` (initial) -> `execute_task`
  - [ ] `execute_task` action `run_task`, `on_error: error_exit`
  - [ ] `done` final output includes `children`, `result`
  - [ ] `error_exit` final output includes `error`

### Acceptance
- [ ] Unit tests for machine config pass

---

## Milestone C — `hooks.py` (tests first)

### Tests (write first)
- [ ] `test_designed_root_000_shape`
- [ ] `test_designed_root_001_shape`
- [ ] `test_designed_leaves_return_no_children`
- [ ] `test_random_mode_respects_max_depth`
- [ ] `test_fail_rate_1_raises_transient_error`

### Implementation tasks
- [ ] Define deterministic designed tree map
- [ ] Implement `TaskHooks` with constructor args: `max_depth`, `fail_rate`
- [ ] Implement `on_action("run_task", context)`:
  - [ ] inject transient failure by probability
  - [ ] emit designed children if task in map
  - [ ] otherwise random generation
  - [ ] set `context["children"]` and `context["result"]`

### Acceptance
- [ ] Hook tests pass deterministically with seeded RNG

---

## Milestone D — `scheduler.py` pure logic (tests first)

### Core structures
- [ ] `RootState`
- [ ] `ResourcePool`

### Tests (write first)
- [ ] `test_score_prefers_active_root`
- [ ] `test_score_prefers_depth`
- [ ] `test_score_boosts_slow_resource`
- [ ] `test_score_boosts_expensive_predecessor_hint`
- [ ] `test_pick_next_prefers_active_candidates`
- [ ] `test_pick_next_admits_new_root_when_no_active_runnable`
- [ ] `test_pick_next_respects_gate_closed`
- [ ] `test_refresh_expensive_flag_clears_when_last_slow_removed`

### Implementation tasks
- [ ] Implement `score(item, root, is_active)`
- [ ] Implement `pick_next(candidates, roots, resources, max_active_roots)`
- [ ] Implement helper functions:
  - [ ] enqueue children
  - [ ] recompute expensive pending flag
- [ ] Implement async `run(...)` loop:
  - [ ] fill worker slots
  - [ ] wait FIRST_COMPLETED
  - [ ] immediate refill
  - [ ] idle polling when blocked

### Acceptance
- [ ] All scheduler unit tests pass

---

## Milestone E — Durable candidate index + pool glue (tests first)

### Tests (write first)
- [ ] `test_rebuild_candidates_from_sqlite_pending_rows`
- [ ] `test_resume_releases_stale_claims`
- [ ] `test_complete_removes_item_from_pool_and_candidates`

### Implementation tasks
- [ ] Add helper in `main.py` (or local helper module) to load pending items from SQLite `work_pool` table for pool `tasks`
- [ ] Define candidate map/list operations:
  - [ ] add candidate on push
  - [ ] remove candidate on dispatch claim
  - [ ] add children candidates on completion
- [ ] Ensure consistency between in-memory candidates and durable pool operations

### Acceptance
- [ ] Durable rebuild tests pass

---

## Milestone F — `main.py` orchestration (tests first)

### CLI behavior
- [ ] parse args: `--roots`, `--resume`, `--max-depth`, `--max-workers`, `--db-path`, `--seed`, `--fail-rate`, `--cleanup`

### Tests (write first)
- [ ] `test_seed_creates_designed_and_random_roots`
- [ ] `test_resume_mode_reports_pending_and_incomplete`
- [ ] `test_dispatch_success_enqueues_children`
- [ ] `test_dispatch_error_requeues_until_max_attempts`

### Implementation tasks
- [ ] initialize checkpoint + work backends
- [ ] seed fresh run roots
- [ ] implement resume path:
  - [ ] release stale worker claims
  - [ ] rebuild candidates
  - [ ] compute incomplete executions = all - machine_end
  - [ ] print status from `load_status()`
- [ ] build root/resource state
- [ ] define `dispatch(item)` coroutine
- [ ] run scheduler loop and gate toggler
- [ ] handle Ctrl+C gracefully (save state via durable backends and stop)
- [ ] post-run report + optional cleanup

### Acceptance
- [ ] Orchestration tests pass

---

## Milestone G — Integration tests and behavior checks

### Integration tests (write first)
- [ ] `test_end_to_end_designed_roots_complete`
- [ ] `test_stop_and_resume_completes_remaining_work`
- [ ] `test_slow_gate_toggle_blocks_and_recovers_progress`
- [ ] `test_checkpoint_cleanup_removes_completed_executions`

### Implementation tasks
- [ ] add integration fixtures for temp db + deterministic timing
- [ ] keep `fail_rate` configurable for deterministic and failure-path runs
- [ ] verify final root completion counts

### Acceptance
- [ ] Integration suite passes in local venv

---

## Milestone H — README and operator UX

- [ ] Document exact commands:
  - [ ] fresh run
  - [ ] resume run
  - [ ] deterministic run (`--seed`, `--fail-rate 0`)
- [ ] Document expected output patterns for both designed roots
- [ ] Document how to interrupt and resume
- [ ] Document cleanup behavior

### Acceptance
- [ ] New user can run example without opening source files

---

## 6) Execution order checklist (strict)

- [ ] A: Create tests skeleton
- [ ] B: Implement `task_machine.py` (green)
- [ ] C: Implement `hooks.py` (green)
- [ ] D: Implement `scheduler.py` (green)
- [ ] E: Implement durable candidate rebuild (green)
- [ ] F: Implement `main.py` orchestration (green)
- [ ] G: Integration tests (green)
- [ ] H: README polish
- [ ] Final: run full targeted test set + manual smoke run

---

## 7) Command checklist for development

- [ ] Run unit tests for this feature set:
  - [ ] `.venv/bin/pytest ../../python/tests/unit/test_dfss_task_machine.py -q`
  - [ ] `.venv/bin/pytest ../../python/tests/unit/test_dfss_hooks.py -q`
  - [ ] `.venv/bin/pytest ../../python/tests/unit/test_dfss_scheduler.py -q`
- [ ] Run integration tests:
  - [ ] `.venv/bin/pytest ../../python/tests/integration/test_dfss_pipeline.py -q`
- [ ] Run all new tests together before merge:
  - [ ] `.venv/bin/pytest ../../python/tests/unit/test_dfss_*.py ../../python/tests/integration/test_dfss_pipeline.py -q`

---

## 8) Definition of done

- [ ] All new tests pass
- [ ] Fresh run demonstrates DFS + saturation behavior
- [ ] Interruption and resume work without manual repair
- [ ] Completed/incomplete execution reporting works
- [ ] Cleanup deletes completed checkpoints
- [ ] README is runnable and accurate
- [ ] Code is formatted and lint-clean per project standards

---

## 9) Known risks and mitigation

- [ ] **Risk:** candidate index drift from pool state
  - [ ] Mitigation: helper invariants + rebuild-from-db on startup
- [ ] **Risk:** nondeterministic test failures due to randomness/timing
  - [ ] Mitigation: seeded RNG + short deterministic intervals in tests
- [ ] **Risk:** gate toggle race in integration tests
  - [ ] Mitigation: use controlled test interval and bounded assertions (invariants, not exact line order)

---

## 10) Optional stretch tasks (after core done)

- [ ] Add `--no-gate-toggle` mode for deterministic demos
- [ ] Add JSON summary output mode for automated verification
- [ ] Add scheduler trace logging flag for scoring diagnostics
