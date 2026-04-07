#!/usr/bin/env python3
"""Live self-improve integration test.

Creates a test project with an intentionally slow multiply function,
runs a read-only FlatAgent via the codex backend, and verifies the
agent identifies the inefficiency and proposes the correct fix.

The agent only gets the `read` tool — no writes, no side effects.
This tests the full FlatMachine→FlatAgent→codex pipeline cheaply.

Run:
  cd sdk/python
  python -m pytest tests/integration/self_improve/test_self_improve_live.py -v --live -s

Cost: ~$0.002 per run (~3 codex calls, ~1k tokens each, ~15 seconds).
"""

from __future__ import annotations

import os
import textwrap
import warnings

import pytest


def _create_test_project(tmp_path):
    """Create a test project with an intentionally slow multiply function."""
    app_py = tmp_path / "app.py"
    app_py.write_text(textwrap.dedent("""\
        def add(a, b):
            \"\"\"Add two numbers.\"\"\"
            return a + b

        def multiply(a, b):
            \"\"\"Multiply two numbers (intentionally slow).\"\"\"
            result = 0
            for _ in range(b):
                result = add(result, a)
            return result
    """))

    benchmark_sh = tmp_path / "benchmark.sh"
    benchmark_sh.write_text(textwrap.dedent("""\
        #!/bin/bash
        set -euo pipefail
        cd "$(dirname "$0")"
        python3 -c "
        import time
        from app import add, multiply

        t0 = time.time()
        for i in range(10000):
            add(i, i+1)
            multiply(i, 3)
        elapsed = time.time() - t0
        print(f'METRIC speed_ms={elapsed*1000:.0f}')
        "
    """))
    benchmark_sh.chmod(0o755)

    return tmp_path


@pytest.mark.asyncio
@pytest.mark.live
async def test_self_improve_analysis(tmp_path):
    """Agent reads code with read tool and identifies the multiply inefficiency."""
    from flatagents import FlatAgent, ValidationWarning

    project_dir = _create_test_project(tmp_path)

    auth_file = os.path.expanduser(
        os.environ.get("FLATAGENTS_CODEX_AUTH_FILE", "~/.pi/agent/auth.json")
    )
    if not os.path.exists(auth_file):
        pytest.skip(f"Codex auth file not found: {auth_file}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ValidationWarning)
        agent = FlatAgent(
            config_dict={
                "spec": "flatagent",
                "spec_version": "2.5.0",
                "data": {
                    "name": "self-improve-analysis-test",
                    "model": {
                        "provider": "openai-codex",
                        "name": "gpt-5.3-codex",
                        "backend": "codex",
                        "base_url": "https://chatgpt.com/backend-api",
                        "oauth": {
                            "provider": "openai-codex",
                            "auth_file": auth_file,
                        },
                    },
                    "system": "You are a code analyst. Read the files and identify performance improvements.",
                    "user": (
                        "Read the files in {{ input.target_dir }} (app.py and benchmark.sh) and identify "
                        "the biggest performance improvement opportunity. "
                        "Explain what you would change and why."
                    ),
                },
            }
        )

    read_tool = {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                },
                "required": ["path"],
            },
        },
    }

    # First call — agent should request to read files
    r1 = await agent.call(
        tools=[read_tool],
        target_dir=str(project_dir),
    )
    assert r1.error is None, f"Call 1 error: {r1.error}"

    messages = []
    if r1.rendered_user_prompt:
        messages.append({"role": "user", "content": r1.rendered_user_prompt})

    # Feed tool results until agent stops calling tools (max 5 rounds)
    resp = r1
    for _ in range(5):
        if not resp.tool_calls:
            break

        messages.append({
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.tool,
                        "arguments": __import__("json").dumps(tc.arguments or {}),
                    },
                }
                for tc in resp.tool_calls
            ],
        })

        for tc in resp.tool_calls:
            path = (tc.arguments or {}).get("path", "")
            try:
                content = open(path).read()
            except Exception as e:
                content = f"Error: {e}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content,
            })

        resp = await agent.call(
            messages=messages,
            tools=[read_tool],
            prompt="Continue your analysis.",
        )
        assert resp.error is None, f"Follow-up error: {resp.error}"

    # Agent should have produced analysis mentioning the multiply issue
    output = resp.content or ""
    assert output, "Agent produced no analysis"

    output_lower = output.lower()
    identified = (
        "multiply" in output_lower
        or "a * b" in output_lower
        or "loop" in output_lower
        or "operator" in output_lower
    )
    assert identified, (
        f"Agent did not identify the multiply inefficiency.\n"
        f"Output:\n{output}"
    )

    print(f"\n  Agent analysis ({len(output)} chars):")
    print(f"  {output[:500]}")
