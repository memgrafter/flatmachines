# DFSS Pipeline Example — Implementation Plan (branch-aware)

## Objective
Implement `PLAN_v2.md` behavior in `sdk/examples/dfss_pipeline/` using current SDK APIs on branch `lifecycle-support-try-2`, with stop/start durability and observable DFS + resource saturation behavior.

## Inputs reviewed
- `PLAN_v2.md`
- `IMPLEMENTATION_REFERENCE.md`
- `/Users/trentrobbins/code/flatagents/AGENTS.md`
- Branch delta vs `main` (SQLite persistence/work + lifecycle API changes)

---

## Branch reality (must account for)
1. `flatmachines.lifecycle` helpers are removed.
   - Use `backend.list_execution_ids()` and `backend.delete_execution()` directly.
2. `list_execution_ids(event=...)` exists (all backends).
   - Completed = `event="machine_end"`.
3. `CheckpointManager.load_status()` exists.
4. `SQLiteCheckpointBackend` and `SQLiteLeaseLock` exist.
5. `WorkPool` moved to `flatmachines.work`.
6. `_launch_and_write` now propagates persistence + lock.

### Important behavior mismatches vs PLAN_v2 text
- Machine-level `data.on_error` is not implemented in runtime path; use **state-level** `on_error`.
- `persistence.resume` config block in plan is not auto-applied by runtime loop; use explicit `resume_from=execution_id` orchestration where needed.

---

## Final architecture

### Storage
- Single SQLite file: `data/dfss.sqlite`
  - `SQLiteCheckpointBackend(db_path=...)`
  - `SQLiteWorkBackend(db_path=...)` (pool name: `tasks`)

### Runtime pieces
- `task_machine.py`: one reusable task machine config
- `hooks.py`: designed trees + random trees + transient failures
- `scheduler.py`: DFSS scoring/pick/run loop
- `main.py`: seed/resume/orchestration/reporting/cleanup
- `README.md`: run + expected observations + resume flow

---

## Implementation decisions

### 1) Error handling in task machine
Use state-level `on_error` on `execute_task` -> `error_exit` final state.

### 2) Child output typing
Return `children` as structured list in final output using bare-path templates (e.g. `"children": "context.children"`) to preserve type.

### 3) WorkPool + DFSS scoring reconciliation
DFSS needs global candidate scoring; `WorkPool.claim()` is FIFO.

Plan for example:
- Maintain scheduler-side candidate index in memory (authoritative for scoring).
- Persist each item in `WorkPool` for durability.
- On restart, rebuild candidate index from SQLite `work_pool` pending rows.
- Single scheduler process assumption (no competing schedulers).

(If we later need multi-scheduler safety, add claim-by-id primitive in SDK.)

### 4) Resume semantics
- On `--resume`:
  - release stale claims: `pool.release_by_worker("scheduler")`
  - reload pending items from DB into candidate index
  - inspect incomplete executions via set difference:
    - `all_ids = list_execution_ids()`
    - `done_ids = list_execution_ids(event="machine_end")`
  - report resumable status via `CheckpointManager.load_status()`

---

## File-by-file checklist

## `task_machine.py`
- [ ] Add `task_config()` returning inline flatmachine dict.
- [ ] Context fields: `task_id`, `root_id`, `depth`, `resource_class`, `has_expensive_descendant`, `children`, `result`.
- [ ] States:
  - `start` (initial) -> `execute_task`
  - `execute_task` (action=`run_task`, `on_error: error_exit`) -> `done`
  - `done` (final) outputs typed fields
  - `error_exit` (final) outputs `task_id`, `root_id`, `error`

## `hooks.py`
- [ ] Implement `DESIGNED_TREES` for `root-000` and `root-001` exactly as plan.
- [ ] Implement `TaskHooks(MachineHooks)` with `on_action("run_task", context)`.
- [ ] Random mode: depth-capped 0–2 children, random resource class.
- [ ] Transient failure injection via `fail_rate`.

## `scheduler.py`
- [ ] Add `RootState` dataclass.
- [ ] Add `ResourcePool` dataclass.
- [ ] Implement `score(item, root, is_active)` with factors from PLAN_v2.
- [ ] Implement `pick_next(candidates, roots, resources, max_active_roots)`.
- [ ] Implement `run(...)` main async loop:
  - fill slots
  - `asyncio.wait(FIRST_COMPLETED)`
  - immediate refill
  - idle sleep when blocked
- [ ] Helpers:
  - `enqueue_children(...)`
  - `refresh_expensive_flag(...)`

## `main.py`
- [ ] CLI args: `--roots`, `--resume`, `--max-depth`, `--max-workers`, `--db-path`.
- [ ] Init backends:
  - `SQLiteCheckpointBackend`
  - `SQLiteWorkBackend` + `pool("tasks")`
- [ ] Seed path (non-resume): designed roots + random roots.
- [ ] Resume path:
  - release stale claims
  - rebuild candidates from DB pending rows
  - list/report incomplete executions via `event` filter
- [ ] Build root states from candidate set.
- [ ] Dispatch function:
  - create `FlatMachine(config_dict=task_config(), hooks=TaskHooks(...), persistence=backend)`
  - execute task
  - on success: enqueue children to pool + candidates + root counters
  - on error final output: bounded requeue policy
  - update resource/root in-flight counters
  - print structured progress lines
- [ ] Gate toggler task for `slow` resource.
- [ ] KeyboardInterrupt handling + graceful shutdown.
- [ ] Post-run reporting:
  - execution totals/completed via backend methods
  - stats summary
- [ ] Optional cleanup mode (or default cleanup) using `delete_execution(eid)`.

## `README.md`
- [ ] Explain scenarios demonstrated (root-000, root-001).
- [ ] Document run commands:
  - fresh run
  - interrupt + resume
- [ ] Document expected observable scheduling behaviors.
- [ ] Note SQLite file path and cleanup behavior.

---

## Validation checklist

### Functional
- [ ] Fresh run (`--roots 8`) shows DFS preference and root admission behavior.
- [ ] root-000 yields two slow d=2 tasks that can saturate two slow slots when gate open.
- [ ] root-001 cheap predecessor chain is prioritized to reach deep slow bottleneck.

### Failure + resume
- [ ] Inject transient failures (`fail_rate ~0.15`) and observe retries/requeue behavior.
- [ ] Interrupt mid-run (`Ctrl+C`), then `--resume` continues from pending queue/checkpoints.

### API alignment
- [ ] No usage of removed `flatmachines.lifecycle` helpers.
- [ ] Use `list_execution_ids(event="machine_end")` and `delete_execution` only.
- [ ] Use `flatmachines.work` imports.

---

## Suggested implementation order
1. `task_machine.py` + `hooks.py`
2. `scheduler.py` (pure logic, no IO)
3. `main.py` seed + dispatch + run loop wiring
4. Resume/recovery/reporting + cleanup
5. `README.md` and output polish

---

## Risks / follow-ups
- Candidate scoring with `WorkPool` requires scheduler-local candidate tracking (single-process assumption).
- If we need strict atomic claim-by-priority across processes, add SDK support for claim-by-id or pending iteration + CAS claim.
