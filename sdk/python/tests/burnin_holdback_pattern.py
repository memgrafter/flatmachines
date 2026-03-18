#!/usr/bin/env python3
"""
Burn-in test for the session holdback pattern.

Exercises: seed (+ auto-warm) → fork × 3 (parallel) → warm → fork again.
Prints cache metrics at every step.

Usage:
    cd sdk/python
    source .venv/bin/activate
    python tests/burnin_holdback_pattern.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flatmachines"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flatagents"))

from flatmachines.adapters.claude_code import ClaudeCodeExecutor
from flatmachines.adapters.claude_code_sessions import SessionHoldback


def _fmt(n):
    if n is None:
        return "—"
    return f"{n:,}"


def _print_result(label, result, session_id=""):
    usage = result.usage or {}
    cr = usage.get("cache_read_tokens", 0)
    cw = usage.get("cache_write_tokens", 0)
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cost = result.cost if isinstance(result.cost, (int, float)) else 0
    sid = (result.metadata or {}).get("session_id", session_id)
    content = (result.content or "")[:80].replace("\n", " ")
    err = result.error

    print(f"  {label}")
    print(f"    session:     {sid}")
    print(f"    cache_read:  {_fmt(cr):<10}  cache_write: {_fmt(cw)}")
    print(f"    input:       {_fmt(inp):<10}  output:      {_fmt(out)}")
    print(f"    cost:        ${cost:.4f}" if cost else "    cost:        —")
    if err:
        print(f"    ERROR:       {err.get('message', err)[:80]}")
    else:
        print(f"    content:     {content}")
    print()


async def main():
    print("=" * 70)
    print("Session Holdback Pattern — Burn-In Test")
    print("=" * 70)
    print()

    work_dir = "/tmp/cc-holdback-burnin"
    os.makedirs(work_dir, exist_ok=True)

    executor = ClaudeCodeExecutor(
        config={
            "model": "sonnet",
            "effort": "low",
            "permission_mode": "bypassPermissions",
            "tools": ["Bash", "Read"],
            "max_continuations": 0,
            "working_dir": work_dir,
        },
        config_dir=work_dir,
        settings={},
    )

    holdback = SessionHoldback(executor=executor)

    # --- Seed (includes auto-warm) ---
    print("─" * 70)
    print("SEED + AUTO-WARM: Establish holdback session and prime cache")
    print("─" * 70)
    seed_result = await holdback.seed(
        "You are a coding assistant. The project uses Python 3.12 with FastAPI. "
        "The main entry point is src/main.py. Acknowledge and remember this context."
    )
    _print_result("Seed", seed_result, holdback.session_id)

    if seed_result.error:
        print("Seed FAILED — aborting.")
        return

    # --- Parallel fork × 3 ---
    print("─" * 70)
    print("FORK × 3: Parallel fan-out from holdback (cache should be warm)")
    print("─" * 70)
    tasks = [
        "What framework does this project use? Reply in one word.",
        "What is the main entry point file? Reply with just the path.",
        "What Python version does this project use? Reply with just the version.",
    ]

    fork_results = await holdback.fork_n(tasks, max_concurrent=3)

    for i, fr in enumerate(fork_results, 1):
        _print_result(f"Fork {i} ({tasks[i-1][:40]}...)", fr.result, fr.session_id)

    # --- Warm ---
    print("─" * 70)
    print("WARM: Touch API cache (fork discarded)")
    print("─" * 70)
    warm_result = await holdback.warm()
    _print_result("Warm", warm_result)

    # --- Fork after warm ---
    print("─" * 70)
    print("FORK after warm: Should still hit cache")
    print("─" * 70)
    post_warm = await holdback.fork(
        "What framework and Python version does this project use? One line."
    )
    _print_result("Post-warm fork", post_warm.result, post_warm.session_id)

    # --- Summary table ---
    print("=" * 70)
    print("CACHE SUMMARY")
    print("=" * 70)
    print()
    print(f"  {'Step':<22} {'cache_read':>12} {'cache_write':>12} {'cost':>10}")
    print(f"  {'─'*22} {'─'*12} {'─'*12} {'─'*10}")

    rows = [("Seed", seed_result)]
    for i, fr in enumerate(fork_results, 1):
        rows.append((f"Fork {i}", fr.result))
    rows.append(("Warm", warm_result))
    rows.append(("Post-warm fork", post_warm.result))

    for label, r in rows:
        u = r.usage or {}
        cr = u.get("cache_read_tokens", 0)
        cw = u.get("cache_write_tokens", 0)
        cost = r.cost if isinstance(r.cost, (int, float)) else 0
        print(f"  {label:<22} {_fmt(cr):>12} {_fmt(cw):>12} {'${:.4f}'.format(cost):>10}")

    print()
    print(f"  Holdback session: {holdback.session_id}")
    print(f"  Total forks:      {holdback.stats['fork_count']}")
    print(f"  Total cost:       ${holdback.stats['total_cost']:.4f}")

    # Validate
    print()
    fork_reads = [
        (fr.result.usage or {}).get("cache_read_tokens", 0)
        for fr in fork_results
    ]
    seed_write = (seed_result.usage or {}).get("cache_write_tokens", 0)

    if all(cr > 6500 for cr in fork_reads):
        print("  ✓ All parallel forks hit conversation cache (not just system prompt)")
    elif all(cr > 0 for cr in fork_reads):
        print("  ~ All forks hit system prompt cache, but conversation may have missed")
    else:
        print("  ✗ Some forks missed cache entirely")

    post_cr = (post_warm.result.usage or {}).get("cache_read_tokens", 0)
    if post_cr > 6500:
        print("  ✓ Post-warm fork hits full cache")
    elif post_cr > 0:
        print("  ~ Post-warm fork hits partial cache")
    else:
        print("  ✗ Post-warm fork missed cache")

    print()


if __name__ == "__main__":
    asyncio.run(main())
