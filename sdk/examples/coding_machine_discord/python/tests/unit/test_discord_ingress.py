from __future__ import annotations

import asyncio

from tool_use_discord.discord_ingress import DiscordIngressService
from tool_use_discord.messages_backend import SQLiteMessageBackend


class _FakeDiscordAPI:
    def __init__(self, channel_id: str, messages: list[dict]):
        self.channel_id = channel_id
        self._messages = messages

    def get_current_user(self) -> dict:
        return {"id": "bot-id"}

    def list_channel_messages(self, *, limit: int = 50) -> list[dict]:
        return self._messages[:limit]


def _message(message_id: str, *, content: str = "", author_id: str = "user-1", bot: bool = False, attachments=None, embeds=None, components=None):
    return {
        "id": message_id,
        "channel_id": "chan-1",
        "author": {
            "id": author_id,
            "username": "trent",
            "bot": bot,
        },
        "content": content,
        "attachments": [] if attachments is None else attachments,
        "embeds": [] if embeds is None else embeds,
        "components": [] if components is None else components,
        "timestamp": "2026-01-01T00:00:00.000000+00:00",
    }


def test_bootstrap_cursor_no_backfill(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    api = _FakeDiscordAPI(
        channel_id="chan-1",
        messages=[
            _message("200", content="new"),
            _message("100", content="old"),
        ],
    )

    service = DiscordIngressService(
        backend=backend,
        api=api,
        backfill_on_first_run=False,
    )

    enqueued = asyncio.run(service.process_once(me_id="bot-id"))
    assert enqueued == 0
    assert backend.get_state("discord:last_seen_message_id") == "200"

    leased = backend.lease(
        queue="discord_incoming",
        worker_id="test",
        limit=10,
        lease_seconds=10,
    )
    assert leased == []


def test_backfill_on_first_run_optional_flag(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    api = _FakeDiscordAPI(
        channel_id="chan-1",
        messages=[
            _message("200", content="new"),
            _message("100", content="old"),
        ],
    )

    service = DiscordIngressService(
        backend=backend,
        api=api,
        backfill_on_first_run=True,
    )

    enqueued = asyncio.run(service.process_once(me_id="bot-id"))
    assert enqueued == 2

    leased = backend.lease(
        queue="discord_incoming",
        worker_id="test",
        limit=10,
        lease_seconds=10,
    )
    assert len(leased) == 2


def test_ignores_empty_content_without_structured_payload(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    backend.set_state("discord:last_seen_message_id", "0")

    api = _FakeDiscordAPI(
        channel_id="chan-1",
        messages=[
            _message("300", content="", attachments=[], embeds=[], components=[]),
            _message("301", content="", attachments=[{"id": "a1"}]),
        ],
    )

    service = DiscordIngressService(backend=backend, api=api)
    enqueued = asyncio.run(service.process_once(me_id="bot-id"))

    assert enqueued == 1
    assert backend.get_state("discord:last_seen_message_id") == "301"

    leased = backend.lease(
        queue="discord_incoming",
        worker_id="test",
        limit=10,
        lease_seconds=10,
    )
    assert len(leased) == 1
    assert leased[0].payload["message_id"] == "301"
