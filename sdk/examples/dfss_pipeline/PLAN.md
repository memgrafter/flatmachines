# DFSS Pipeline Example — Plan

> A self-contained Python example demonstrating depth-first saturation
> scheduling (DFSS) of FlatMachine pipelines. Uses the new machine-level
> `on_error` and `persistence.resume` features. No real LLM calls — all
> work is simulated via hooks so the example runs instantly.

## Goal

Capture the essential dynamics of `research_paper_analysis_v2` in a small,
runnable example that a developer can read in 15 minutes and adapt for their
own multi-phase pipeline. The example should be the idealized target
architecture for an rpav3 rewrite.

## What the example demonstrates

1. **Multi-phase pipeline** with resource-gated phases (cheap model, expensive
   model) — mirrors rpav2's prep → expensive → wrap.
2. **Depth-first scheduling** — roots closest to completion are scheduled first;
   new roots are only admitted when active roots are blocked or done.
3. **Resource saturation** — constrained resource pools (e.g., expensive model
   slots) are kept fully utilized whenever gate-open work exists.
4. **Machine-level `on_error`** — machines declare a default error handler in
   config, eliminating per-state `on_error` boilerplate.
5. **`persistence.resume`** — machines auto-retry from checkpoint on transient
   infrastructure failures.
6. **Lifecycle helpers** — `list_executions()` and `cleanup_executions()` for
   post-run introspection and cleanup.
7. **Simulated transient failures** — hooks randomly fail to show resilience in
   action.

## What the example does NOT include

- Real LLM calls or model providers
- SQLite work queue (uses in-memory structures for clarity)
- Production concerns (signal handling, graceful drain, budget tracking)
- The full DFSS spec (scoring weights, starvation SLAs, etc.)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Scheduler (dfss_scheduler.py)                              │
│                                                             │
│  Work queue: in-memory list of WorkItems                    │
│  Resource gates: dict of {resource_class: bool}             │
│  Active root set: bounded set of root_ids                   │
│                                                             │
│  Loop:                                                      │
│    1. Score candidates (depth-first + saturation)           │
│    2. Dispatch top candidates to free worker slots           │
│    3. On completion: unlock successors, update root state   │
│    4. Repeat on any completion (no batch boundaries)        │
│    5. If idle: poll / exit when all roots done              │
└─────────┬───────────────────────────┬───────────────────────┘
          │                           │
          ▼                           ▼
┌─────────────────┐         ┌─────────────────────┐
│  prep_machine   │         │  expensive_machine   │
│  (cheap model)  │         │  (expensive model)   │
│  1 hook action  │         │  1 hook action        │
│  on_error ───►  │         │  on_error ───►        │
│  resume: 1      │         │  resume: 1            │
└─────────────────┘         └─────────────────────┘
          │
          ▼
┌─────────────────┐
│  wrap_machine   │
│  (cheap model)  │
│  2 hook actions │
│  on_error ───►  │
│  resume: 1      │
└─────────────────┘
```

### Pipeline per root

Each root (simulated "paper") flows through:

```
prep (cheap, 1 action) → expensive (expensive, 1 action) → wrap (cheap, 2 actions)
   depth=0                  depth=1                           depth=2
```

### Resource classes

| Class | Simulated capacity | Used by |
|-------|-------------------|---------|
| `cheap` | 4 slots | prep, wrap |
| `expensive` | 2 slots | expensive |

### Transient failures

Hooks randomly raise errors (~20% chance) to exercise:
- Machine-level `on_error` routing to a recovery state
- `persistence.resume` auto-retry from checkpoint

## File layout

```
sdk/python/examples/dfss_pipeline/
├── PLAN.md                    # This file
├── README.md                  # How to run, what to observe
├── main.py                    # Entry point — seeds roots, runs scheduler
├── dfss_scheduler.py          # The scheduler (~120 lines)
│                              #   WorkItem, RootState, ResourceState
│                              #   score(), pick_next(), run_loop()
├── machines.py                # Machine configs (inline dicts, no YAML files)
│                              #   prep_config(), expensive_config(), wrap_config()
│                              #   All use on_error + persistence.resume
├── hooks.py                   # Simulated hook actions
│                              #   PrepHooks, ExpensiveHooks, WrapHooks
│                              #   Random transient failures
└── pipeline.py                # Glue: dispatch WorkItem → FlatMachine.execute()
                               #   On completion: enqueue successors
                               #   On failure: mark retryable or terminal
```

## Scheduler design (dfss_scheduler.py)

### Data structures

```python
@dataclass
class WorkItem:
    id: str
    root_id: str
    depth: int                         # 0=prep, 1=expensive, 2=wrap
    resource_class: str                # "cheap" or "expensive"
    phase: str                         # "prep", "expensive", "wrap"
    payload: dict                      # input data for machine
    ready_at: float = 0.0              # unix ts, 0 = ready now
    attempts: int = 0
    max_attempts: int = 3
    execution_id: Optional[str] = None # for resume

@dataclass
class RootState:
    root_id: str
    admitted: bool = False
    in_flight: int = 0
    completed_phases: set = field(default_factory=set)

    @property
    def remaining_depth(self) -> int:
        return 3 - len(self.completed_phases)

    @property
    def is_complete(self) -> bool:
        return self.remaining_depth == 0

@dataclass
class ResourceState:
    capacity: int
    in_flight: int = 0
    gate_open: bool = True

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.in_flight) if self.gate_open else 0
```

### Scoring

```python
def score(item: WorkItem, root: RootState, active_roots: set) -> float:
    s = 0.0
    s += 100.0 if root.root_id in active_roots else 0.0   # continuation
    s += 10.0 * item.depth                                  # depth-first
    s -= 5.0 * root.remaining_depth                         # closer to done
    s += 1.0 * (time.time() - item.ready_at)               # age fairness
    return s
```

### Pick next

```python
def pick_next(ready, roots, resources, active_roots, max_active) -> Optional[WorkItem]:
    # Filter: gate open, resource has capacity
    candidates = [
        w for w in ready
        if resources[w.resource_class].available > 0
        and time.time() >= w.ready_at
    ]
    if not candidates:
        return None

    # Prefer active roots; admit new root only if active roots can't fill slots
    active_candidates = [w for w in candidates if roots[w.root_id].admitted]
    if active_candidates:
        candidates = active_candidates
    elif len([r for r in roots.values() if r.admitted and not r.is_complete]) >= max_active:
        # Active set full and has runnable work — block new roots
        return None

    # Score and pick
    best = max(candidates, key=lambda w: score(w, roots[w.root_id], {r.root_id for r in roots.values() if r.admitted}))
    return best
```

### Main loop

```python
async def run_scheduler(
    roots: dict[str, RootState],
    ready: list[WorkItem],
    resources: dict[str, ResourceState],
    dispatch: Callable,         # (WorkItem) -> Awaitable[result]
    max_workers: int = 6,
    max_active_roots: int = 3,
) -> dict:
    active = set()              # asyncio.Task set

    while True:
        # Fill free slots
        while len(active) < max_workers:
            item = pick_next(ready, roots, resources,
                           {r for r in roots if roots[r].admitted},
                           max_active_roots)
            if item is None:
                break
            ready.remove(item)
            roots[item.root_id].admitted = True
            roots[item.root_id].in_flight += 1
            resources[item.resource_class].in_flight += 1
            task = asyncio.create_task(dispatch(item))
            task.work_item = item
            active.add(task)

        if not active:
            if all(r.is_complete for r in roots.values()):
                break
            if not ready:
                break
            await asyncio.sleep(0.1)
            continue

        done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            active.discard(task)
            item = task.work_item
            roots[item.root_id].in_flight -= 1
            resources[item.resource_class].in_flight -= 1
            # Callback handles: enqueue successor, requeue on failure, etc.
```

## Machine configs (machines.py)

All three machines use inline config dicts. Key features:

```python
def prep_config():
    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "prep",
            "on_error": "handle_error",       # machine-level default
            "persistence": {
                "enabled": True,
                "backend": "memory",
                "resume": {                    # auto-retry from checkpoint
                    "max_retries": 1,
                    "backoffs": [0.1],
                },
            },
            "context": {
                "root_id": "input.root_id",
                "data": "input.data",
            },
            "states": {
                "start": {
                    "type": "initial",
                    "transitions": [{"to": "do_prep"}],
                },
                "do_prep": {
                    "action": "simulate_prep",
                    # No per-state on_error needed — machine-level catches it
                    "transitions": [{"to": "done"}],
                },
                "done": {
                    "type": "final",
                    "output": {
                        "root_id": "{{ context.root_id }}",
                        "prep_result": "{{ context.prep_result }}",
                    },
                },
                "handle_error": {
                    "type": "final",
                    "output": {
                        "root_id": "{{ context.root_id }}",
                        "error": "{{ context.last_error }}",
                    },
                },
            },
        },
    }
```

`expensive_config()` and `wrap_config()` follow the same pattern with different
action names and outputs.

## Hooks (hooks.py)

Simulated work with random transient failures:

```python
class PipelineHooks(MachineHooks):
    def __init__(self, fail_rate: float = 0.2):
        self.fail_rate = fail_rate

    def on_action(self, action_name, context):
        # Simulate work
        if action_name == "simulate_prep":
            if random.random() < self.fail_rate:
                raise RuntimeError("Transient prep failure")
            context["prep_result"] = f"prepped-{context.get('root_id')}"

        elif action_name == "simulate_expensive":
            if random.random() < self.fail_rate:
                raise RuntimeError("Transient expensive failure")
            context["expensive_result"] = f"analyzed-{context.get('root_id')}"

        elif action_name == "simulate_wrap":
            if random.random() < self.fail_rate:
                raise RuntimeError("Transient wrap failure")
            context["wrap_result"] = f"wrapped-{context.get('root_id')}"

        elif action_name == "simulate_finalize":
            context["final_report"] = f"report-{context.get('root_id')}"

        return context
```

## Pipeline glue (pipeline.py)

Dispatches a WorkItem to the appropriate FlatMachine and handles the result:

```python
async def dispatch(item: WorkItem, hooks, backend) -> DispatchResult:
    config = {"prep": prep_config, "expensive": expensive_config, "wrap": wrap_config}[item.phase]()

    machine = FlatMachine(
        config_dict=config,
        hooks=hooks,
        persistence=backend,
    )
    item.execution_id = machine.execution_id

    try:
        result = await machine.execute(input=item.payload)
        if "error" in result:
            return DispatchResult(item, success=False, retryable=True, error=result["error"])
        return DispatchResult(item, success=True, output=result)
    except Exception as exc:
        return DispatchResult(item, success=False, retryable=True, error=str(exc))
```

## Entry point (main.py)

```python
async def main():
    # Seed 10 roots
    roots = {}
    ready = []
    for i in range(10):
        root_id = f"paper-{i:03d}"
        roots[root_id] = RootState(root_id=root_id)
        ready.append(WorkItem(
            id=f"{root_id}-prep",
            root_id=root_id,
            depth=0,
            resource_class="cheap",
            phase="prep",
            payload={"root_id": root_id, "data": f"abstract-{i}"},
        ))

    resources = {
        "cheap": ResourceState(capacity=4),
        "expensive": ResourceState(capacity=2),
    }

    hooks = PipelineHooks(fail_rate=0.15)
    backend = MemoryBackend()

    async def on_dispatch(item):
        result = await dispatch(item, hooks, backend)
        if result.success:
            successor = make_successor(item, result.output)
            if successor:
                ready.append(successor)
            else:
                roots[item.root_id].completed_phases.add(item.phase)
                # Mark root complete if wrap done
        elif result.retryable and item.attempts < item.max_attempts:
            item.attempts += 1
            item.ready_at = time.time() + 0.5  # backoff
            ready.append(item)
        else:
            print(f"  ✗ {item.root_id} terminal failure: {result.error}")

        return result

    stats = await run_scheduler(roots, ready, resources, on_dispatch,
                                max_workers=6, max_active_roots=3)

    # Post-run: use lifecycle helpers
    execution_ids = [...]  # collected during dispatch
    snapshots = await list_executions(backend, execution_ids)
    print(f"Completed: {sum(1 for s in snapshots if s.event == 'machine_end')}")
    await cleanup_executions(backend, execution_ids)
```

## Expected output

```
🚀 DFSS Pipeline Example — 10 roots, 3 phases, 2 resource classes
================================================================
  ✓ paper-000 prep complete (depth=0, cheap)
  ✓ paper-001 prep complete (depth=0, cheap)
  ✓ paper-002 prep complete (depth=0, cheap)
  ⟳ paper-000 expensive retrying (attempt 2/3)
  ✓ paper-000 expensive complete (depth=1, expensive)
  ✓ paper-000 wrap complete (depth=2, cheap) — ROOT DONE
  ✓ paper-001 expensive complete (depth=1, expensive)
  ✓ paper-003 prep complete (depth=0, cheap)      ← new root admitted
  ✓ paper-001 wrap complete (depth=2, cheap) — ROOT DONE
  ...

Summary:
  Roots completed: 10/10
  Total dispatches: 38 (30 phases + 8 retries)
  Active root high-water: 3
  Resource utilization: cheap=78%, expensive=91%
```

Key things to observe:
- paper-000 completes all 3 phases before paper-003 even starts prep (DFS)
- expensive slots are never idle when prepped roots exist (saturation)
- new roots admitted only when active roots are blocked/done
- transient failures handled transparently by machine-level `on_error` and
  `persistence.resume` — no retry logic in the scheduler

## Line count estimate

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~60 | Seed, configure, run, report |
| `dfss_scheduler.py` | ~120 | WorkItem, RootState, ResourceState, score, pick, loop |
| `machines.py` | ~80 | 3 machine configs (inline dicts) |
| `hooks.py` | ~40 | Simulated actions with random failures |
| `pipeline.py` | ~50 | Dispatch + successor enqueue |
| `README.md` | ~60 | How to run, what to observe |
| **Total** | **~410** | |

---

## How this reduces rpav3 code vs rpav2

### rpav2 line counts (scheduling + infra)

| File | Lines | What it does |
|------|-------|-------------|
| `run.py` | 1175 | Scheduler loop, claim functions, DB setup, resume scanning, stale release, budget, seeding, signal handling, CLI |
| `sqlite_checkpoint_backend.py` | 188 | Custom PersistenceBackend for SQLite |
| `sqlite_lease_lock.py` | 172 | Custom ExecutionLock with heartbeat |
| `lease_flatmachine.py` | 45 | FlatMachine subclass for lock propagation |
| `v2_executions.sql` | 64 | Schema: executions, daily_usage, leases, checkpoints |
| `hooks.py` (error handling) | ~250 | `mark_execution_failed` with transient classification, 429 gating, status reset |
| **Scheduling + infra subtotal** | **~1894** | |

### What rpav3 eliminates or reduces

| rpav2 concern | Lines | rpav3 approach | Savings |
|---------------|-------|----------------|---------|
| Per-state `on_error` boilerplate (3 machines × ~6 states each) | ~50 | Machine-level `on_error` | **-50** |
| `mark_execution_failed` transient classification + status reset | ~250 | Machine-level `on_error` routes to recovery state; `persistence.resume` handles infra errors. Hooks just set `context.last_error`. | **-200** |
| `_pick_next()` — phase priority, watermark, 429 gating | ~100 | DFSS `pick_next()` with scoring. Phase priority is implicit in depth. Watermark is implicit in `max_active_roots`. 429 gating is `gate_open` flag. | **-60** (net: simpler, fewer special cases) |
| `run_continuous()` — main loop, semaphores, batch-free dispatch | ~120 | DFSS `run_scheduler()` — same structure but generic | **-80** (replaced by reusable scheduler) |
| `find_incomplete_executions()` — checkpoint DB query for resume | ~25 | `persistence.resume` handles this inside the machine. Scheduler doesn't scan for incompletes. | **-25** |
| `release_stale()` — reset stuck transient statuses | ~20 | `persistence.resume` + machine-level `on_error` means fewer stuck executions. Stale release becomes simpler (just age-based cleanup). | **-10** |
| `reset_orphaned_executions()` | ~25 | Same cleanup, but less needed since machines self-recover | **-15** |
| `claim_for_prep/expensive/wrap` — 3 separate claim functions | ~60 | Single `claim_ready(resource_class)` | **-40** |
| `run_prep/run_expensive/run_wrap` — 3 dispatch functions | ~100 | Single `dispatch(item)` — config lookup by phase | **-70** |
| `resume_machine()` — separate resume path | ~20 | Eliminated — `persistence.resume` is internal | **-20** |
| `lease_flatmachine.py` — lock propagation subclass | 45 | Still needed if using SQLite leases, but simpler (no resume logic) | **-10** |

### Estimated savings

| Category | rpav2 lines | rpav3 estimate | Reduction |
|----------|-------------|----------------|-----------|
| Scheduling + dispatch | ~420 | ~180 | -240 (57%) |
| Error handling + resilience | ~300 | ~40 | -260 (87%) |
| Machine configs (on_error boilerplate) | ~50 | ~0 | -50 (100%) |
| Resume/checkpoint scanning | ~70 | ~0 | -70 (100%) |
| Infra (backends, locks, schema) | ~470 | ~400 | -70 (15%) |
| Hooks (domain logic) | ~600 | ~550 | -50 (8%) |
| **Total scheduling + infra** | **~1894** | **~1170** | **-724 (38%)** |

The biggest wins come from:
1. **Machine-level `on_error` + `persistence.resume`** eliminates the entire
   transient error classification / status reset / per-state error routing layer
   (~300 lines → ~40).
2. **DFSS `pick_next` with scoring** replaces the ad-hoc phase priority +
   watermark + 429 special-casing with a single scoring function (~100 → ~40).
3. **Single dispatch function** replaces 3 phase-specific run functions + a
   separate resume function (~120 → ~50).

Hooks (domain logic like PDF download, text extraction, corpus signals,
terminology tagging) stay roughly the same — those are irreducible application
complexity.
