from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional


Candidate = Dict[str, Any]


@dataclass
class RootState:
    root_id: str
    admitted: bool = False
    in_flight: int = 0
    pending: int = 0
    completed: int = 0
    terminal_failures: int = 0
    has_pending_expensive: bool = False

    @property
    def is_done(self) -> bool:
        return self.pending <= 0 and self.in_flight <= 0


@dataclass
class ResourcePool:
    name: str
    capacity: int
    in_flight: int = 0
    gate_open: bool = True

    @property
    def available(self) -> int:
        if not self.gate_open:
            return 0
        return max(0, self.capacity - self.in_flight)


def add_candidate(candidates: List[Candidate], item: Candidate) -> None:
    work_id = item.get("work_id")
    if work_id and any(c.get("work_id") == work_id for c in candidates):
        return
    candidates.append(item)


def remove_candidate(candidates: List[Candidate], work_id: str) -> Optional[Candidate]:
    for idx, item in enumerate(candidates):
        if item.get("work_id") == work_id:
            return candidates.pop(idx)
    return None


def refresh_expensive_pending_flag(
    root: RootState,
    candidates: Iterable[Candidate],
    in_flight_items: Optional[Iterable[Candidate]] = None,
) -> None:
    expensive_pending = any(
        c.get("root_id") == root.root_id and c.get("resource_class") == "slow"
        for c in candidates
    )
    if not expensive_pending and in_flight_items:
        expensive_pending = any(
            c.get("root_id") == root.root_id and c.get("resource_class") == "slow"
            for c in in_flight_items
        )
    root.has_pending_expensive = expensive_pending


def recompute_root_metrics(
    roots: Dict[str, RootState],
    candidates: Iterable[Candidate],
    in_flight_items: Optional[Iterable[Candidate]] = None,
) -> None:
    counts: Dict[str, int] = {}
    for c in candidates:
        rid = c.get("root_id")
        if not rid:
            continue
        counts[rid] = counts.get(rid, 0) + 1

    for rid, root in roots.items():
        root.pending = counts.get(rid, 0) + max(0, root.in_flight)
        refresh_expensive_pending_flag(root, candidates, in_flight_items)


def score(item: Candidate, root: RootState, is_active: bool) -> float:
    depth = float(item.get("depth", 0))
    pending = float(max(root.pending, 0))

    s = 0.0
    s += 300.0 if is_active else 0.0                     # keep admitted roots saturated
    s += depth * 18.0                                     # prefer deeper work (DFS)
    s += max(0.0, 60.0 - (pending * 6.0))                # prefer roots near completion
    s += 120.0 if item.get("resource_class") == "slow" else 0.0

    if item.get("has_expensive_descendant"):
        s += 80.0                                         # cheap predecessor unlocks expensive work

    distance = item.get("distance_to_nearest_slow_descendant")
    if distance is not None:
        try:
            d = float(distance)
            if d < 10_000:
                s += max(0.0, 36.0 - (6.0 * d))
        except (TypeError, ValueError):
            pass

    if root.has_pending_expensive:
        s += 20.0

    return s


def pick_next(
    candidates: List[Candidate],
    roots: Dict[str, RootState],
    resources: Dict[str, ResourcePool],
    max_active_roots: int,
) -> Optional[Candidate]:
    active_root_ids = {
        r.root_id for r in roots.values() if r.admitted and not r.is_done
    }

    runnable: List[Candidate] = []
    for item in candidates:
        pool = resources.get(item.get("resource_class"))
        if pool is None:
            continue
        if pool.available <= 0:
            continue
        if item.get("root_id") not in roots:
            continue
        runnable.append(item)

    if not runnable:
        return None

    active = [c for c in runnable if c.get("root_id") in active_root_ids]
    inactive = [c for c in runnable if c.get("root_id") not in active_root_ids]

    if active:
        pool = active
    elif len(active_root_ids) < max_active_roots:
        pool = inactive
    else:
        return None

    return max(
        pool,
        key=lambda c: (
            score(c, roots[c["root_id"]], c.get("root_id") in active_root_ids),
            str(c.get("task_id", "")),
        ),
    )


async def run(
    candidates: List[Candidate],
    roots: Dict[str, RootState],
    resources: Dict[str, ResourcePool],
    dispatch: Callable[[Candidate], Awaitable[None]],
    max_workers: int,
    max_active_roots: int,
    idle_poll: float = 0.05,
    stop_event: Optional[asyncio.Event] = None,
    on_task_done: Optional[Callable[[], None]] = None,
) -> None:
    active_tasks: set[asyncio.Task] = set()

    while True:
        stopping = bool(stop_event and stop_event.is_set())

        while not stopping and len(active_tasks) < max_workers:
            item = pick_next(candidates, roots, resources, max_active_roots)
            if item is None:
                break

            removed = remove_candidate(candidates, str(item.get("work_id", "")))
            if removed is None:
                # Candidate already removed by another path.
                continue

            root = roots[item["root_id"]]
            root.admitted = True
            root.in_flight += 1

            resource_name = str(item["resource_class"])
            resources[resource_name].in_flight += 1

            task = asyncio.create_task(dispatch(item))
            setattr(task, "_dfss_item", item)
            active_tasks.add(task)

        if not active_tasks:
            if not candidates or stopping:
                return
            await asyncio.sleep(idle_poll)
            continue

        done, _ = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            active_tasks.discard(task)
            item = getattr(task, "_dfss_item", None)
            if item is None:
                continue

            root = roots[item["root_id"]]
            root.in_flight = max(0, root.in_flight - 1)

            resource_name = str(item["resource_class"])
            resources[resource_name].in_flight = max(0, resources[resource_name].in_flight - 1)

            try:
                task.result()
            except Exception:
                # Dispatch handles item-level errors and retries; suppress task noise.
                pass

            if on_task_done is not None:
                on_task_done()
