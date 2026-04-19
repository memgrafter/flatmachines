from __future__ import annotations

import asyncio
from typing import Optional

from .discord_api import DiscordAPI
from .messages_backend import SQLiteMessageBackend


class DiscordIngressService:
    def __init__(
        self,
        *,
        backend: SQLiteMessageBackend,
        api: DiscordAPI,
        input_queue: str = "discord_incoming",
        cursor_state_key: str = "discord:last_seen_message_id",
        poll_seconds: float = 2.0,
        fetch_limit: int = 50,
        backfill_on_first_run: bool = False,
    ):
        self.backend = backend
        self.api = api
        self.input_queue = input_queue
        self.cursor_state_key = cursor_state_key
        self.poll_seconds = poll_seconds
        self.fetch_limit = fetch_limit
        self.backfill_on_first_run = backfill_on_first_run

    async def run(self, stop_event: asyncio.Event) -> None:
        me = await asyncio.to_thread(self.api.get_current_user)
        me_id = str(me.get("id", ""))

        while not stop_event.is_set():
            try:
                await self.process_once(me_id=me_id)
            except Exception as exc:
                print(f"[ingress] error: {exc}", flush=True)
            await asyncio.sleep(self.poll_seconds)

    async def process_once(self, *, me_id: Optional[str] = None) -> int:
        if me_id is None:
            me = await asyncio.to_thread(self.api.get_current_user)
            me_id = str(me.get("id", ""))

        last_seen = self.backend.get_state(self.cursor_state_key)
        messages = await asyncio.to_thread(self.api.list_channel_messages, limit=self.fetch_limit)

        # Default behavior: do not backfill history on first run.
        if last_seen is None and not self.backfill_on_first_run:
            newest = _newest_message_id(messages)
            if newest is not None:
                self.backend.set_state(self.cursor_state_key, newest)
            return 0

        enqueued_count = 0
        newest_seen = last_seen

        for message in reversed(messages):
            message_id = str(message.get("id", ""))
            if not message_id:
                continue

            if last_seen is not None and _snowflake_lte(message_id, last_seen):
                continue

            author = message.get("author") or {}
            author_id = str(author.get("id", ""))
            is_bot = bool(author.get("bot", False))
            if is_bot or (me_id and author_id == me_id):
                newest_seen = _max_snowflake(newest_seen, message_id)
                continue

            # Ignore empty-content records unless they carry structured payload.
            if not _is_message_actionable(message):
                newest_seen = _max_snowflake(newest_seen, message_id)
                continue

            payload = {
                "message_id": message_id,
                "channel_id": str(message.get("channel_id", self.api.channel_id)),
                "author_id": author_id,
                "author_name": str(author.get("username", "")),
                "content": str(message.get("content", "")),
                "timestamp": message.get("timestamp"),
                "raw": message,
            }

            dedupe_key = f"discord:{self.api.channel_id}:{message_id}"
            inserted = self.backend.enqueue(
                queue=self.input_queue,
                conversation_key=payload["channel_id"],
                payload=payload,
                dedupe_key=dedupe_key,
            )
            if inserted is not None:
                enqueued_count += 1

            newest_seen = _max_snowflake(newest_seen, message_id)

        if newest_seen is not None:
            self.backend.set_state(self.cursor_state_key, newest_seen)

        return enqueued_count


def _is_message_actionable(message: dict) -> bool:
    content = str(message.get("content", "")).strip()
    if content:
        return True

    attachments = message.get("attachments")
    embeds = message.get("embeds")
    components = message.get("components")

    if isinstance(attachments, list) and len(attachments) > 0:
        return True
    if isinstance(embeds, list) and len(embeds) > 0:
        return True
    if isinstance(components, list) and len(components) > 0:
        return True

    return False


def _newest_message_id(messages: list[dict]) -> Optional[str]:
    newest: Optional[str] = None
    for message in messages:
        message_id = str(message.get("id", ""))
        if not message_id:
            continue
        newest = _max_snowflake(newest, message_id)
    return newest


def _snowflake_lte(left: str, right: str) -> bool:
    try:
        return int(left) <= int(right)
    except ValueError:
        return left <= right


def _max_snowflake(a: Optional[str], b: str) -> str:
    if a is None:
        return b
    try:
        return b if int(b) > int(a) else a
    except ValueError:
        return b if b > a else a
