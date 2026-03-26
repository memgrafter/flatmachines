#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import random
import signal
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from flatmachines import CheckpointManager, FlatMachine, SQLiteCheckpointBackend, SQLiteWorkBackend

from .hooks import TaskHooks
from .scheduler import ResourcePool, RootState, add_candidate, recompute_root_metrics, run
from .task_machine import task_config


logging.getLogger("flatmachines").setLevel(logging.WARNING)

POOL_NAME = "tasks"
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
        "distance_to_nearest_slow_descendant": int(data.get("distance_to_nearest_slow_descendant", 10_000)),
        "attempts": int(row["attempts"]),
    }


def _load_pending_candidates(db_path: str, pool_name: str = POOL_NAME) -> List[Dict[str, Any]]:
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


def _load_pending_candidate(db_path: str, work_id: str, pool_name: str = POOL_NAME) -> Optional[Dict[str, Any]]:
    with _sqlite_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT item_id, data, attempts
            FROM work_pool
            WHERE pool_name = ? AND item_id = ? AND status = 'pending'
            """,
            (pool_name, work_id),
        ).fetchone()
    if row is None:
        return None
    return _candidate_from_row(row)


def _claim_selected_candidate(
    db_path: str,
    work_id: str,
    *,
    worker_id: str = WORKER_ID,
    pool_name: str = POOL_NAME,
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
            """
            SELECT item_id, data, attempts
            FROM work_pool
            WHERE pool_name = ? AND item_id = ?
            """,
            (pool_name, work_id),
        ).fetchone()

    if row is None:
        return None
    return _candidate_from_row(row)


def _unfinished_work_count(db_path: str, pool_name: str = POOL_NAME) -> int:
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


def _root_terminal_failures(db_path: str, pool_name: str = POOL_NAME) -> Dict[str, int]:
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


def _initial_root_task(root_id: str, max_depth: int, rng: random.Random) -> Dict[str, Any]:
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
    distance = 0 if resource_class == "slow" else (rng.randint(1, max(1, max_depth)) if hint else 10_000)
    return {
        "task_id": f"{root_id}/0",
        "root_id": root_id,
        "depth": 0,
        "resource_class": resource_class,
        "has_expensive_descendant": bool(hint),
        "distance_to_nearest_slow_descendant": int(distance),
    }


async def _seed_roots(
    pool,
    *,
    roots: int,
    max_depth: int,
    seed: int,
    max_attempts: int,
) -> List[str]:
    rng = random.Random(seed)
    root_ids = [f"root-{i:03d}" for i in range(roots)]

    for root_id in root_ids:
        item = _initial_root_task(root_id=root_id, max_depth=max_depth, rng=rng)
        await pool.push(item, options={"max_retries": max_attempts})

    return root_ids


def _build_root_states(root_ids: List[str], candidates: List[Dict[str, Any]]) -> Dict[str, RootState]:
    if not root_ids:
        root_ids = sorted({c["root_id"] for c in candidates})

    roots = {rid: RootState(root_id=rid) for rid in root_ids}
    recompute_root_metrics(roots, candidates)
    return roots


async def _toggle_slow_gate(
    resources: Dict[str, ResourcePool],
    stop_event: asyncio.Event,
    interval: float,
) -> None:
    print("  ⚡ slow gate -> OPEN", flush=True)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass

        slow = resources["slow"]
        slow.gate_open = not slow.gate_open
        state = "OPEN" if slow.gate_open else "CLOSED"
        print(f"  ⚡ slow gate -> {state}", flush=True)


async def _resume_status_report(checkpoint_backend: SQLiteCheckpointBackend) -> None:
    all_execs = set(await checkpoint_backend.list_execution_ids())
    completed = set(await checkpoint_backend.list_execution_ids(event="machine_end"))
    incomplete = sorted(all_execs - completed)

    print(
        f"Resume status: total executions={len(all_execs)}, completed={len(completed)}, incomplete={len(incomplete)}",
        flush=True,
    )
    for execution_id in incomplete[:10]:
        status = await CheckpointManager(checkpoint_backend, execution_id).load_status()
        if status is None:
            print(f"  - {execution_id}: unknown", flush=True)
            continue
        event, state = status
        print(f"  - {execution_id}: event={event}, state={state}", flush=True)


async def _post_run_report(
    checkpoint_backend: SQLiteCheckpointBackend,
    *,
    cleanup: bool,
) -> None:
    all_execs = await checkpoint_backend.list_execution_ids()
    completed = await checkpoint_backend.list_execution_ids(event="machine_end")
    print(
        f"Checkpoint summary: total={len(all_execs)}, completed={len(completed)}, incomplete={len(set(all_execs) - set(completed))}",
        flush=True,
    )

    if cleanup:
        for execution_id in completed:
            await checkpoint_backend.delete_execution(execution_id)
        print(f"Cleanup: deleted {len(completed)} completed checkpoints", flush=True)


async def _run_pipeline(args: argparse.Namespace) -> int:
    db_path = str(Path(args.db_path).resolve())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if not args.resume and Path(db_path).exists():
        Path(db_path).unlink()

    checkpoint_backend = SQLiteCheckpointBackend(db_path=db_path)
    work_backend = SQLiteWorkBackend(db_path=db_path)
    pool = work_backend.pool(POOL_NAME)

    if args.resume:
        meta = _load_meta(db_path)
        root_ids = list(meta.get("root_ids", []))
        args.max_depth = int(meta.get("max_depth", args.max_depth))
        args.max_attempts = int(meta.get("max_attempts", args.max_attempts))
        seed = int(meta.get("seed", args.seed))

        released = await pool.release_by_worker(WORKER_ID)
        print(f"Resuming from {db_path} (released {released} stale claims)", flush=True)
        await _resume_status_report(checkpoint_backend)
    else:
        root_ids = await _seed_roots(
            pool,
            roots=args.roots,
            max_depth=args.max_depth,
            seed=args.seed,
            max_attempts=args.max_attempts,
        )
        _save_meta(
            db_path,
            {
                "root_ids": root_ids,
                "roots": args.roots,
                "max_depth": args.max_depth,
                "seed": args.seed,
                "max_attempts": args.max_attempts,
            },
        )
        seed = int(args.seed)
        print(
            f"Seeded roots={args.roots}, max_depth={args.max_depth}, seed={args.seed}, max_attempts={args.max_attempts}",
            flush=True,
        )

    candidates = _load_pending_candidates(db_path)
    roots = _build_root_states(root_ids, candidates)

    resources: Dict[str, ResourcePool] = {
        "fast": ResourcePool(name="fast", capacity=4, gate_open=True),
        "slow": ResourcePool(name="slow", capacity=2, gate_open=True),
    }

    hooks = TaskHooks(max_depth=args.max_depth, fail_rate=args.fail_rate, seed=seed)
    machine_cfg = task_config()

    announced_complete: set[str] = set()
    terminal_by_root = _root_terminal_failures(db_path)
    for rid, count in terminal_by_root.items():
        if rid in roots:
            roots[rid].terminal_failures = count

    stop_event = asyncio.Event()

    def _on_signal() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, _on_signal)
        loop.add_signal_handler(signal.SIGTERM, _on_signal)
    except (NotImplementedError, RuntimeError):
        pass

    def _refresh_and_report_roots() -> None:
        recompute_root_metrics(roots, candidates)
        for root in roots.values():
            if root.is_done and root.root_id not in announced_complete:
                announced_complete.add(root.root_id)
                state = "COMPLETE" if root.terminal_failures == 0 else "COMPLETE_WITH_TERMINAL_FAILURES"
                print(f"  🏁 {root.root_id} {state}", flush=True)

    async def dispatch(item: Dict[str, Any]) -> None:
        claimed = _claim_selected_candidate(db_path, work_id=item["work_id"])
        if claimed is None:
            return

        root_id = claimed["root_id"]
        task_payload = {
            "task_id": claimed["task_id"],
            "root_id": claimed["root_id"],
            "depth": claimed["depth"],
            "resource_class": claimed["resource_class"],
            "has_expensive_descendant": claimed["has_expensive_descendant"],
            "distance_to_nearest_slow_descendant": claimed["distance_to_nearest_slow_descendant"],
        }

        machine = FlatMachine(
            config_dict=machine_cfg,
            hooks=hooks,
            persistence=checkpoint_backend,
            _execution_id=claimed["work_id"],
        )

        try:
            latest_ptr = await checkpoint_backend.load(f"{claimed['work_id']}/latest")
            if latest_ptr:
                output = await machine.execute(input=task_payload, resume_from=claimed["work_id"])
            else:
                output = await machine.execute(input=task_payload)
        except Exception as exc:  # Defensive: machine-level unexpected failure
            output = {"error": str(exc)}

        error = output.get("error") if isinstance(output, dict) else "unknown task failure"
        if error:
            await pool.fail(claimed["work_id"], str(error))

            if int(claimed["attempts"]) >= args.max_attempts:
                if root_id in roots:
                    roots[root_id].terminal_failures += 1
                print(
                    f"  ✗ {claimed['task_id']:24s} terminal after {claimed['attempts']} attempts: {error}",
                    flush=True,
                )
                return

            pending_retry = _load_pending_candidate(db_path, claimed["work_id"])
            if pending_retry is not None:
                add_candidate(candidates, pending_retry)
            print(
                f"  ⟳ {claimed['task_id']:24s} retry {claimed['attempts']}/{args.max_attempts}",
                flush=True,
            )
            return

        await pool.complete(claimed["work_id"], output)
        if root_id in roots:
            roots[root_id].completed += 1

        children = output.get("children") if isinstance(output, dict) else []
        if not isinstance(children, list):
            children = []

        for child in children:
            if not isinstance(child, dict):
                continue
            work_id = await pool.push(child, options={"max_retries": args.max_attempts})
            add_candidate(
                candidates,
                {
                    "work_id": work_id,
                    "task_id": child["task_id"],
                    "root_id": child["root_id"],
                    "depth": int(child.get("depth", 0)),
                    "resource_class": str(child.get("resource_class", "fast")),
                    "has_expensive_descendant": bool(child.get("has_expensive_descendant", False)),
                    "distance_to_nearest_slow_descendant": int(child.get("distance_to_nearest_slow_descendant", 10_000)),
                    "attempts": 0,
                },
            )

        suffix = f"→ {len(children)} children" if children else "→ leaf"
        print(
            f"  ✓ {claimed['task_id']:24s} (d={claimed['depth']} {claimed['resource_class']}) {suffix}",
            flush=True,
        )

    gate_task = asyncio.create_task(
        _toggle_slow_gate(resources=resources, stop_event=stop_event, interval=args.gate_interval)
    )

    try:
        await run(
            candidates=candidates,
            roots=roots,
            resources=resources,
            dispatch=dispatch,
            max_workers=args.max_workers,
            max_active_roots=args.max_active_roots,
            idle_poll=0.05,
            stop_event=stop_event,
            on_task_done=_refresh_and_report_roots,
        )
    finally:
        stop_event.set()
        gate_task.cancel()
        try:
            await gate_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    remaining = _unfinished_work_count(db_path)
    if remaining == 0:
        print("✅ All work complete.", flush=True)
    else:
        print(f"⚠ Run paused with {remaining} unfinished tasks. Resume with --resume", flush=True)

    await _post_run_report(checkpoint_backend, cleanup=args.cleanup)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DFSS pipeline demo using FlatMachines + SQLite backends")
    parser.add_argument("--roots", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--max-active-roots", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--db-path", type=str, default="data/dfss.sqlite")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fail-rate", type=float, default=0.15)
    parser.add_argument("--gate-interval", type=float, default=0.8)
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    code = asyncio.run(_run_pipeline(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
