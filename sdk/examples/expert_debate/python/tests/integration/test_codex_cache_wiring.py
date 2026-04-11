from __future__ import annotations

from pathlib import Path

import asyncio

import pytest
import yaml

from flatagents import FlatAgent
from flatagents.providers.openai_codex_types import CodexResult, CodexUsage


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def test_master_prompt_places_cache_block_first_and_forwards_session_id(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    async def fake_codex_call(self, params):  # noqa: ANN001
        captured.append(params)
        return CodexResult(
            content="ok",
            usage=CodexUsage(input_tokens=10, output_tokens=5, total_tokens=15, cached_tokens=0),
        )

    monkeypatch.setattr("flatagents.providers.openai_codex_client.CodexClient.call", fake_codex_call)

    agent = FlatAgent(config_file=str(config_dir / "master_shared.yml"))
    response = asyncio.run(
        agent.call(
            persona_prompt="You are debating from your assigned role.",
            role_name="Master A",
            role_domain="systems thinking",
            role_viewpoint="emphasize structural constraints",
            opponent_name="Master B",
            opponent_statement="",
            topic="Will LLMs try to escape?",
            audience="curious generalist",
            learning_goal="understand arguments",
            round_index=1,
            round_count=3,
            rounds_remaining=3,
            round_focus="Definitions and framing",
            history_text="",
            cache_prefix="cache_anchor cache_anchor cache_anchor",
            session_id="sess-a",
        )
    )

    assert response.error is None
    assert response.content == "ok"
    assert len(captured) == 1

    params = captured[0]
    assert params["session_id"] == "sess-a"

    user_message = next(m for m in params["messages"] if m.get("role") == "user")
    user_text = user_message["content"]
    assert user_text.startswith("Stable cache prefix block (verbatim, do not reinterpret):")
    assert "System reminder for this turn:" in user_text
    assert "You are a master of systems thinking." in user_text



def test_next_turn_prefix_stays_shared_through_history_block(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    async def fake_codex_call(self, params):  # noqa: ANN001
        captured.append(params)
        return CodexResult(
            content="ok",
            usage=CodexUsage(input_tokens=10, output_tokens=5, total_tokens=15, cached_tokens=0),
        )

    monkeypatch.setattr("flatagents.providers.openai_codex_client.CodexClient.call", fake_codex_call)

    agent = FlatAgent(config_file=str(config_dir / "master_shared.yml"))

    asyncio.run(
        agent.call(
            persona_prompt="Persona A",
            role_name="Master A",
            role_domain="systems thinking",
            role_viewpoint="emphasize structure",
            opponent_name="Master B",
            opponent_statement="",
            topic="Will LLMs try to escape?",
            audience="curious generalist",
            learning_goal="understand arguments",
            round_index=1,
            round_count=3,
            rounds_remaining=3,
            round_focus="Definitions and framing",
            history_text="",
            cache_prefix="cache_anchor cache_anchor cache_anchor",
            session_id="sess-a",
        )
    )

    asyncio.run(
        agent.call(
            persona_prompt="Persona B",
            role_name="Master B",
            role_domain="historical analysis",
            role_viewpoint="emphasize evidence",
            opponent_name="Master A",
            opponent_statement="Master A opening",
            topic="Will LLMs try to escape?",
            audience="curious generalist",
            learning_goal="understand arguments",
            round_index=1,
            round_count=3,
            rounds_remaining=3,
            round_focus="Definitions and framing",
            history_text="",
            cache_prefix="cache_anchor cache_anchor cache_anchor",
            session_id="sess-a",
        )
    )

    assert len(captured) == 2

    u1 = next(m for m in captured[0]["messages"] if m.get("role") == "user")["content"]
    u2 = next(m for m in captured[1]["messages"] if m.get("role") == "user")["content"]

    marker = "Conversation history so far (all prior turns):"
    marker_idx = u1.find(marker)
    assert marker_idx >= 0

    shared_prefix = _common_prefix_len(u1, u2)
    assert shared_prefix > marker_idx, (
        f"Shared prefix ended too early (idx={shared_prefix}, history_marker={marker_idx}); "
        "dynamic fields are likely before history and will bust cache continuity."
    )


def test_machine_uses_shared_master_agent_and_session_id(config_dir: Path) -> None:
    machine_cfg = yaml.safe_load((config_dir / "machine.yml").read_text(encoding="utf-8"))
    states = machine_cfg["data"]["states"]

    assert states["master_a_turn"]["agent"] == "master"
    assert states["master_b_turn"]["agent"] == "master"
    assert states["master_a_turn"]["input"]["session_id"] == "{{ context.session_id }}"
    assert states["master_b_turn"]["input"]["session_id"] == "{{ context.session_id }}"

    assert states["append_master_a_to_history"]["action"] == "append_master_a_to_history"
    assert states["append_master_b_to_history"]["action"] == "append_master_b_to_history"
    assert states["master_a_turn"]["transitions"][0]["to"] == "append_master_a_to_history"
    assert states["append_master_a_to_history"]["transitions"][0]["to"] == "master_b_turn"
    assert states["master_b_turn"]["transitions"][0]["to"] == "append_master_b_to_history"
    assert states["append_master_b_to_history"]["transitions"][0]["to"] == "record_round"
