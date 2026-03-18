#!/usr/bin/env python3
"""
Burn-in test for Claude Code adapter — cache token validation.

Runs 3 sequential invocations on the same session:
  1. New session (expect: high cache_write, low cache_read)
  2. Resume (expect: high cache_read, low cache_write)
  3. Resume (expect: even higher cache_read)

Prints a clear table of cache metrics per step so you can verify
prompt caching is working.

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

from flatmachines.adapters.claude_code import ClaudeCodeExecutor


def _fmt(n):
    """Format token count with commas."""
    if n is None:
        return "—"
    return f"{n:,}"


def _print_row(step, label, result):
    usage = result.usage or {}
    cache_read = usage.get("cache_read_tokens", 0)
    cache_write = usage.get("cache_write_tokens", 0)
    input_tok = usage.get("input_tokens", 0)
    output_tok = usage.get("output_tokens", 0)
    cost = result.cost if isinstance(result.cost, (int, float)) else 0
    session = (result.metadata or {}).get("session_id", "?")
    turns = (result.metadata or {}).get("num_turns", "?")
    duration = (result.metadata or {}).get("duration_ms", "?")

    print(f"  {step}. {label}")
    print(f"     session:     {session}")
    print(f"     input:       {_fmt(input_tok)}")
    print(f"     output:      {_fmt(output_tok)}")
    print(f"     cache_read:  {_fmt(cache_read)}")
    print(f"     cache_write: {_fmt(cache_write)}")
    print(f"     cost:        ${cost:.4f}" if cost else "     cost:        —")
    print(f"     turns:       {turns}")
    print(f"     duration_ms: {duration}")
    if result.error:
        print(f"     ERROR:       {result.error}")
    print()


async def main():
    print("=" * 70)
    print("Claude Code Adapter — Cache Burn-In Test")
    print("=" * 70)
    print()

    # Use a temp directory so we don't interfere with anything
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
    print("─" * 70)
    print("Step 1: New session")
    print("─" * 70)
    r1 = await executor._invoke_once(
        task="What is 2+2? Answer briefly.",
        session_id=session_id,
        resume=False,
    )
    _print_row(1, "New session", r1)

    if r1.error:
        print("FAILED — aborting.")
        return

    # --- Step 2: Resume ---
    print("─" * 70)
    print("Step 2: Resume (should show higher cache_read)")
    print("─" * 70)
    r2 = await executor._invoke_once(
        task="What is 3+3? Answer briefly.",
        session_id=session_id,
        resume=True,
    )
    _print_row(2, "Resume #1", r2)

    if r2.error:
        print("FAILED — aborting.")
        return

    # --- Step 3: Resume again ---
    print("─" * 70)
    print("Step 3: Resume again (cache_read should stay high or grow)")
    print("─" * 70)
    r3 = await executor._invoke_once(
        task="What is 4+4? Answer briefly.",
        session_id=session_id,
        resume=True,
    )
    _print_row(3, "Resume #2", r3)

    # --- Summary ---
    print("=" * 70)
    print("CACHE SUMMARY")
    print("=" * 70)
    print()
    print(f"  {'Step':<12} {'cache_read':>12} {'cache_write':>12} {'input':>10} {'output':>10} {'cost':>10}")
    print(f"  {'─'*12} {'─'*12} {'─'*12} {'─'*10} {'─'*10} {'─'*10}")
    for i, (label, r) in enumerate(
        [("New session", r1), ("Resume #1", r2), ("Resume #2", r3)], 1
    ):
        u = r.usage or {}
        cr = u.get("cache_read_tokens", 0)
        cw = u.get("cache_write_tokens", 0)
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        cost = r.cost if isinstance(r.cost, (int, float)) else 0
        print(f"  {label:<12} {_fmt(cr):>12} {_fmt(cw):>12} {_fmt(inp):>10} {_fmt(out):>10} {'${:.4f}'.format(cost):>10}")

    print()

    # Validate
    u1 = (r1.usage or {})
    u2 = (r2.usage or {})
    u3 = (r3.usage or {})
    cr1 = u1.get("cache_read_tokens", 0)
    cr2 = u2.get("cache_read_tokens", 0)
    cr3 = u3.get("cache_read_tokens", 0)

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
