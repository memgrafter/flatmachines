"""
DFSS Deep Sleep — scheduler runner.

Thin glue: parse args, construct backends, execute the scheduler machine.
All orchestration logic lives in the machine states + hook actions.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from flatmachines import (
    FlatMachine,
    HooksRegistry,
    SQLiteCheckpointBackend,
    SQLiteWorkBackend,
    SQLiteSignalBackend,
)

from flatagent_dfss_deepsleep.hooks import DeepSleepHooks, _load_meta

logging.getLogger("flatmachines").setLevel(logging.WARNING)


async def _run(args: argparse.Namespace) -> int:
    db_path = str(Path(args.db_path).resolve())
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if not args.resume and Path(db_path).exists():
        Path(db_path).unlink()

    config_path = str(
        Path(__file__).parent.parent.parent.parent / "config" / "scheduler_machine.yml"
    )

    checkpoint_backend = SQLiteCheckpointBackend(db_path=db_path)
    work_backend = SQLiteWorkBackend(db_path=db_path)
    signal_backend = SQLiteSignalBackend(db_path=db_path)

    hooks = DeepSleepHooks(
        max_depth=args.max_depth,
        fail_rate=args.fail_rate,
        seed=args.seed,
        max_attempts=args.max_attempts,
        gate_interval=args.gate_interval,
        work_backend=work_backend,
        signal_backend=signal_backend,
        checkpoint_backend=checkpoint_backend,
        pool_name="tasks",
    )

    # Register hooks in registry so child machines (task_runner) resolve by name
    registry = HooksRegistry()
    registry.register("deepsleep", lambda: hooks)

    machine_input = {
        "pool_name": "tasks",
        "max_active_roots": args.max_active_roots,
        "batch_size": args.batch_size,
        "n_roots": args.roots,
        "max_depth": args.max_depth,
        "resume": args.resume,
        "cleanup": args.cleanup,
    }

    if args.resume:
        # Find the execution to resume
        waiting_ids = await checkpoint_backend.list_execution_ids(
            waiting_channel="dfss/ready"
        )
        all_ids = await checkpoint_backend.list_execution_ids()
        completed_ids = set(
            await checkpoint_backend.list_execution_ids(event="machine_end")
        )
        incomplete_ids = [eid for eid in all_ids if eid not in completed_ids]

        execution_id = None
        if waiting_ids:
            execution_id = waiting_ids[0]
        elif incomplete_ids:
            execution_id = incomplete_ids[0]

        if execution_id is None:
            print("Nothing to resume.", flush=True)
            return 0

        # Restore args from meta
        meta = _load_meta(db_path)
        if meta:
            args.max_depth = int(meta.get("max_depth", args.max_depth))
            args.max_attempts = int(meta.get("max_attempts", args.max_attempts))
            hooks.max_depth = args.max_depth
            hooks.max_attempts = args.max_attempts

        # Send signal to unblock wait_for if parked there
        await signal_backend.send("dfss/ready", {"reason": "resume"})

        print(f"Resuming execution {execution_id}", flush=True)
        machine = FlatMachine(
            config_file=config_path,
            hooks_registry=registry,
            persistence=checkpoint_backend,
            signal_backend=signal_backend,
        )
        result = await machine.execute(
            input=machine_input, resume_from=execution_id
        )
    else:
        # Send initial signal so scheduler doesn't immediately sleep
        await signal_backend.send("dfss/ready", {"reason": "initial_seed"})

        machine = FlatMachine(
            config_file=config_path,
            hooks_registry=registry,
            persistence=checkpoint_backend,
            signal_backend=signal_backend,
        )
        result = await machine.execute(input=machine_input)

    if isinstance(result, dict) and result.get("_waiting"):
        print(
            f"Scheduler sleeping on channel: {result.get('_channel')}",
            flush=True,
        )
        print("Resume with --resume", flush=True)
    else:
        print("Scheduler finished.", flush=True)

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DFSS Deep Sleep scheduler — checkpoint-and-exit scheduling"
    )
    parser.add_argument("--roots", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--max-active-roots", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--db-path", type=str, default="data/dfss.sqlite")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--fail-rate", type=float, default=0.15)
    parser.add_argument("--gate-interval", type=float, default=0.8)
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    code = asyncio.run(_run(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
