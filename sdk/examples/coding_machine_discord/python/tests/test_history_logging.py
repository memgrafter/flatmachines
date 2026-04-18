from __future__ import annotations

import asyncio
import json

from tool_use_discord import main


class _FakeAPI:
    channel_id = "chan-1"

    def __init__(self) -> None:
        self.posts: list[str] = []

    def post_channel_message(self, text: str) -> None:
        self.posts.append(text)


def test_history_jsonl_captures_user_assistant_tool_flow(monkeypatch, tmp_path) -> None:
    history_dir = tmp_path / "history"
    monkeypatch.setenv("TOOL_USE_DISCORD_HISTORY_DIR", str(history_dir))

    api = _FakeAPI()
    hooks = main.DiscordMachineHooks(working_dir=".", api=api)

    context: dict = {
        "conversation_key": "chan-1",
        "batch_messages": [{"author_name": "alice", "content": "please inspect logs"}],
        "_tool_loop_chain": [],
    }

    context = hooks.on_state_enter("admin_work", context)
    context = asyncio.run(hooks.on_action("queue_feedback", context))

    context["_tool_loop_chain"].append(
        {
            "role": "assistant",
            "content": "I'll inspect now.",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": '{"path":"README.md"}',
                    },
                }
            ],
        }
    )
    context = hooks.on_tool_calls(
        "admin_work",
        [{"id": "call-1", "name": "read", "arguments": {"path": "README.md"}}],
        context,
    )

    context["_tool_loop_chain"].append(
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "README contents",
        }
    )
    context = hooks.on_tool_result(
        "admin_work",
        {
            "tool_call_id": "call-1",
            "name": "read",
            "arguments": {"path": "README.md"},
            "content": "README contents",
            "is_error": False,
        },
        context,
    )

    context["_tool_loop_chain"].append({"role": "assistant", "content": "Done. I checked it."})
    context["result"] = "Done. I checked it."
    context = asyncio.run(hooks.on_action("post_result", context))

    files = sorted(history_dir.glob("*_admin_chan-1.jsonl"))
    assert len(files) == 1

    lines = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [entry["type"] for entry in lines] == ["message", "tool_call", "tool_response", "message"]

    assert lines[0]["role"] == "user"
    assert "alice: please inspect logs" in lines[0]["content"]

    assert lines[1]["role"] == "assistant"
    assert lines[1]["tool_calls"][0]["name"] == "read"

    assert lines[2]["role"] == "assistant"
    assert lines[2]["type"] == "tool_response"
    assert lines[2]["content"] == "README contents"

    assert lines[3]["role"] == "assistant"
    assert lines[3]["content"] == "Done. I checked it."

    assert all(isinstance(entry.get("ts"), int) for entry in lines)
