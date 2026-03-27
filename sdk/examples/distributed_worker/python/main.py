#!/usr/bin/env python3
"""Distributed worker demo entrypoint.

Usage:
    python main.py seed --count 10
    python main.py checker --max-workers 3
    python main.py worker --worker-id worker-123
    python main.py reaper --threshold 60
    python main.py all --count 5 --max-workers 3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def _run(script: str, *args: str) -> int:
    cmd = [sys.executable, str(HERE / script), *args]
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Distributed worker demo wrapper")
    parser.add_argument("command", choices=["seed", "checker", "worker", "reaper", "all"], nargs="?", default="seed")
    parser.add_argument("--count", "-n", type=int, default=5)
    parser.add_argument("--max-workers", "-m", type=int, default=3)
    parser.add_argument("--threshold", "-t", type=int, default=60)
    parser.add_argument("--pool", "-p", default="default")
    parser.add_argument("--worker-id", "-w", default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    common: list[str] = ["--pool", args.pool]
    if args.db:
        common += ["--db", args.db]

    if args.command == "seed":
        return _run("seed_jobs.py", "--count", str(args.count), *common)

    if args.command == "checker":
        return _run("run_checker.py", "--max-workers", str(args.max_workers), *common)

    if args.command == "worker":
        worker_args: list[str] = []
        if args.worker_id:
            worker_args += ["--worker-id", args.worker_id]
        return _run("run_worker.py", *worker_args, *common)

    if args.command == "reaper":
        return _run("run_reaper.py", "--threshold", str(args.threshold), *common)

    # all
    code = _run("seed_jobs.py", "--count", str(args.count), *common)
    if code != 0:
        return code
    code = _run("run_checker.py", "--max-workers", str(args.max_workers), *common)
    if code != 0:
        return code
    code = _run("run_worker.py", *( ["--worker-id", args.worker_id] if args.worker_id else [] ), *common)
    if code != 0:
        return code
    return _run("run_reaper.py", "--threshold", str(args.threshold), *common)


if __name__ == "__main__":
    raise SystemExit(main())
