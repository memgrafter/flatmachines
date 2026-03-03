"""
Hooks for DFSS Deep Sleep.

Two roles:
  - Scheduler actions: seed_work, hydrate_candidates, pick_batch, claim_batch,
    settle_results, check_done, release_stale, report_and_cleanup
  - Task actions: run_task, signal_ready

Scheduling/scoring logic is intentionally kept isomorphic with
examples/dfss_pipeline/scheduler.py.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from flatmachines import MachineHooks


NO_SLOW_DISTANCE = 10_000
WORKER_ID = "scheduler"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _candidate_from_row(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(row["data"])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "task_id" not in data or "root_id" not in data:
        return None
    return {
        "work_id": row["item_id"],
        "task_id": data["task_id"],
        "root_id": data["root_id"],
        "depth": int(data.get("depth", 0)),
        "resource_class": str(data.get("resource_class", "fast")),
        "has_expensive_descendant": bool(data.get("has_expensive_descendant", False)),
        "distance_to_nearest_slow_descendant": int(
            data.get("distance_to_nearest_slow_descendant", NO_SLOW_DISTANCE)
        ),
        "attempts": int(row["attempts"]),
    }


def _load_pending_candidates(
    db_path: str, pool_name: str = "tasks"
) -> List[Dict[str, Any]]:
    with _sqlite_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT item_id, data, attempts
            FROM work_pool
            WHERE pool_name = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (pool_name,),
        ).fetchall()
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        item = _candidate_from_row(row)
        if item is not None:
            candidates.append(item)
    return candidates


def _claim_by_id(
    db_path: str,
    work_id: str,
    *,
    worker_id: str = WORKER_ID,
    pool_name: str = "tasks",
) -> Optional[Dict[str, Any]]:
    with _sqlite_conn(db_path) as conn:
        updated = conn.execute(
            """
            UPDATE work_pool
            SET status = 'claimed', claimed_by = ?, claimed_at = ?, attempts = attempts + 1
            WHERE pool_name = ? AND item_id = ? AND status = 'pending'
            """,
            (worker_id, _now_iso(), pool_name, work_id),
        )
        if updated.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT item_id, data, attempts FROM work_pool WHERE item_id = ?",
            (work_id,),
        ).fetchone()
    if row is None:
        return None
    return _candidate_from_row(row)


def _unfinished_work_count(db_path: str, pool_name: str = "tasks") -> int:
    with _sqlite_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM work_pool
            WHERE pool_name = ? AND status IN ('pending', 'claimed')
            """,
            (pool_name,),
        ).fetchone()
    return int(row["c"] if row else 0)


def _root_terminal_failures(
    db_path: str, pool_name: str = "tasks"
) -> Dict[str, int]:
    with _sqlite_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT data
            FROM work_pool
            WHERE pool_name = ? AND status = 'poisoned'
            """,
            (pool_name,),
        ).fetchall()
    out: Dict[str, int] = {}
    for row in rows:
        try:
            data = json.loads(row["data"])
            root_id = str(data.get("root_id"))
        except Exception:
            continue
        if root_id:
            out[root_id] = out.get(root_id, 0) + 1
    return out


def _initial_root_task(
    root_id: str, max_depth: int, rng: random.Random
) -> Dict[str, Any]:
    if root_id == "root-000":
        return {
            "task_id": "root-000/0",
            "root_id": "root-000",
            "depth": 0,
            "resource_class": "fast",
            "has_expensive_descendant": True,
            "distance_to_nearest_slow_descendant": 2,
        }
    if root_id == "root-001":
        return {
            "task_id": "root-001/0",
            "root_id": "root-001",
            "depth": 0,
            "resource_class": "fast",
            "has_expensive_descendant": True,
            "distance_to_nearest_slow_descendant": 3,
        }
    resource_class = rng.choice(["fast", "slow"])
    hint = resource_class == "fast" and (rng.random() < 0.35)
    distance = (
        0
        if resource_class == "slow"
        else (rng.randint(1, max(1, max_depth)) if hint else NO_SLOW_DISTANCE)
    )
    return {
        "task_id": f"{root_id}/0",
        "root_id": root_id,
        "depth": 0,
        "resource_class": resource_class,
        "has_expensive_descendant": bool(hint),
        "distance_to_nearest_slow_descendant": int(distance),
    }


# ── Meta table helpers ─────────────────────────────────────

def _ensure_meta_table(db_path: str) -> None:
    with _sqlite_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dfss_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )


def _save_meta(db_path: str, values: Dict[str, Any]) -> None:
    _ensure_meta_table(db_path)
    with _sqlite_conn(db_path) as conn:
        conn.execute("DELETE FROM dfss_meta")
        for key, value in values.items():
            conn.execute(
                "INSERT INTO dfss_meta(key, value) VALUES(?, ?)",
                (str(key), json.dumps(value)),
            )


def _load_meta(db_path: str) -> Dict[str, Any]:
    _ensure_meta_table(db_path)
    with _sqlite_conn(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM dfss_meta").fetchall()
    out: Dict[str, Any] = {}
    for row in rows:
        try:
            out[row["key"]] = json.loads(row["value"])
        except Exception:
            out[row["key"]] = row["value"]
    return out


# ═══════════════════════════════════════════════════════════
# DeepSleepHooks
# ═══════════════════════════════════════════════════════════


class DeepSleepHooks(MachineHooks):

    def __init__(
        self,
        max_depth: int = 3,
        fail_rate: float = 0.0,
        seed: int = 7,
        max_attempts: int = 3,
        gate_interval: float = 0.8,
        # Injected at runtime
        work_backend=None,
        signal_backend=None,
        checkpoint_backend=None,
        pool_name: str = "tasks",
    ):
        self.max_depth = max_depth
        self.fail_rate = fail_rate
        self.max_attempts = max_attempts
        self.gate_interval = gate_interval
        self._rng = random.Random(seed)
        self._seed_rng = random.Random(seed)
        self.work_backend = work_backend
        self.signal_backend = signal_backend
        self.checkpoint_backend = checkpoint_backend
        self.pool_name = pool_name
        self._pool = None

    @property
    def pool(self):
        if self._pool is None and self.work_backend is not None:
            self._pool = self.work_backend.pool(self.pool_name)
        return self._pool

    @property
    def db_path(self) -> Optional[str]:
        p = self.pool
        if p is not None and hasattr(p, "db_path"):
            return str(p.db_path)
        return None

    # ── Action dispatch ────────────────────────────────────────
    # HookAction in flatmachines awaits coroutines, so async actions work.

    async def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        dispatch = {
            # Scheduler actions (async — touch durable backends)
            "seed_work": self._seed_work,
            "hydrate_candidates": self._hydrate_candidates,
            "claim_batch": self._claim_batch,
            "settle_results": self._settle_results,
            "check_done": self._check_done,
            "release_stale": self._release_stale,
            "report_and_cleanup": self._report_and_cleanup,
            "signal_ready": self._signal_ready,
            # Pure-logic actions (sync)
            "pick_batch": self._pick_batch,
            "run_task": self._run_task,
        }
        handler = dispatch.get(action_name)
        if handler is None:
            return context
        result = handler(context)
        # Await if coroutine
        if hasattr(result, "__await__"):
            return await result
        return result

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalize_root(cls, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "admitted": bool(state.get("admitted", False)),
            "in_flight": max(0, cls._to_int(state.get("in_flight", 0))),
            "pending": max(0, cls._to_int(state.get("pending", state.get("_pending", 0)))),
            "completed": max(0, cls._to_int(state.get("completed", 0))),
            "terminal_failures": max(0, cls._to_int(state.get("terminal_failures", 0))),
            "has_pending_expensive": bool(state.get("has_pending_expensive", False)),
        }

    @classmethod
    def _normalize_roots(cls, roots: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(roots, dict):
            return {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for rid, state in roots.items():
            if not isinstance(state, dict):
                state = {}
            normalized[str(rid)] = cls._normalize_root(state)
        return normalized

    @staticmethod
    def _root_done(root: Dict[str, Any]) -> bool:
        return int(root.get("pending", 0)) <= 0 and int(root.get("in_flight", 0)) <= 0

    @staticmethod
    def _score(item: Dict[str, Any], root: Dict[str, Any], is_active: bool) -> float:
        """Isomorphic with dfss_pipeline.scheduler.score."""
        depth = float(item.get("depth", 0))
        pending = float(max(int(root.get("pending", 0)), 0))

        s = 0.0
        s += 300.0 if is_active else 0.0
        s += depth * 18.0
        s += max(0.0, 60.0 - (pending * 6.0))
        s += 120.0 if item.get("resource_class") == "slow" else 0.0

        if item.get("has_expensive_descendant"):
            s += 80.0

        distance = item.get("distance_to_nearest_slow_descendant")
        if distance is not None:
            try:
                d = float(distance)
                if d < NO_SLOW_DISTANCE:
                    s += max(0.0, 36.0 - (6.0 * d))
            except (TypeError, ValueError):
                pass

        if root.get("has_pending_expensive"):
            s += 20.0

        return s

    @staticmethod
    def _refresh_expensive_pending_flag(
        root_id: str,
        root: Dict[str, Any],
        candidates: Iterable[Dict[str, Any]],
        in_flight_items: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> None:
        expensive_pending = any(
            c.get("root_id") == root_id and c.get("resource_class") == "slow"
            for c in candidates
        )
        if not expensive_pending and in_flight_items:
            expensive_pending = any(
                c.get("root_id") == root_id and c.get("resource_class") == "slow"
                for c in in_flight_items
            )
        root["has_pending_expensive"] = expensive_pending

    def _recompute_root_metrics(
        self,
        roots: Dict[str, Dict[str, Any]],
        candidates: Iterable[Dict[str, Any]],
        in_flight_items: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> None:
        counts: Dict[str, int] = {}
        for c in candidates:
            rid = c.get("root_id")
            if not rid:
                continue
            rid_s = str(rid)
            counts[rid_s] = counts.get(rid_s, 0) + 1
        for rid, root in roots.items():
            root["pending"] = counts.get(rid, 0) + max(0, int(root.get("in_flight", 0)))
            self._refresh_expensive_pending_flag(rid, root, candidates, in_flight_items)

    def _pick_one(
        self,
        candidates: List[Dict[str, Any]],
        roots: Dict[str, Dict[str, Any]],
        resources: Dict[str, Dict[str, Any]],
        max_active_roots: int,
    ) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None

        active_root_ids = {
            rid for rid, r in roots.items()
            if r.get("admitted") and not self._root_done(r)
        }

        # Filter by resource availability
        runnable: List[Dict[str, Any]] = []
        for c in candidates:
            rc = str(c.get("resource_class", "fast"))
            res = resources.get(rc)
            if res is None:
                continue
            if not res.get("gate_open", True):
                continue
            cap = int(res.get("capacity", 4))
            inflight = int(res.get("in_flight", 0))
            if (cap - inflight) <= 0:
                continue
            runnable.append(c)

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
                self._score(
                    c, roots[str(c["root_id"])], c.get("root_id") in active_root_ids
                ),
                str(c.get("task_id", "")),
            ),
        )

    def _maybe_toggle_gate(self, context: Dict[str, Any]) -> None:
        """Toggle slow gate based on elapsed time since last toggle."""
        resources = context.get("resources")
        if not resources or not isinstance(resources, dict):
            return
        slow = resources.get("slow")
        if not slow or not isinstance(slow, dict):
            return

        now = time.monotonic()
        last_toggle = context.get("_last_gate_toggle")
        if last_toggle is None:
            context["_last_gate_toggle"] = now
            return

        elapsed = now - float(last_toggle)
        if elapsed >= self.gate_interval:
            slow["gate_open"] = not slow.get("gate_open", True)
            state = "OPEN" if slow["gate_open"] else "CLOSED"
            print(f"  ⚡ slow gate -> {state}", flush=True)
            context["_last_gate_toggle"] = now

    # ══════════════════════════════════════════════════════════
    # Scheduler actions
    # ══════════════════════════════════════════════════════════

    async def _seed_work(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Push initial root tasks into the durable work pool."""
        n_roots = self._to_int(context.get("n_roots", 8), 8)
        max_depth = self._to_int(context.get("max_depth", self.max_depth), self.max_depth)

        root_ids = [f"root-{i:03d}" for i in range(n_roots)]

        pool = self.pool
        if pool is not None:
            for root_id in root_ids:
                item = _initial_root_task(root_id, max_depth, self._seed_rng)
                await pool.push(item, options={"max_retries": self.max_attempts})

        # Save meta
        db = self.db_path
        if db:
            _save_meta(db, {
                "root_ids": root_ids,
                "n_roots": n_roots,
                "max_depth": max_depth,
                "max_attempts": self.max_attempts,
            })

        context["root_ids"] = root_ids
        context["roots"] = {rid: self._normalize_root({}) for rid in root_ids}

        # Initialize resources
        context["resources"] = {
            "fast": {"capacity": 4, "in_flight": 0, "gate_open": True},
            "slow": {"capacity": 2, "in_flight": 0, "gate_open": True},
        }
        context["_last_gate_toggle"] = time.monotonic()

        print(
            f"Seeded roots={n_roots}, max_depth={max_depth}, max_attempts={self.max_attempts}",
            flush=True,
        )
        return context

    async def _hydrate_candidates(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Load pending work items from SQLite into context._candidates."""
        db = self.db_path
        if db is None:
            return context

        candidates = _load_pending_candidates(db, self.pool_name)
        context["_candidates"] = candidates

        # Rebuild root state from DB if roots empty
        roots = self._normalize_roots(context.get("roots", {}))
        root_ids = context.get("root_ids", [])
        if not roots and root_ids:
            roots = {rid: self._normalize_root({}) for rid in root_ids}

        # Ensure all candidate root_ids have entries
        for c in candidates:
            rid = str(c.get("root_id", ""))
            if rid and rid not in roots:
                roots[rid] = self._normalize_root({})

        # Restore terminal failure counts from DB
        terminal = _root_terminal_failures(db, self.pool_name)
        for rid, count in terminal.items():
            if rid in roots:
                roots[rid]["terminal_failures"] = count

        self._recompute_root_metrics(roots, candidates)
        context["roots"] = roots

        return context

    def _pick_batch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Score candidates, select up to batch_size. Pure logic — no I/O."""
        raw_candidates = context.get("_candidates") or []
        candidates = [c for c in raw_candidates if isinstance(c, dict)]

        batch_size = max(0, self._to_int(context.get("batch_size", 4), 4))
        max_active = max(1, self._to_int(context.get("max_active_roots", 3), 3))
        roots = self._normalize_roots(context.get("roots", {}))

        # Initialize resources if not present
        resources = context.get("resources")
        if not resources or not isinstance(resources, dict):
            resources = {
                "fast": {"capacity": 4, "in_flight": 0, "gate_open": True},
                "slow": {"capacity": 2, "in_flight": 0, "gate_open": True},
            }
            context["resources"] = resources

        # Toggle gate if timer elapsed
        self._maybe_toggle_gate(context)

        for c in candidates:
            rid = str(c.get("root_id", ""))
            if rid and rid not in roots:
                roots[rid] = self._normalize_root({})

        self._recompute_root_metrics(roots, candidates)

        available = list(candidates)
        batch: List[Dict[str, Any]] = []

        for _ in range(batch_size):
            picked = self._pick_one(available, roots, resources, max_active_roots=max_active)
            if picked is None:
                break
            available.remove(picked)
            rid = str(picked["root_id"])
            root = roots[rid]
            root["admitted"] = True
            root["in_flight"] = int(root.get("in_flight", 0)) + 1

            # Track resource in-flight
            rc = str(picked.get("resource_class", "fast"))
            if rc in resources:
                resources[rc]["in_flight"] = int(resources[rc].get("in_flight", 0)) + 1

            batch.append(picked)
            self._recompute_root_metrics(roots, available, in_flight_items=batch)

        context["batch"] = batch
        context["_candidates"] = available
        context["roots"] = roots
        context["resources"] = resources

        if not roots:
            context["all_done"] = not available and not batch
        else:
            context["all_done"] = (
                not available
                and not batch
                and all(self._root_done(r) for r in roots.values())
            )

        return context

    async def _claim_batch(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically claim each picked item in the durable work pool."""
        batch = context.get("batch") or []
        db = self.db_path
        claimed: List[Dict[str, Any]] = []

        for item in batch:
            work_id = item.get("work_id")
            if not work_id or db is None:
                # No durable pool — pass through (e.g. unit tests)
                claimed.append(item)
                continue

            result = _claim_by_id(db, work_id, pool_name=self.pool_name)
            if result is not None:
                claimed.append(result)
            else:
                # Lost race — release the resource slot we reserved in pick
                rc = str(item.get("resource_class", "fast"))
                resources = context.get("resources", {})
                if rc in resources:
                    resources[rc]["in_flight"] = max(
                        0, int(resources[rc].get("in_flight", 0)) - 1
                    )

        context["claimed_batch"] = claimed
        return context

    async def _settle_results(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process batch results: complete/fail in pool, enqueue children.

        The foreach dispatch returns results indexed by position, matching
        the claimed_batch order. We correlate results with claimed items
        to recover work_id, resource_class, attempts, etc.
        """
        raw_results = context.get("batch_results", [])
        roots = self._normalize_roots(context.get("roots", {}))
        resources = context.get("resources", {})
        claimed_batch = context.get("claimed_batch") or []

        # Build ordered list of results, correlating with claimed_batch by index
        if isinstance(raw_results, dict):
            if claimed_batch:
                # foreach returns {0: result, 1: result, ...}
                ordered = [raw_results.get(i) for i in range(len(claimed_batch))]
            else:
                # Fallback: use dict values in key order
                ordered = [raw_results[k] for k in sorted(raw_results.keys())]
        elif isinstance(raw_results, list):
            ordered = list(raw_results)
        else:
            ordered = []

        # Merge claimed metadata into results
        items: List[Dict[str, Any]] = []
        for idx, result in enumerate(ordered):
            if not isinstance(result, dict):
                continue
            # Enrich with claimed_batch metadata (work_id, attempts, resource_class)
            if idx < len(claimed_batch):
                claimed = claimed_batch[idx]
                if isinstance(claimed, dict):
                    result.setdefault("work_id", claimed.get("work_id"))
                    result.setdefault("attempts", claimed.get("attempts", 0))
                    result.setdefault("resource_class", claimed.get("resource_class", "fast"))
            items.append(result)

        pool = self.pool
        announced = context.get("_announced_complete")
        if not isinstance(announced, set):
            if isinstance(announced, (list, tuple)):
                announced = set(announced)
            else:
                announced = set()

        new_children: List[Dict[str, Any]] = []

        for result in items:
            rid = str(result.get("root_id", ""))
            if rid and rid not in roots:
                roots[rid] = self._normalize_root({})
            root = roots.get(rid, {})

            # Release resource slot
            rc = str(result.get("resource_class", "fast"))
            if rc in resources:
                resources[rc]["in_flight"] = max(
                    0, int(resources[rc].get("in_flight", 0)) - 1
                )

            # Release in-flight on root
            root["in_flight"] = max(0, int(root.get("in_flight", 0)) - 1)

            work_id = result.get("work_id")
            # foreach wraps child errors as {"_error": ..., "_error_type": ...}
            error = result.get("error") or result.get("_error")

            if error:
                if pool is not None and work_id:
                    try:
                        await pool.fail(work_id, str(error))
                    except KeyError:
                        pass

                attempts = self._to_int(result.get("attempts", 0))
                if attempts >= self.max_attempts:
                    root["terminal_failures"] = int(root.get("terminal_failures", 0)) + 1
                    print(
                        f"  ✗ {result.get('task_id', '?'):24s} terminal after {attempts} attempts: {error}",
                        flush=True,
                    )
                else:
                    print(
                        f"  ⟳ {result.get('task_id', '?'):24s} retry {attempts}/{self.max_attempts}",
                        flush=True,
                    )
            else:
                if pool is not None and work_id:
                    try:
                        await pool.complete(work_id, result)
                    except KeyError:
                        pass

                root["completed"] = int(root.get("completed", 0)) + 1

                children = result.get("children", [])
                if isinstance(children, list):
                    for child in children:
                        if not isinstance(child, dict):
                            continue
                        if pool is not None:
                            await pool.push(
                                child, options={"max_retries": self.max_attempts}
                            )
                        new_children.append(child)

                n_children = len(result.get("children", []))
                suffix = f"→ {n_children} children" if n_children else "→ leaf"
                depth = self._to_int(result.get("depth", 0))
                print(
                    f"  ✓ {result.get('task_id', '?'):24s} (d={depth} {rc}) {suffix}",
                    flush=True,
                )

        # Report root completions
        for rid, root in roots.items():
            if self._root_done(root) and root.get("admitted") and rid not in announced:
                announced.add(rid)
                state = (
                    "COMPLETE"
                    if int(root.get("terminal_failures", 0)) == 0
                    else "COMPLETE_WITH_TERMINAL_FAILURES"
                )
                print(f"  🏁 {rid} {state}", flush=True)

        context["roots"] = roots
        context["resources"] = resources
        context["_new_children"] = new_children
        context["batch"] = []
        context["claimed_batch"] = []
        context["batch_results"] = []
        context["_announced_complete"] = list(announced)  # JSON-serializable for checkpoint

        return context

    async def _check_done(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Check if all work is complete using durable pool state."""
        db = self.db_path
        if db is not None:
            remaining = _unfinished_work_count(db, self.pool_name)
            context["all_done"] = remaining == 0
        else:
            candidates = context.get("_candidates", [])
            roots = self._normalize_roots(context.get("roots", {}))
            context["all_done"] = (
                not candidates
                and all(self._root_done(r) for r in roots.values())
            ) if roots else not candidates

        return context

    async def _release_stale(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Release stale claims from a previous interrupted run."""
        pool = self.pool
        if pool is not None:
            released = await pool.release_by_worker(WORKER_ID)
            print(f"Released {released} stale claims", flush=True)

        db = self.db_path
        if db:
            meta = _load_meta(db)
            root_ids = meta.get("root_ids", [])
            context["root_ids"] = root_ids
            context["roots"] = {
                rid: self._normalize_root({}) for rid in root_ids
            }

            if "resources" not in context or not context.get("resources"):
                context["resources"] = {
                    "fast": {"capacity": 4, "in_flight": 0, "gate_open": True},
                    "slow": {"capacity": 2, "in_flight": 0, "gate_open": True},
                }
                context["_last_gate_toggle"] = time.monotonic()

        return context

    async def _report_and_cleanup(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Print summary and optionally clean up completed checkpoints."""
        db = self.db_path
        remaining = 0
        if db is not None:
            remaining = _unfinished_work_count(db, self.pool_name)

        if remaining == 0:
            print("✅ All work complete.", flush=True)
        else:
            print(
                f"⚠ Run paused with {remaining} unfinished tasks. Resume with --resume",
                flush=True,
            )

        cb = self.checkpoint_backend
        if cb is not None:
            all_execs = await cb.list_execution_ids()
            completed = await cb.list_execution_ids(event="machine_end")
            print(
                f"Checkpoint summary: total={len(all_execs)}, "
                f"completed={len(completed)}, "
                f"incomplete={len(set(all_execs) - set(completed))}",
                flush=True,
            )

            cleanup = context.get("cleanup", False)
            if cleanup:
                for eid in completed:
                    await cb.delete_execution(eid)
                print(
                    f"Cleanup: deleted {len(completed)} completed checkpoints",
                    flush=True,
                )

        context["summary"] = {"remaining": remaining}
        return context

    # ══════════════════════════════════════════════════════════
    # Task actions
    # ══════════════════════════════════════════════════════════

    def _run_task(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self._rng.random() < self.fail_rate:
            raise RuntimeError(f"transient failure in {context.get('task_id')}")

        task_id = str(context.get("task_id", ""))
        root_id = str(context.get("root_id", ""))
        depth = int(context.get("depth", 0))

        children = self._generate_children(task_id, root_id, depth)
        context["children"] = children
        context["result"] = f"ok:{task_id}"
        return context

    async def _signal_ready(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Signal that work is ready so the scheduler wakes from deep sleep."""
        if self.signal_backend is not None:
            await self.signal_backend.send("dfss/ready", {"reason": "task_complete"})
        return context

    def _generate_children(
        self, task_id: str, root_id: str, depth: int
    ) -> List[Dict[str, Any]]:
        if depth >= self.max_depth:
            return []

        n = self._rng.randint(0, 2)
        children: List[Dict[str, Any]] = []

        for i in range(n):
            resource_class = self._rng.choice(["fast", "slow"])
            hint = resource_class == "fast" and (self._rng.random() < 0.25)
            if resource_class == "slow":
                distance = 0
            elif hint:
                distance = self._rng.randint(1, max(1, self.max_depth - depth))
            else:
                distance = NO_SLOW_DISTANCE

            children.append({
                "task_id": f"{task_id}.{i}",
                "root_id": root_id,
                "depth": depth + 1,
                "resource_class": resource_class,
                "has_expensive_descendant": bool(hint),
                "distance_to_nearest_slow_descendant": int(distance),
            })

        return children
