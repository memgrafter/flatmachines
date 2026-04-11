from __future__ import annotations

from expert_debate.hooks import ExpertDebateHooks


def test_bootstrap_generates_session_id_when_missing() -> None:
    hooks = ExpertDebateHooks()

    ctx = hooks.on_action("bootstrap_session", {"round_count": 3})

    session_id = ctx.get("session_id")
    assert isinstance(session_id, str)
    assert session_id


def test_bootstrap_preserves_explicit_session_id() -> None:
    hooks = ExpertDebateHooks()

    ctx = hooks.on_action("bootstrap_session", {"session_id": "sess-123"})

    assert ctx["session_id"] == "sess-123"


def test_append_master_turns_to_history_incrementally() -> None:
    hooks = ExpertDebateHooks()

    ctx = {
        "round_index": 1,
        "master_a_name": "Master A",
        "master_b_name": "Master B",
        "current_master_a_statement": "A1",
        "current_master_b_statement": "B1",
        "history_text": "",
    }

    ctx = hooks.on_action("append_master_a_to_history", ctx)
    assert "Round 1 — Master A:\nA1" in ctx["history_text"]
    assert "Master B" not in ctx["history_text"]

    ctx = hooks.on_action("append_master_b_to_history", ctx)
    assert "Round 1 — Master B:\nB1" in ctx["history_text"]


def test_record_round_does_not_rewrite_history() -> None:
    hooks = ExpertDebateHooks()

    existing_history = "Round 1 — Master A:\nA1\n\nRound 1 — Master B:\nB1"
    ctx = {
        "round_count": 2,
        "round_index": 1,
        "current_round_focus": "Focus",
        "master_a_name": "Master A",
        "master_b_name": "Master B",
        "current_master_a_statement": "A1",
        "current_master_b_statement": "B1",
        "history_text": existing_history,
        "transcript": [],
    }

    out = hooks.on_action("record_round", ctx)
    assert out["history_text"] == existing_history
    assert out["round_index"] == 2
