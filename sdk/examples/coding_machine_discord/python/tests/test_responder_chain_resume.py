from __future__ import annotations

import asyncio
from typing import Any

from tool_use_discord import main


class _FakeAPI:
    channel_id = "chan-1"

    def post_channel_message(self, _text: str) -> None:
        return None


def test_conversation_execution_id_is_stable() -> None:
    assert main._conversation_execution_id("123") == "discord-machine-123"
    assert main._conversation_execution_id("abc") == "discord-machine-abc"


def test_compose_reply_resumes_existing_execution_with_signal(monkeypatch):
    sent_signals: list[tuple[str, dict[str, Any]]] = []
    execute_calls: list[dict[str, Any]] = []

    class _FakeCheckpointBackend:
        def __init__(self, *args, **kwargs):
            self.deleted: list[str] = []

        async def delete_execution(self, execution_id: str) -> None:
            self.deleted.append(execution_id)

    class _FakeSignalBackend:
        def __init__(self, *args, **kwargs):
            pass

        async def send(self, channel: str, data: Any) -> str:
            sent_signals.append((channel, data))
            return "sig-1"

    class _FakeLock:
        def __init__(self, *args, **kwargs):
            pass

    class _FakeCheckpointManager:
        def __init__(self, _backend, _execution_id: str):
            pass

        async def load_status(self):
            return ("waiting", "wait_for_feedback")

    class _FakeMachine:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, input=None, resume_from=None):
            execute_calls.append({"input": input, "resume_from": resume_from})
            return {"_waiting": True, "_channel": "discord/chan-1"}

    monkeypatch.setattr(main, "SQLiteCheckpointBackend", _FakeCheckpointBackend)
    monkeypatch.setattr(main, "SQLiteSignalBackend", _FakeSignalBackend)
    monkeypatch.setattr(main, "SQLiteLeaseLock", _FakeLock)
    monkeypatch.setattr(main, "CheckpointManager", _FakeCheckpointManager)
    monkeypatch.setattr(main, "FlatMachine", _FakeMachine)

    responder = main.CodingMachineBatchResponder(
        working_dir=".",
        api=_FakeAPI(),
        backend=None,
        db_path="/tmp/discord-test.sqlite",
        input_queue="discord_debounced",
        queue_wait_seconds=1.0,
        conversation_idle_timeout_seconds=1.0,
        queue_poll_seconds=0.1,
    )

    batch = {
        "conversation_key": "chan-1",
        "message_count": 1,
        "messages": [{"author_name": "alice", "content": "follow up"}],
    }

    result = asyncio.run(responder.compose_reply(batch))

    assert result is None
    assert execute_calls[0]["resume_from"] == "discord-machine-chan-1"
    assert sent_signals[0][0] == "discord/chan-1"
    assert sent_signals[0][1]["latest_user_request"] == "follow up"


def test_queue_feedback_action_appends_to_tool_loop_chain() -> None:
    hooks = main.DiscordMachineHooks(working_dir=".", api=_FakeAPI())
    context = {
        "batch_messages": [{"author_name": "alice", "content": "tell me more"}],
        "_tool_loop_chain": [{"role": "assistant", "content": "hello"}],
    }

    updated = asyncio.run(hooks.on_action("queue_feedback", context))

    assert updated["_tool_loop_chain"][-1] == {"role": "user", "content": "alice: tell me more"}
