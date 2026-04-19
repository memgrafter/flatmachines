from __future__ import annotations

from tool_use_discord.debounce import DebounceService
from tool_use_discord.messages_backend import SQLiteMessageBackend


def test_debounce_batches_multiple_messages(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))

    backend.enqueue(
        queue="discord_incoming",
        conversation_key="chan-1",
        payload={"message_id": "1", "content": "a"},
        now=0,
    )
    backend.enqueue(
        queue="discord_incoming",
        conversation_key="chan-1",
        payload={"message_id": "2", "content": "b"},
        now=0.2,
    )

    svc = DebounceService(
        backend=backend,
        input_queue="discord_incoming",
        output_queue="discord_debounced",
        debounce_seconds=3.0,
        lease_seconds=10.0,
        poll_seconds=0.1,
    )

    # First pass ingests messages, not yet due.
    flushed = svc.process_once(now=1.0)
    assert flushed == 0

    # After debounce window, batch should flush.
    flushed = svc.process_once(now=5.0)
    assert flushed == 1

    batches = backend.lease(
        queue="discord_debounced",
        worker_id="test",
        limit=10,
        lease_seconds=10,
        now=5.1,
    )
    assert len(batches) == 1
    payload = batches[0].payload
    assert payload["message_count"] == 2
    assert [m["content"] for m in payload["messages"]] == ["a", "b"]
