from __future__ import annotations

import asyncio
import json
from typing import Any, Optional, Protocol

from .discord_api import DiscordAPI
from .messages_backend import SQLiteMessageBackend


class BatchResponder(Protocol):
    async def compose_reply(self, batch: dict[str, Any]) -> Optional[str]:
        ...


class EchoBatchResponder:
    async def compose_reply(self, batch: dict[str, Any]) -> Optional[str]:
        messages = batch.get("messages")
        if not isinstance(messages, list) or not messages:
            return "No messages found in batch."

        rows: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                rows.append(str(message))
                continue

            author_name = str(message.get("author_name") or message.get("author_id") or "unknown")
            content = str(message.get("content", ""))
            if content:
                rows.append(f"{author_name}: {content}")
            else:
                rows.append(f"{author_name}: <non-text message>")

        if len(rows) == 1:
            return f"Thanks — I got your message:\n{rows[0]}"

        bullet_rows = "\n".join(f"- {row}" for row in rows)
        return f"I saw {len(rows)} queued messages:\n{bullet_rows}"


class FlatMachineBatchResponder:
    """Optional responder that routes debounced batches into a FlatMachine."""

    def __init__(
        self,
        *,
        machine_config: str,
        profiles_file: str | None = None,
        output_key: str = "response",
    ):
        self.machine_config = machine_config
        self.profiles_file = profiles_file
        self.output_key = output_key
        self._machine = None

    async def compose_reply(self, batch: dict[str, Any]) -> Optional[str]:
        if self._machine is None:
            from flatmachines import FlatMachine

            self._machine = FlatMachine(
                config_file=self.machine_config,
                profiles_file=self.profiles_file,
            )

        result = await self._machine.execute(
            input={
                "batch": batch,
                "messages": batch.get("messages", []),
                "conversation_key": batch.get("conversation_key"),
            }
        )

        if isinstance(result, dict):
            if self.output_key in result:
                return str(result[self.output_key])
            if "content" in result:
                return str(result["content"])

        return json.dumps(result, indent=2, default=str)


class DiscordResponderService:
    def __init__(
        self,
        *,
        backend: SQLiteMessageBackend,
        api: DiscordAPI,
        responder: BatchResponder,
        input_queue: str = "discord_debounced",
        worker_id: str = "responder",
        lease_seconds: float = 120.0,
        lease_limit: int = 10,
        poll_seconds: float = 1.0,
        retry_delay_seconds: float = 3.0,
    ):
        self.backend = backend
        self.api = api
        self.responder = responder
        self.input_queue = input_queue
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.lease_limit = lease_limit
        self.poll_seconds = poll_seconds
        self.retry_delay_seconds = retry_delay_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.process_once()
            except Exception as exc:
                print(f"[respond] error: {exc}", flush=True)
            await asyncio.sleep(self.poll_seconds)

    async def process_once(self) -> int:
        leased = self.backend.lease(
            queue=self.input_queue,
            worker_id=self.worker_id,
            limit=self.lease_limit,
            lease_seconds=self.lease_seconds,
        )

        processed = 0
        for message in leased:
            try:
                reply = await self.responder.compose_reply(message.payload)
                if reply is not None and str(reply).strip() != "":
                    for chunk in split_discord_message(str(reply), max_chars=2000):
                        await asyncio.to_thread(self.api.post_channel_message, chunk)
                self.backend.ack([message.id])
                processed += 1
            except Exception as exc:
                print(f"[respond] failed message_id={message.id}: {exc}", flush=True)

                if is_non_retryable_quota_error(exc):
                    cancelled = self.backend.ack_conversation(
                        queue=self.input_queue,
                        conversation_key=message.conversation_key,
                    )
                    print(
                        "[respond] cancelled queued conversation after quota error "
                        f"conversation={message.conversation_key} cancelled={cancelled}",
                        flush=True,
                    )
                    continue

                self.backend.nack(message.id, delay_seconds=self.retry_delay_seconds)

        return processed


def is_non_retryable_quota_error(exc: Exception) -> bool:
    """Detect provider-side quota exhaustion where retries should be cancelled."""
    text = str(exc).lower()
    patterns = (
        "insufficient_quota",
        "out of quota",
        "exceeded your current quota",
        "billing hard limit",
        "status=402",
        "status=403",
    )
    if any(pattern in text for pattern in patterns):
        return True

    # Some providers return quota exhaustion under HTTP 429.
    if "status=429" in text and "quota" in text:
        return True

    return False


def split_discord_message(content: str, max_chars: int = 2000) -> list[str]:
    """Split long output into Discord-safe chunks without dropping content."""
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    if len(content) <= max_chars:
        return [content]

    parts: list[str] = []
    start = 0
    while start < len(content):
        end = min(len(content), start + max_chars)

        # Prefer newline boundary when possible.
        if end < len(content):
            newline = content.rfind("\n", start, end)
            if newline > start:
                end = newline + 1

        part = content[start:end]
        parts.append(part)
        start = end

    return parts
