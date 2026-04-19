from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .messages_backend import QueueMessage, SQLiteMessageBackend


@dataclass
class ConversationBuffer:
    conversation_key: str
    source_message_ids: list[int] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    deadline: float = 0.0


class DebounceService:
    def __init__(
        self,
        *,
        backend: SQLiteMessageBackend,
        input_queue: str = "discord_incoming",
        output_queue: str = "discord_debounced",
        worker_id: str = "debouncer",
        debounce_seconds: float = 5.0,
        poll_seconds: float = 0.5,
        lease_seconds: float = 60.0,
        lease_limit: int = 100,
    ):
        self.backend = backend
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.worker_id = worker_id
        self.debounce_seconds = debounce_seconds
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.lease_limit = lease_limit
        self._buffers: dict[str, ConversationBuffer] = {}

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                self.process_once()
            except Exception as exc:
                print(f"[debounce] error: {exc}", flush=True)
            await asyncio.sleep(self.poll_seconds)

        # Flush pending buffers on shutdown so nothing is stranded.
        self._flush_due(now=float("inf"))

    def process_once(self, now: float | None = None) -> int:
        t = time.time() if now is None else float(now)

        leased = self.backend.lease(
            queue=self.input_queue,
            worker_id=self.worker_id,
            limit=self.lease_limit,
            lease_seconds=self.lease_seconds,
            now=t,
        )

        for message in leased:
            self._ingest(message, now=t)

        return self._flush_due(now=t)

    def _ingest(self, message: QueueMessage, now: float) -> None:
        key = message.conversation_key or "default"
        buffer = self._buffers.get(key)
        if buffer is None:
            buffer = ConversationBuffer(conversation_key=key)
            self._buffers[key] = buffer

        buffer.source_message_ids.append(message.id)
        buffer.events.append(message.payload)
        buffer.deadline = now + self.debounce_seconds

    def _flush_due(self, now: float) -> int:
        due_keys = [
            key
            for key, buffer in self._buffers.items()
            if buffer.source_message_ids and buffer.deadline <= now
        ]

        flushed = 0
        for key in due_keys:
            buffer = self._buffers[key]
            payload = build_batch_payload(buffer)
            source_ids = list(buffer.source_message_ids)
            dedupe_key = (
                f"debounce:{key}:"
                f"{payload['first_message_id']}:{payload['last_message_id']}:{payload['message_count']}"
            )

            self.backend.enqueue(
                queue=self.output_queue,
                conversation_key=key,
                payload=payload,
                dedupe_key=dedupe_key,
                now=now,
            )
            self.backend.ack(source_ids, now=now)
            flushed += 1
            del self._buffers[key]

        return flushed


def build_batch_payload(buffer: ConversationBuffer) -> dict[str, Any]:
    first_message_id = ""
    last_message_id = ""

    if buffer.events:
        first_message_id = str(buffer.events[0].get("message_id", ""))
        last_message_id = str(buffer.events[-1].get("message_id", ""))

    return {
        "conversation_key": buffer.conversation_key,
        "message_count": len(buffer.events),
        "messages": list(buffer.events),
        "first_message_id": first_message_id,
        "last_message_id": last_message_id,
        "source_queue_message_ids": list(buffer.source_message_ids),
    }
