#!/usr/bin/env python3
"""Live Codex OAuth integration regression tests.

Pattern under test (strict):
  1) normal message
  2) tool call round #1
  3) tool call round #2
  4) tool call round #3
  5) message after final tool call
  6) follow-up message

This verifies session/prompt-cache key continuity and per-round cache-read behavior.

Run:
  cd sdk/python
  python -m pytest tests/integration/codex/test_codex_oauth_live.py -v --live -s
"""

from __future__ import annotations

import json
import os
import uuid
import warnings

import pytest
from flatagents import FlatAgent, ValidationWarning


@pytest.mark.asyncio
@pytest.mark.live
async def test_codex_oauth_cache_continuity_across_post_tool_and_followup() -> None:
    auth_file = os.path.expanduser(
        os.environ.get("FLATAGENTS_CODEX_AUTH_FILE", "~/.agents/flatmachines/auth.json")
    )
    if not os.path.exists(auth_file):
        pytest.skip(f"Codex auth file not found: {auth_file}")

    # 5k tokens to avoid tiny-cache edge behavior.
    long_seed = "TOK " * 5000

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ValidationWarning)
        agent = FlatAgent(
            config_dict={
                "spec": "flatagent",
                "spec_version": "2.4.4",
                "data": {
                    "name": "codex-live-cache-regression",
                    "model": {
                        "provider": "openai-codex",
                        "name": "gpt-5.3-codex",
                        "backend": "codex",
                        "base_url": "https://chatgpt.com/backend-api",
                        "oauth": {
                            "provider": "openai-codex",
                            "auth_file": auth_file,
                            "originator": "flatagents",
                            "refresh": True,
                        },
                    },
                    "system": "You are a precise assistant.",
                    "user": "{{ input.prompt }}",
                },
            }
        )

    session_id = str(uuid.uuid4())

    tool_pwd = {
        "type": "function",
        "function": {
            "name": "tool_pwd",
            "description": "Return current working directory",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    tool_ls = {
        "type": "function",
        "function": {
            "name": "tool_ls",
            "description": "List directory entries",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    tool_readme = {
        "type": "function",
        "function": {
            "name": "tool_readme",
            "description": "Read README summary",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    # Keep tool definitions static across the whole session.
    session_tools = [tool_pwd, tool_ls, tool_readme]

    def _request_meta(resp):
        raw = resp.raw_response
        return getattr(raw, "_request_meta", {}) if raw is not None else {}

    def _cache_read(resp) -> int:
        usage = resp.usage
        return int(getattr(usage, "cache_read_tokens", 0) or 0) if usage else 0

    def _usage_triplet(resp) -> tuple[int, int, int]:
        usage = resp.usage
        if usage is None:
            return 0, 0, 0
        return (
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "cache_read_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )

    def _append_tool_round(chain: list[dict], resp) -> None:
        if resp.rendered_user_prompt:
            chain.append({"role": "user", "content": resp.rendered_user_prompt})

        chain.append(
            {
                "role": "assistant",
                "content": resp.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.tool,
                            "arguments": json.dumps(tc.arguments or {}),
                        },
                    }
                    for tc in (resp.tool_calls or [])
                ],
            }
        )

        for tc in resp.tool_calls or []:
            chain.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"{tc.tool} output: ok",
                }
            )

    # 1) normal message
    r1 = await agent.call(
        prompt=(
            "Acknowledge in one short sentence and wait for follow-up. "
            "Do not call any tools. "
            f"CONTEXT_START {long_seed} CONTEXT_END"
        ),
        tools=session_tools,
        session_id=session_id,
    )
    assert r1.error is None, f"Round 1 error: {r1.error}"
    assert r1.content

    chain: list[dict] = [
        {"role": "user", "content": r1.rendered_user_prompt or ""},
        {"role": "assistant", "content": r1.content or ""},
    ]

    # 2) tool call round #1
    r2 = await agent.call(
        messages=chain,
        tools=session_tools,
        prompt="Call tool_pwd now, then wait for tool output.",
        session_id=session_id,
    )
    assert r2.error is None, f"Round 2 error: {r2.error}"
    assert r2.tool_calls, "Expected tool calls in round 2"
    assert any(tc.tool == "tool_pwd" for tc in (r2.tool_calls or [])), "Round 2 did not call tool_pwd"
    _append_tool_round(chain, r2)

    # 3) tool call round #2
    r3 = await agent.call(
        messages=chain,
        tools=session_tools,
        prompt="Call tool_ls now, then wait for tool output.",
        session_id=session_id,
    )
    assert r3.error is None, f"Round 3 error: {r3.error}"
    assert r3.tool_calls, "Expected tool calls in round 3"
    assert any(tc.tool == "tool_ls" for tc in (r3.tool_calls or [])), "Round 3 did not call tool_ls"
    _append_tool_round(chain, r3)

    # 4) tool call round #3
    r4 = await agent.call(
        messages=chain,
        tools=session_tools,
        prompt="Call tool_readme now, then wait for tool output.",
        session_id=session_id,
    )
    assert r4.error is None, f"Round 4 error: {r4.error}"
    assert r4.tool_calls, "Expected tool calls in round 4"
    assert any(tc.tool == "tool_readme" for tc in (r4.tool_calls or [])), "Round 4 did not call tool_readme"
    _append_tool_round(chain, r4)

    # 5) message after final tool call
    r5 = await agent.call(
        messages=chain,
        tools=session_tools,
        prompt="Provide one concise technical summary now. Do not call any tools.",
        session_id=session_id,
    )
    assert r5.error is None, f"Round 5 error: {r5.error}"
    assert r5.content, "Expected text response after final tool outputs"
    chain.append({"role": "assistant", "content": r5.content or ""})

    # 6) follow-up message
    r6 = await agent.call(
        messages=chain,
        tools=session_tools,
        prompt="One short follow-up sentence. Do not call any tools.",
        session_id=session_id,
    )
    assert r6.error is None, f"Round 6 error: {r6.error}"
    assert r6.content

    rounds = [
        (1, r1),
        (2, r2),
        (3, r3),
        (4, r4),
        (5, r5),
        (6, r6),
    ]

    # Session/prompt-cache key continuity must hold for all continuation rounds.
    for idx, resp in rounds[1:]:
        meta = _request_meta(resp)
        assert meta.get("prompt_cache_key") == session_id, f"Round {idx} prompt_cache_key mismatch"
        headers = meta.get("headers") if isinstance(meta, dict) else {}
        assert isinstance(headers, dict), f"Round {idx} missing request headers in meta"
        assert headers.get("session_id") == session_id, f"Round {idx} session_id header mismatch"

    # Original cache assertions: every continuation round should report cache reads.
    for idx, resp in rounds[1:]:
        assert _cache_read(resp) > 0, f"Expected cache_read_tokens > 0 on round {idx}, got {resp.usage}"

    # Emit round-level cache telemetry as markdown table.
    print("\n| round | read tok | cached read tok | out tok |")
    print("|---:|---:|---:|---:|")
    for round_num, resp in rounds:
        read_tok, cached_read_tok, out_tok = _usage_triplet(resp)
        print(f"| {round_num} | {read_tok} | {cached_read_tok} | {out_tok} |")
