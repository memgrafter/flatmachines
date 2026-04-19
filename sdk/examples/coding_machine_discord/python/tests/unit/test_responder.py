from __future__ import annotations

import asyncio

from tool_use_discord.messages_backend import SQLiteMessageBackend
from tool_use_discord.responder import (
    DiscordResponderService,
    is_non_retryable_quota_error,
    split_discord_message,
)


class _DummyAPI:
    def post_channel_message(self, content: str) -> dict[str, str]:
        return {"content": content}


class _AlwaysErrorResponder:
    def __init__(self, message: str):
        self.message = message

    async def compose_reply(self, batch: dict[str, object]) -> str:
        raise RuntimeError(self.message)


def test_split_discord_message_no_truncation():
    text = "line1\nline2\n" + ("x" * 2100)
    chunks = split_discord_message(text, max_chars=2000)

    assert len(chunks) >= 2
    assert "".join(chunks) == text
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_quota_error_cancels_conversation_backlog(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    backend.enqueue(
        queue="discord_debounced",
        conversation_key="chan-1",
        payload={"messages": [{"content": "hello"}]},
    )
    backend.enqueue(
        queue="discord_debounced",
        conversation_key="chan-1",
        payload={"messages": [{"content": "hello again"}]},
    )

    service = DiscordResponderService(
        backend=backend,
        api=_DummyAPI(),
        responder=_AlwaysErrorResponder("status=429 insufficient_quota"),
        input_queue="discord_debounced",
        lease_limit=1,
    )

    processed = asyncio.run(service.process_once())
    assert processed == 0

    counts = backend.queue_counts()["discord_debounced"]
    assert counts["active"] == 0
    assert counts["acked"] == 2


def test_transient_error_is_retried(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    backend.enqueue(
        queue="discord_debounced",
        conversation_key="chan-1",
        payload={"messages": [{"content": "hello"}]},
    )

    service = DiscordResponderService(
        backend=backend,
        api=_DummyAPI(),
        responder=_AlwaysErrorResponder("network timeout"),
        input_queue="discord_debounced",
        lease_limit=1,
    )

    processed = asyncio.run(service.process_once())
    assert processed == 0

    counts = backend.queue_counts()["discord_debounced"]
    assert counts["active"] == 1
    assert counts["acked"] == 0


def test_is_non_retryable_quota_error():
    assert is_non_retryable_quota_error(RuntimeError("insufficient_quota")) is True
    assert is_non_retryable_quota_error(RuntimeError("status=403 quota exceeded")) is True
    assert is_non_retryable_quota_error(RuntimeError("status=429 too many requests")) is False
    assert is_non_retryable_quota_error(RuntimeError("socket timeout")) is False
