#!/usr/bin/env python3
"""
Burn-in test for Claude Code adapter — cache token validation.

Runs 3 sequential invocations on the same session:
  1. New session (expect: high cache_write, low cache_read)
  2. Resume (expect: high cache_read, low cache_write)
  3. Resume (expect: even higher cache_read)

Per-invocation metrics (tokens, cache, cost, duration) are emitted
automatically by AgentMonitor at INFO level.  This script only adds
the summary table and cache-growth validation on top.

Usage:
    cd sdk/python
    source .venv/bin/activate
    python tests/burnin_claude_code_cache.py
"""

import asyncio
import os
import sys
import uuid

# Add the packages to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flatmachines"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "flatagents"))

from flatagents.monitoring import setup_logging
from flatmachines.adapters.claude_code import ClaudeCodeExecutor

# Ensure AgentMonitor INFO lines are visible
setup_logging(level="INFO")


def _fmt(n):
    """Format token count with commas."""
    if n is None:
        return "—"
    return f"{n:,}"


def _usage(result):
    """Extract usage dict with safe defaults."""
    return result.usage or {}


async def main():
    print("=" * 70)
    print("Claude Code Adapter — Cache Burn-In Test")
    print("=" * 70)
    print()

    work_dir = "/tmp/cc-burnin-test"
    os.makedirs(work_dir, exist_ok=True)

    executor = ClaudeCodeExecutor(
        config={
            "model": "sonnet",  # sonnet is cheaper for burn-in
            "effort": "low",    # keep it fast
            "permission_mode": "bypassPermissions",
            "tools": ["Bash", "Read"],
            "max_continuations": 0,  # no auto-continue for this test
        },
        config_dir=work_dir,
        settings={},
    )

    session_id = str(uuid.uuid4())
    print(f"Session ID: {session_id}")
    print(f"Work dir:   {work_dir}")
    print()

    # --- Step 1: New session ---
    # AgentMonitor will log: Agent claude-code/sonnet completed in Xms - success | tokens: N→M
    print("─" * 70)
    print("Step 1: New session")
    print("─" * 70)
    r1 = await executor._invoke_once(
        task="What is 2+2? Answer briefly.",
        session_id=session_id,
        resume=False,
    )
    if r1.error:
        print(f"FAILED: {r1.error}")
        return
    print()

    # --- Step 2: Resume ---
    print("─" * 70)
    print("Step 2: Resume (should show higher cache_read)")
    print("─" * 70)
    r2 = await executor._invoke_once(
        task="What is 3+3? Answer briefly.",
        session_id=session_id,
        resume=True,
    )
    if r2.error:
        print(f"FAILED: {r2.error}")
        return
    print()

    # --- Step 3: Resume again ---
    print("─" * 70)
    print("Step 3: Resume again (cache_read should stay high or grow)")
    print("─" * 70)
    r3 = await executor._invoke_once(
        task="What is 4+4? Answer briefly.",
        session_id=session_id,
        resume=True,
    )
    if r3.error:
        print(f"FAILED: {r3.error}")
        return
    print()

    # --- Summary table ---
    print("=" * 70)
    print("CACHE SUMMARY")
    print("=" * 70)
    print()
    print(f"  {'Step':<12} {'cache_read':>12} {'cache_write':>12} {'input':>10} {'output':>10} {'cost':>10}")
    print(f"  {'─'*12} {'─'*12} {'─'*12} {'─'*10} {'─'*10} {'─'*10}")
    for label, r in [("New session", r1), ("Resume #1", r2), ("Resume #2", r3)]:
        u = _usage(r)
        cr = u.get("cache_read_tokens", 0)
        cw = u.get("cache_write_tokens", 0)
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        cost = r.cost if isinstance(r.cost, (int, float)) else 0
        print(f"  {label:<12} {_fmt(cr):>12} {_fmt(cw):>12} {_fmt(inp):>10} {_fmt(out):>10} {'${:.4f}'.format(cost):>10}")

    print()

    # --- Validate cache growth ---
    cr1 = _usage(r1).get("cache_read_tokens", 0)
    cr2 = _usage(r2).get("cache_read_tokens", 0)
    cr3 = _usage(r3).get("cache_read_tokens", 0)

    if cr2 > cr1:
        print("  ✓ Cache read tokens INCREASED on resume #1 — caching is working!")
    else:
        print("  ✗ Cache read tokens did NOT increase on resume #1")
        print(f"    Step 1: {cr1}, Step 2: {cr2}")

    if cr3 >= cr2:
        print("  ✓ Cache read tokens HELD or GREW on resume #2 — consistent.")
    else:
        print(f"  ⚠ Cache read tokens decreased on resume #2: {cr2} → {cr3}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
