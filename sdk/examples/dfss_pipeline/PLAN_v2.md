# DFSS Pipeline Example — Plan v2

> A self-contained Python example demonstrating depth-first saturation
> scheduling of FlatMachine task trees. Uses machine-level `on_error`,
> `persistence.resume`, file persistence, and lifecycle helpers. Runs
> with no LLM — all work is simulated via hooks.

## Concept

A **task tree processor**. Each "root" starts as a single task. When a task
completes, it may dynamically spawn 0–2 child tasks, forming a tree of
arbitrary depth (capped at `max_depth`). Two resource classes (`fast` and
`slow`) constrain execution. The scheduler does genuine depth-first traversal
of each root's tree while saturating scarce resources across roots.

This is not phases or stages. The tree shape is discovered at runtime as
tasks complete and spawn children. DFS means: follow one root's branches
deep before expanding another root.

```
root-000 (designed):                     root-001 (designed):
  task(d=0, fast)                          task(d=0, fast)
  ├── task(d=1, fast)                      └── task(d=1, fast)
  │   ├── task(d=2, slow)  ← bottleneck        └── task(d=2, fast)
  │   └── task(d=2, slow)  ← bottleneck            └── task(d=3, slow) ← deep bottleneck
  └── task(d=1, fast)
      └── task(d=2, fast)  ← leaf

DFS order for root-000: d=0, d=1(left), d=2(slow), d=2(slow), d=1(right), d=2(leaf)
NOT: d=0(000), d=0(001), d=0(002)...
```

## Designed roots vs random roots

The first two roots have **hardcoded tree shapes** that deterministically
produce the key scheduling scenarios. The remaining roots are random,
providing background saturation pressure.

### root-000: Simultaneous slow-resource saturation

Tree shape guarantees two `slow` tasks land in the queue at the same time
(both at d=2, both children of the same d=1 task). When the slow gate is
open, the scheduler fills both slow slots simultaneously from this root.
This demonstrates: **k workers allocated to j jobs when j tasks are expensive.**

```
root-000/0 (d=0, fast)
├── root-000/0.0 (d=1, fast)
│   ├── root-000/0.0.0 (d=2, slow)   ← both enqueued together
│   └── root-000/0.0.1 (d=2, slow)   ← when parent completes
└── root-000/0.1 (d=1, fast)
    └── root-000/0.1.0 (d=2, fast)
```

### root-001: Expensive task gated behind cheap predecessors

A `slow` task exists at d=3, but cheap predecessors at d=0, d=1, d=2 must
complete first. The scheduler must drill through cheap tasks depth-first to
unblock the expensive work. The predecessor hint (`has_expensive_descendant`)
boosts the cheap tasks on this path so they're prioritized over cheap tasks
from other roots.

```
root-001/0 (d=0, fast, has_expensive_descendant=true)
└── root-001/0.0 (d=1, fast, has_expensive_descendant=true)
    └── root-001/0.0.0 (d=2, fast, has_expensive_descendant=true)
        └── root-001/0.0.0.0 (d=3, slow)   ← the bottleneck
```

### root-002..007: Random trees

Random children (0–2), random resource class, random depth. These provide
background work that fills resource slots when designed roots are blocked
or done.

## What the example demonstrates

1. **Depth-first scheduling** — deepest tasks in active roots run first; new
   roots admitted only when active roots are blocked or done.
2. **Resource saturation** — `slow` resource has 2 slots and its gate toggles
   on/off during the run. When open, the scheduler fills both slots immediately.
3. **Expensive-task prioritization** — tasks requiring `slow` resource score
   higher. When 2+ slow tasks are ready, they fill available slow slots before
   any cheap tasks run.
4. **Predecessor drilling** — cheap tasks that gate expensive descendants get
   a score boost, causing the scheduler to drill down the tree to unblock
   the expensive work.
5. **Dynamic work** — task tree shape is not known upfront. Children are
   discovered as tasks complete.
6. **Machine-level `on_error`** — single error handler declared at machine
   level; no per-state boilerplate.
7. **`persistence.resume`** — machines auto-retry from checkpoint on transient
   failures.
8. **File persistence + stop/start** — run the example, Ctrl+C mid-run, run
   again. Incomplete tasks resume from checkpoints. The scheduler rediscovers
   pending work and continues DFS.
9. **Lifecycle helpers** — `list_executions()` to show what completed,
   `cleanup_executions()` to remove checkpoint data.

## File layout

```
sdk/python/examples/dfss_pipeline/
├── PLAN_v2.md                 # This file
├── README.md                  # How to run, what to observe
├── main.py                    # Entry point: seed, run, stop/start, report
├── scheduler.py               # DFSS scheduler (~150 lines)
├── task_machine.py            # Single machine config (inline dict)
├── hooks.py                   # Simulated work: designed + random trees, failures
└── work_queue.py              # File-backed work queue (JSON) for stop/start
```

## The task machine

One machine config used for all tasks. Parameterized by input:

```yaml
# Equivalent YAML (implemented as inline dict in task_machine.py)
spec: flatmachine
spec_version: "1.1.1"
data:
  name: task-runner
  on_error: error_exit                 # machine-level default
  persistence:
    enabled: true
    backend: local
    resume:
      max_retries: 2
      backoffs: [0.5, 1.0]
      jitter: 0.2
  context:
    task_id: input.task_id
    root_id: input.root_id
    depth: input.depth
    resource_class: input.resource_class
    has_expensive_descendant: input.has_expensive_descendant
    # populated by hook
    children: []
    result: null
  states:
    start:
      type: initial
      transitions:
        - to: execute_task
    execute_task:
      action: run_task
      transitions:
        - to: done
    done:
      type: final
      output:
        task_id: "{{ context.task_id }}"
        root_id: "{{ context.root_id }}"
        depth: "{{ context.depth }}"
        children: "{{ context.children }}"
        result: "{{ context.result }}"
    error_exit:
      type: final
      output:
        task_id: "{{ context.task_id }}"
        root_id: "{{ context.root_id }}"
        error: "{{ context.last_error }}"
```

One machine, one action, one error handler. The hook does all the work.

## Hooks (hooks.py)

The hook handles two modes: designed trees (root-000, root-001) return
predetermined children; random trees return random children.

```python
# Designed tree definitions — keyed by task_id
DESIGNED_TREES = {
    # root-000: two simultaneous slow tasks at d=2
    "root-000/0": {
        "children": [
            {"suffix": "0", "resource_class": "fast"},
            {"suffix": "1", "resource_class": "fast"},
        ],
    },
    "root-000/0.0": {
        "children": [
            {"suffix": "0", "resource_class": "slow"},
            {"suffix": "1", "resource_class": "slow"},
        ],
    },
    "root-000/0.1": {
        "children": [
            {"suffix": "0", "resource_class": "fast"},
        ],
    },
    # root-000/0.0.0, root-000/0.0.1, root-000/0.1.0 → leaves (not in dict)

    # root-001: slow task gated behind 3 cheap predecessors
    "root-001/0": {
        "children": [
            {"suffix": "0", "resource_class": "fast",
             "has_expensive_descendant": True},
        ],
    },
    "root-001/0.0": {
        "children": [
            {"suffix": "0", "resource_class": "fast",
             "has_expensive_descendant": True},
        ],
    },
    "root-001/0.0.0": {
        "children": [
            {"suffix": "0", "resource_class": "slow"},
        ],
    },
    # root-001/0.0.0.0 → leaf (not in dict)
}


class TaskHooks(MachineHooks):
    """Simulate task execution.

    Designed roots (000, 001) follow DESIGNED_TREES for deterministic output.
    Random roots spawn 0-2 children with random resource classes.
    All tasks have a chance of transient failure (~15%).
    """

    def __init__(self, max_depth=3, fail_rate=0.15):
        self.max_depth = max_depth
        self.fail_rate = fail_rate

    def on_action(self, action_name, context):
        if action_name != "run_task":
            return context

        # Transient failure
        if random.random() < self.fail_rate:
            raise RuntimeError(f"transient failure in {context['task_id']}")

        task_id = context["task_id"]
        root_id = context["root_id"]
        depth = int(context.get("depth", 0))

        # Designed tree?
        if task_id in DESIGNED_TREES:
            spec = DESIGNED_TREES[task_id]
            children = []
            for c in spec["children"]:
                child_id = f"{task_id}.{c['suffix']}"
                children.append({
                    "task_id": child_id,
                    "root_id": root_id,
                    "depth": depth + 1,
                    "resource_class": c["resource_class"],
                    "has_expensive_descendant": c.get("has_expensive_descendant", False),
                })
            context["children"] = children
            context["result"] = f"interior-{task_id}"
            return context

        # Random tree
        if depth >= self.max_depth:
            context["result"] = f"leaf-{task_id}"
            context["children"] = []
        else:
            n_children = random.choices([0, 1, 2], weights=[0.2, 0.5, 0.3])[0]
            children = []
            for i in range(n_children):
                child_id = f"{task_id}.{i}"
                child_resource = random.choice(["fast", "slow"])
                children.append({
                    "task_id": child_id,
                    "root_id": root_id,
                    "depth": depth + 1,
                    "resource_class": child_resource,
                    "has_expensive_descendant": False,
                })
            context["children"] = children
            context["result"] = f"interior-{task_id}"

        return context
```

## File-backed work queue (work_queue.py)

A simple JSON file that persists the work queue across process restarts.
Not a production queue — just enough for the stop/start demo.

```python
class FileWorkQueue:
    """JSON-file-backed work queue for stop/start persistence."""

    def __init__(self, path="data/work_queue.json"):
        self.path = Path(path)
        self.items: list[dict] = []
        self.completed_roots: set[str] = set()
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text())
            self.items = data.get("items", [])
            self.completed_roots = set(data.get("completed_roots", []))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"items": self.items, "completed_roots": sorted(self.completed_roots)}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def push(self, item: dict): ...
    def claim(self, resource_class: str) -> Optional[dict]: ...
    def mark_done(self, task_id: str): ...
    def pending_count(self) -> int: ...
```

## Scheduler (scheduler.py)

### Core structures

```python
@dataclass
class RootState:
    root_id: str
    admitted: bool = False
    in_flight: int = 0
    max_depth_seen: int = 0
    pending: int = 0                # tasks still in queue for this root
    has_pending_expensive: bool = False  # any slow tasks queued for this root

    @property
    def is_done(self) -> bool:
        return self.in_flight == 0 and self.pending == 0

@dataclass
class ResourcePool:
    name: str
    capacity: int
    in_flight: int = 0
    gate_open: bool = True

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.in_flight) if self.gate_open else 0
```

### Candidate scoring

```python
def score(item: dict, root: RootState, is_active: bool) -> float:
    """Higher = scheduled first.

    Five factors:
    1. Active root continuation — keep working on admitted roots
    2. Depth — prefer deeper tasks (DFS)
    3. Proximity to done — prefer roots with fewer pending tasks
    4. Scarce resource — boost tasks that need slow resource (bottleneck)
    5. Predecessor hint — boost cheap tasks that gate expensive descendants
    """
    s = 0.0
    s += 100.0 if is_active else 0.0                         # 1. continuation
    s += 10.0 * item["depth"]                                 # 2. depth-first
    s -= 5.0 * root.pending                                   # 3. closer to done
    s += 20.0 if item["resource_class"] == "slow" else 0.0   # 4. scarce resource
    s += 30.0 if item.get("has_expensive_descendant") else 0.0  # 5. predecessor
    s += 15.0 if root.has_pending_expensive else 0.0          # 5b. root has bottleneck
    return s
```

The scoring captures:
- **root-000 scenario**: when both slow d=2 tasks are enqueued, they each get
  +20 (scarce resource) + +10×2 (depth). With 2 slow slots open, both are
  dispatched simultaneously.
- **root-001 scenario**: the cheap predecessor at d=0 gets +30 (has_expensive_descendant)
  + +15 (root has pending expensive). This outscores a random cheap task at d=0
  from another root (+0 + +0), so the scheduler drills through root-001's chain
  first.

### Pick next — DFS with gated saturation

```python
def pick_next(queue, roots, resources, max_active_roots) -> Optional[dict]:
    active_root_ids = {r.root_id for r in roots.values() if r.admitted and not r.is_done}

    # Build candidates: ready items whose resource gate is open with capacity
    candidates = []
    for item in queue.items:
        res = resources.get(item["resource_class"])
        if res and res.available > 0:
            candidates.append(item)

    if not candidates:
        return None

    # Partition: active root candidates vs new root candidates
    active_cands = [c for c in candidates if c["root_id"] in active_root_ids]
    new_cands = [c for c in candidates if c["root_id"] not in active_root_ids]

    # Prefer active roots. Admit new root only if:
    # - no active candidates exist, AND
    # - active set has room or all active roots are blocked
    if active_cands:
        pool = active_cands
    elif len(active_root_ids) < max_active_roots:
        pool = new_cands
    else:
        any_active_runnable = any(
            c for c in candidates if c["root_id"] in active_root_ids
        )
        if not any_active_runnable and new_cands:
            pool = new_cands
        else:
            return None

    best = max(pool, key=lambda c: score(c, roots[c["root_id"]],
               c["root_id"] in active_root_ids))
    return best
```

### Main loop

```python
async def run(queue, roots, resources, dispatch, max_workers, max_active_roots):
    active_tasks = set()

    while True:
        # Fill free slots
        while len(active_tasks) < max_workers:
            item = pick_next(queue, roots, resources, max_active_roots)
            if item is None:
                break
            queue.claim(item["task_id"])
            roots[item["root_id"]].admitted = True
            roots[item["root_id"]].in_flight += 1
            resources[item["resource_class"]].in_flight += 1

            task = asyncio.create_task(dispatch(item))
            task._item = item
            active_tasks.add(task)

        # All done?
        if not active_tasks:
            if queue.pending_count() == 0:
                break
            await asyncio.sleep(0.2)
            continue

        # Wait for any completion, then immediately loop to refill
        done, _ = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            active_tasks.discard(t)
            item = t._item
            roots[item["root_id"]].in_flight -= 1
            resources[item["resource_class"]].in_flight -= 1
            # dispatch callback already enqueued children + saved queue

        queue.save()  # persist after each batch of completions
```

## Updating root state on enqueue

When children are enqueued after a task completes, the root's
`has_pending_expensive` flag must be updated:

```python
def enqueue_children(children, queue, roots):
    for child in children:
        queue.push(child)
        root = roots[child["root_id"]]
        root.pending += 1
        if child["resource_class"] == "slow":
            root.has_pending_expensive = True

def refresh_expensive_flag(root_id, queue, roots):
    """Recompute after a slow task completes (it may have been the last one)."""
    root = roots[root_id]
    root.has_pending_expensive = any(
        item["resource_class"] == "slow"
        for item in queue.items
        if item["root_id"] == root_id
    )
```

## Gate toggling

A background task that simulates the `slow` resource going offline
periodically (like a rate-limited API):

```python
async def toggle_gate(resources, name="slow", interval=3.0):
    """Toggle a resource gate on/off to simulate intermittent availability."""
    while True:
        await asyncio.sleep(interval)
        res = resources[name]
        res.gate_open = not res.gate_open
        state = "OPEN" if res.gate_open else "CLOSED"
        print(f"  ⚡ {name} gate → {state}")
```

## Expected output

### Scenario A: Two slow slots fill simultaneously (root-000)

```
  ✓ root-000/0       (d=0 fast) → 2 children
  ✓ root-000/0.0     (d=1 fast) → 2 children [slow, slow]
  ✓ root-000/0.1     (d=1 fast) → 1 child
  ✓ root-000/0.0.0   (d=2 slow) ← slot 1 }  both slow slots
  ✓ root-000/0.0.1   (d=2 slow) ← slot 2 }  filled at once
  ✓ root-000/0.1.0   (d=2 fast) → leaf
  🏁 root-000 COMPLETE
```

### Scenario B: Drill through cheap predecessors to expensive task (root-001)

```
  ✓ root-001/0       (d=0 fast, has_expensive_descendant) → 1 child
  ✓ root-001/0.0     (d=1 fast, has_expensive_descendant) → 1 child
  ✓ root-001/0.0.0   (d=2 fast, has_expensive_descendant) → 1 child
  ✓ root-001/0.0.0.0 (d=3 slow) → leaf       ← bottleneck reached
  🏁 root-001 COMPLETE
```

Note: root-001's cheap tasks at d=0,1,2 are prioritized over random roots'
cheap tasks at the same depths because of the +30 predecessor hint and +15
root-has-expensive boost.

### Full run output

```
$ python main.py --roots 8

🌳 DFSS Task Tree — 8 roots, max_depth=3
  Resources: fast(4 slots), slow(2 slots, toggling)
  Max active roots: 3
  Designed: root-000 (simultaneous slow), root-001 (deep expensive)

  ✓ root-000/0       (d=0 fast) → 2 children
  ✓ root-001/0       (d=0 fast) → 1 child [has_expensive_descendant]
  ✓ root-002/0       (d=0 fast) → 1 child
  ✓ root-000/0.0     (d=1 fast) → 2 children [slow, slow]
  ✓ root-001/0.0     (d=1 fast) → 1 child [has_expensive_descendant]
  ✓ root-000/0.1     (d=1 fast) → 1 child
  ⚡ slow gate → OPEN
  ✓ root-000/0.0.0   (d=2 slow) → leaf       ← slow slot 1
  ✓ root-000/0.0.1   (d=2 slow) → leaf       ← slow slot 2
  ✓ root-001/0.0.0   (d=2 fast) → 1 child [has_expensive_descendant]
  ✓ root-000/0.1.0   (d=2 fast) → leaf
  🏁 root-000 COMPLETE (6 tasks)
  ✓ root-001/0.0.0.0 (d=3 slow) → leaf       ← bottleneck reached
  🏁 root-001 COMPLETE (4 tasks)
  ✓ root-003/0       (d=0 slow) → 2 children  ← new root admitted
  ⟳ root-002/0.0     retrying (persistence.resume, attempt 2)
  ✓ root-002/0.0     (d=1 fast) → leaf
  🏁 root-002 COMPLETE
  ...
  ⚡ slow gate → CLOSED
  ...waiting for gate...
  ⚡ slow gate → OPEN
  ...
  ^C

  Interrupted. 5/8 roots complete. Queue saved to data/work_queue.json.
  Checkpoints in .checkpoints/. Resume with: python main.py --resume
```

### Resume run

```
$ python main.py --resume

🌳 DFSS Task Tree — resuming from data/work_queue.json
  Loaded: 7 pending tasks, 5/8 roots complete
  Checking checkpoints for incomplete machines...
  Found 1 resumable execution

  ⟳ root-005/0.1 resumed from checkpoint (d=1 fast)
  ✓ root-005/0.1 → 1 child
  ✓ root-005/0.1.0 (d=2 slow) → leaf
  🏁 root-005 COMPLETE
  ✓ root-006/0 (d=0 fast) → leaf
  🏁 root-006 COMPLETE
  ✓ root-007/0 (d=0 slow) → 2 children
  ✓ root-007/0.0 (d=1 fast) → leaf
  ✓ root-007/0.1 (d=1 fast) → leaf
  🏁 root-007 COMPLETE

  ✅ All 8 roots complete.
  Total tasks: 31 (3 retries via persistence.resume, 1 resumed from checkpoint)

  Cleaning up checkpoints...
  Removed 31 execution checkpoints.
```

## Stop/start behavior

### First run

User runs `python main.py --roots 8`, watches DFS + saturation in action,
hits Ctrl+C mid-run.

**What persists:**
- `data/work_queue.json` — remaining work items + which roots are done
- `.checkpoints/` — file persistence checkpoints for all machine runs

### Second run (resume)

User runs `python main.py --resume`.

**What happens:**
1. Queue loaded from `data/work_queue.json` — knows what work remains
2. Root states rebuilt from queue (which roots are done, which have pending work)
3. Checkpoints scanned — any execution that was mid-flight when killed is
   detected and its work item requeued
4. Scheduler resumes DFS from where it left off
5. `persistence.resume` inside each machine handles any partial checkpoints

## Entry point (main.py)

```python
async def main():
    args = parse_args()  # --roots N, --resume, --max-depth, --max-workers

    queue = FileWorkQueue("data/work_queue.json")
    backend = LocalFileBackend()

    if args.resume:
        print(f"Resuming: {queue.pending_count()} pending tasks")
        # Scan for in-flight tasks that were killed mid-execution
        requeue_interrupted(queue, backend)
    else:
        # Seed roots: designed roots first, then random
        seed_designed_roots(queue)
        for i in range(2, args.roots):
            root_id = f"root-{i:03d}"
            queue.push({
                "task_id": f"{root_id}/0",
                "root_id": root_id,
                "depth": 0,
                "resource_class": random.choice(["fast", "slow"]),
                "has_expensive_descendant": False,
            })
        queue.save()

    # Build root state from queue
    roots = build_root_states(queue)

    resources = {
        "fast": ResourcePool("fast", capacity=4),
        "slow": ResourcePool("slow", capacity=2),
    }

    hooks = TaskHooks(max_depth=args.max_depth, fail_rate=0.15)
    stats = {"dispatched": 0, "retries": 0, "resumed": 0}

    async def dispatch(item):
        stats["dispatched"] += 1
        machine = FlatMachine(
            config_dict=task_config(),
            hooks=hooks,
            persistence=backend,
        )

        try:
            result = await machine.execute(input=item)
        except Exception as exc:
            # persistence.resume exhausted — terminal failure
            print(f"  ✗ {item['task_id']} terminal: {exc}")
            roots[item["root_id"]].pending -= 1
            return

        if result.get("error"):
            # Machine-level on_error caught it — requeue
            item["attempts"] = item.get("attempts", 0) + 1
            if item["attempts"] < 3:
                stats["retries"] += 1
                queue.push(item)
            else:
                print(f"  ✗ {item['task_id']} terminal failure after retries")
                roots[item["root_id"]].pending -= 1
        else:
            # Enqueue children
            children = json.loads(result.get("children", "[]"))
            enqueue_children(children, queue, roots)
            roots[item["root_id"]].pending -= 1
            refresh_expensive_flag(item["root_id"], queue, roots)

            depth_str = f"d={item['depth']}"
            res_str = item["resource_class"]
            n = len(children)
            suffix = f"→ {n} children" if n else "→ leaf"
            hint = " [has_expensive_descendant]" if item.get("has_expensive_descendant") else ""
            print(f"  ✓ {item['task_id']:20s} ({depth_str} {res_str}{hint}) {suffix}")

            if roots[item["root_id"]].is_done:
                queue.completed_roots.add(item["root_id"])
                print(f"  🏁 {item['root_id']} COMPLETE")

    # Start gate toggler
    toggler = asyncio.create_task(toggle_gate(resources))

    try:
        await run(queue, roots, resources, dispatch,
                  max_workers=args.max_workers, max_active_roots=3)
    except KeyboardInterrupt:
        pass
    finally:
        toggler.cancel()
        queue.save()

    # Post-run: lifecycle helpers
    exec_ids = [d.name for d in Path(".checkpoints").iterdir() if d.is_dir()]
    snaps = await list_executions(backend, exec_ids)
    completed = sum(1 for s in snaps if s.event == "machine_end")
    print(f"\nExecutions: {len(snaps)} total, {completed} completed")
    print(f"Stats: {stats['dispatched']} dispatched, {stats['retries']} retries")
    await cleanup_executions(backend, exec_ids)
    print("Checkpoints cleaned up.")


def seed_designed_roots(queue):
    """Seed root-000 and root-001 with known tree entry points."""
    queue.push({
        "task_id": "root-000/0",
        "root_id": "root-000",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": False,
    })
    queue.push({
        "task_id": "root-001/0",
        "root_id": "root-001",
        "depth": 0,
        "resource_class": "fast",
        "has_expensive_descendant": True,  # we know it leads to slow at d=3
    })
```

## Line count estimate

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | ~100 | Seed (designed + random), dispatch, resume, report |
| `scheduler.py` | ~150 | RootState, ResourcePool, score, pick_next, run loop |
| `task_machine.py` | ~50 | Single machine config dict |
| `hooks.py` | ~80 | Designed trees + random trees, random failures |
| `work_queue.py` | ~60 | File-backed JSON queue for stop/start |
| `README.md` | ~80 | How to run, what to observe, stop/start instructions |
| **Total** | **~520** |

## Key observations for the reader

1. **One machine config** for all tasks. No per-task-type machines. The hook
   action + input parameterize behavior.
2. **Zero retry logic in the scheduler.** Machine-level `on_error` catches
   application errors → routed to `error_exit` final state. `persistence.resume`
   catches infra errors → auto-retries from checkpoint. The scheduler only sees
   terminal outcomes.
3. **DFS is visible in output.** root-000's d=2 slow tasks complete before
   root-003 even starts. root-001 drills straight down to its d=3 slow task.
4. **Saturation is visible.** When slow gate opens, both slots fill immediately.
   root-000's two slow tasks at d=2 run simultaneously.
5. **Expensive-task prioritization is visible.** root-001's cheap predecessors
   are scheduled before random roots' cheap tasks because of the
   `has_expensive_descendant` boost.
6. **Stop/start is real.** File persistence + JSON work queue. Kill the process
   at any point, restart, and it picks up where it left off. Lifecycle helpers
   discover and report on checkpoint state.
7. **The scheduler is ~150 lines.** Scoring is ~8 lines. The loop is generic.
   All domain logic is in the dispatch callback and hooks.
