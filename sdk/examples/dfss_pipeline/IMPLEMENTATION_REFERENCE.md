# DFSS Pipeline — Implementation Reference

> What changed in the SDK since PLAN_v2.md was written, and how to
> implement the example using the current APIs.

## SDK changes that affect this example

All changes are on branch `lifecycle-support-try-2`.

### 1. `lifecycle.py` helpers are gone

PLAN_v2.md references `list_executions()` and `cleanup_executions()` from
`flatmachines.lifecycle`. Those were rejected — they were thin loops over
backend methods. The methods now live directly on `PersistenceBackend`:

```python
# Old (dead code)
from flatmachines.lifecycle import list_executions, cleanup_executions
snaps = await list_executions(backend, exec_ids)
await cleanup_executions(backend, exec_ids)

# New
exec_ids = await backend.list_execution_ids()
for eid in exec_ids:
    await backend.delete_execution(eid)
```

### 2. `list_execution_ids(event=...)` filtering

All three backends (Local, Memory, SQLite) now accept an optional `event`
keyword argument:

```python
# All executions
all_ids = await backend.list_execution_ids()

# Only completed
done_ids = await backend.list_execution_ids(event="machine_end")

# Incomplete = set difference
incomplete = set(all_ids) - set(done_ids)
```

This replaces `requeue_interrupted()` from PLAN_v2.md. No raw checkpoint
scanning needed.

### 3. `CheckpointManager.load_status()`

Lightweight peek at execution state without deserializing full context:

```python
manager = CheckpointManager(backend, execution_id)
status = await manager.load_status()  # -> ("state_exit", "step_2") or None
if status and status[0] == "machine_end":
    print("completed")
```

### 4. `SQLiteCheckpointBackend` and `SQLiteLeaseLock`

New backends in flatmachines. Single SQLite file replaces `.checkpoints/`
directory sprawl:

```python
from flatmachines import SQLiteCheckpointBackend, SQLiteLeaseLock

backend = SQLiteCheckpointBackend(db_path="data/dfss.sqlite")
lock = SQLiteLeaseLock(
    db_path="data/dfss.sqlite",  # can share the same file
    owner_id=f"{hostname}:{pid}",
    ttl_seconds=300,
    renew_interval_seconds=100,
)
```

Tables created automatically: `machine_checkpoints`, `machine_latest`,
`execution_leases`.

### 5. `WorkPool` moved to `flatmachines.work`

`WorkPool`, `WorkItem`, `WorkBackend` and implementations moved from
`distributed.py` to `work.py`. Old imports still work (re-exported for
backward compat).

```python
from flatmachines.work import (
    WorkPool, WorkItem, WorkBackend,
    MemoryWorkBackend, SQLiteWorkBackend,
    create_work_backend,
)
```

### 6. Peer machines inherit persistence + lock

`FlatMachine._launch_and_write` now passes `persistence=self.persistence`
and `lock=self.lock` to peer machines. No `LeaseFlatMachine` subclass
needed.

---

## What replaces `FileWorkQueue`

PLAN_v2.md defines a custom `FileWorkQueue` (JSON-backed, ~60 lines). Use
`WorkPool` instead — it already has `push`, `claim`, `complete`, `fail`,
`release_by_worker`, and `size`, backed by either Memory or SQLite.

```python
from flatmachines.work import SQLiteWorkBackend

work_backend = SQLiteWorkBackend(db_path="data/dfss.sqlite")
pool = work_backend.pool("tasks")

# Seed
await pool.push({"task_id": "root-000/0", "root_id": "root-000", "depth": 0,
                  "resource_class": "fast", "has_expensive_descendant": False})

# Claim (FIFO — scheduler decides WHICH pool/item externally)
item = await pool.claim("scheduler")

# After task completes, enqueue children
for child in result["children"]:
    await pool.push(child)
await pool.complete(item.id)

# On crash recovery
released = await pool.release_by_worker("scheduler")
```

### What WorkPool doesn't do (scheduler owns this)

- **Priority scoring** — `score()` evaluates candidates against runtime state
  (active roots, gate status). The pool is unordered; the scheduler imposes order.
- **Resource gating** — `is_gate_open("slow")` is scheduler logic.
- **DFS ordering** — depth preference is in the scoring function, not the pool.

The PLAN_v2.md scheduler's `pick_next()` function stays exactly as designed.
It just reads candidates from the pool and scores them instead of reading
from a JSON file.

### Reading candidates for scoring

`WorkPool.claim()` is atomic FIFO — it picks for you. But the DFSS scheduler
needs to evaluate all candidates before choosing. Two approaches:

**Option A: Multiple pools by resource class.** The scheduler decides which
pool to claim from based on gate status and scoring. Loses cross-pool
priority but simple:

```python
fast_pool = work_backend.pool("fast")
slow_pool = work_backend.pool("slow")

# Scheduler picks which pool
if slow_gate_open and await slow_pool.size() > 0:
    item = await slow_pool.claim("scheduler")
elif await fast_pool.size() > 0:
    item = await fast_pool.claim("scheduler")
```

**Option B: Single pool, in-memory candidate list.** Push to WorkPool for
durability, but maintain an in-memory list for scoring. On restart, rebuild
from pool. This is closest to PLAN_v2.md's design:

```python
# In-memory candidate tracking (rebuilt on restart from pool state)
candidates: list[dict] = []

# After push
candidates.append(item_data)
await pool.push(item_data)

# Score and pick
best = max(candidates, key=lambda c: score(c, roots, ...))
candidates.remove(best)
claimed = await pool.claim("scheduler")  # FIFO, but we've tracked what's there
```

Option B is what PLAN_v2.md effectively does with `FileWorkQueue.items`.
The WorkPool provides crash durability; the in-memory list provides
scoring. On restart, scan pool to rebuild the list.

---

## Revised file layout

```
sdk/python/examples/dfss_pipeline/
├── PLAN_v2.md                      # Original plan (for reference)
├── IMPLEMENTATION_REFERENCE.md     # This file
├── README.md                       # How to run, what to observe
├── main.py                         # Entry point: seed, run, stop/start, report
├── scheduler.py                    # DFSS scheduler (~150 lines, unchanged)
├── task_machine.py                 # Single machine config (inline dict)
└── hooks.py                        # Simulated work: designed + random trees
```

`work_queue.py` is gone — replaced by `WorkPool`.

## Revised main.py sketch

```python
import asyncio
import random
from flatmachines import FlatMachine, SQLiteCheckpointBackend, CheckpointManager
from flatmachines.work import SQLiteWorkBackend

from scheduler import RootState, ResourcePool, score, pick_next, run
from hooks import TaskHooks, DESIGNED_TREES
from task_machine import task_config

DB_PATH = "data/dfss.sqlite"


async def main():
    args = parse_args()

    backend = SQLiteCheckpointBackend(db_path=DB_PATH)
    work_backend = SQLiteWorkBackend(db_path=DB_PATH)
    pool = work_backend.pool("tasks")

    if args.resume:
        print(f"Resuming: {await pool.size()} pending tasks")
        # Release anything claimed by a previous crashed run
        released = await pool.release_by_worker("scheduler")
        if released:
            print(f"  Released {released} stale claims")

        # Find incomplete machine executions and requeue them
        all_ids = await backend.list_execution_ids()
        done_ids = set(await backend.list_execution_ids(event="machine_end"))
        for eid in all_ids:
            if eid not in done_ids:
                # Check if it's actually in the pool already
                # If not, requeue it (it was in-flight when we crashed)
                status = await CheckpointManager(backend, eid).load_status()
                if status:
                    print(f"  Resumable: {eid} (event={status[0]}, state={status[1]})")
    else:
        # Seed designed roots
        seed_designed_roots(pool)
        for i in range(2, args.roots):
            root_id = f"root-{i:03d}"
            await pool.push({
                "task_id": f"{root_id}/0",
                "root_id": root_id,
                "depth": 0,
                "resource_class": random.choice(["fast", "slow"]),
                "has_expensive_descendant": False,
            })

    # Build root state by scanning pool
    # (WorkPool doesn't expose iteration, so track in-memory)
    roots = build_root_states_from_pool(pool)

    resources = {
        "fast": ResourcePool("fast", capacity=4),
        "slow": ResourcePool("slow", capacity=2),
    }

    hooks = TaskHooks(max_depth=args.max_depth, fail_rate=0.15)

    async def dispatch(item):
        machine = FlatMachine(
            config_dict=task_config(),
            hooks=hooks,
            persistence=backend,
        )
        result = await machine.execute(input=item.data)

        if not result.get("error"):
            children = result.get("children", [])
            for child in children:
                await pool.push(child)
                roots[child["root_id"]].pending += 1

        await pool.complete(item.id)
        return result

    toggler = asyncio.create_task(toggle_gate(resources))

    try:
        await run(pool, roots, resources, dispatch,
                  max_workers=args.max_workers, max_active_roots=3)
    except KeyboardInterrupt:
        pass
    finally:
        toggler.cancel()

    # Report
    all_ids = await backend.list_execution_ids()
    done_ids = await backend.list_execution_ids(event="machine_end")
    print(f"\nExecutions: {len(all_ids)} total, {len(done_ids)} completed")

    # Cleanup
    for eid in done_ids:
        await backend.delete_execution(eid)
    print(f"Cleaned up {len(done_ids)} completed checkpoints.")
```

## Key differences from PLAN_v2.md

| PLAN_v2.md | Now |
|------------|-----|
| `FileWorkQueue("data/work_queue.json")` | `SQLiteWorkBackend("data/dfss.sqlite").pool("tasks")` |
| `LocalFileBackend()` | `SQLiteCheckpointBackend(db_path="data/dfss.sqlite")` |
| `list_executions(backend, exec_ids)` | `backend.list_execution_ids()` |
| `cleanup_executions(backend, exec_ids)` | `backend.delete_execution(eid)` per ID |
| `requeue_interrupted(queue, backend)` | `pool.release_by_worker()` + `list_execution_ids(event=...)` set diff |
| Scan `.checkpoints/` dirs for exec IDs | `backend.list_execution_ids()` |
| `queue.save()` after completions | Automatic (SQLite) |
| `work_queue.py` (~60 lines) | Deleted |

## What stays unchanged from PLAN_v2.md

- **`scheduler.py`** — `RootState`, `ResourcePool`, `score()`, `pick_next()`, main loop. All unchanged.
- **`hooks.py`** — `DESIGNED_TREES`, `TaskHooks`. All unchanged.
- **`task_machine.py`** — Single machine config dict. Unchanged.
- **Machine-level `on_error`** — Still works as designed.
- **`persistence.resume`** — Still works. SQLite backend is just a different storage layer.
- **The scheduling algorithm** — DFS scoring, gate toggling, resource saturation. All scheduler logic, not affected by backend changes.
- **Expected output** — Same observable behavior. Different storage.

## Import summary

```python
# Persistence
from flatmachines import (
    SQLiteCheckpointBackend,   # new
    CheckpointManager,         # existing
    MachineSnapshot,           # existing
    FlatMachine,               # existing
)

# Work pool
from flatmachines.work import (
    SQLiteWorkBackend,         # moved from distributed.py
    WorkPool,                  # moved from distributed.py
)

# Locking (if needed for multi-process)
from flatmachines import SQLiteLeaseLock  # new
```
