from __future__ import annotations

from tool_use_discord.messages_backend import SQLiteMessageBackend


def test_enqueue_lease_ack(tmp_path):
    db_path = tmp_path / "queue.sqlite"
    backend = SQLiteMessageBackend(str(db_path))

    message_id = backend.enqueue(
        queue="incoming",
        conversation_key="chan-1",
        payload={"text": "hello"},
        dedupe_key="m1",
        now=10,
    )
    assert isinstance(message_id, int)

    duplicate = backend.enqueue(
        queue="incoming",
        conversation_key="chan-1",
        payload={"text": "hello"},
        dedupe_key="m1",
        now=10,
    )
    assert duplicate is None

    leased = backend.lease(
        queue="incoming",
        worker_id="worker-a",
        limit=10,
        lease_seconds=30,
        now=11,
    )
    assert len(leased) == 1
    assert leased[0].id == message_id
    assert leased[0].payload["text"] == "hello"

    acked = backend.ack([message_id], now=12)
    assert acked == 1

    leased_again = backend.lease(
        queue="incoming",
        worker_id="worker-a",
        limit=10,
        lease_seconds=30,
        now=13,
    )
    assert leased_again == []


def test_lease_expiry_and_nack(tmp_path):
    db_path = tmp_path / "queue.sqlite"
    backend = SQLiteMessageBackend(str(db_path))

    message_id = backend.enqueue(
        queue="incoming",
        conversation_key="chan-1",
        payload={"text": "retry"},
        now=100,
    )
    assert isinstance(message_id, int)

    leased = backend.lease(
        queue="incoming",
        worker_id="worker-a",
        limit=1,
        lease_seconds=5,
        now=101,
    )
    assert len(leased) == 1

    still_leased = backend.lease(
        queue="incoming",
        worker_id="worker-b",
        limit=1,
        lease_seconds=5,
        now=104,
    )
    assert still_leased == []

    re_leased = backend.lease(
        queue="incoming",
        worker_id="worker-b",
        limit=1,
        lease_seconds=5,
        now=107,
    )
    assert len(re_leased) == 1
    assert re_leased[0].attempts == 2

    backend.nack(message_id, delay_seconds=10, now=108)
    not_ready = backend.lease(
        queue="incoming",
        worker_id="worker-c",
        limit=1,
        lease_seconds=5,
        now=117,
    )
    assert not_ready == []

    ready = backend.lease(
        queue="incoming",
        worker_id="worker-c",
        limit=1,
        lease_seconds=5,
        now=118,
    )
    assert len(ready) == 1


def test_state_roundtrip(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))
    assert backend.get_state("cursor") is None

    backend.set_state("cursor", "12345", now=1)
    assert backend.get_state("cursor") == "12345"

    backend.set_state("cursor", "12346", now=2)
    assert backend.get_state("cursor") == "12346"


def test_discord_user_admin_mapping(tmp_path):
    backend = SQLiteMessageBackend(str(tmp_path / "queue.sqlite"))

    assert backend.is_discord_user_admin("u1") is False

    backend.upsert_discord_user(user_id="u1", username="trent", is_admin=True, now=1)
    assert backend.is_discord_user_admin("u1") is True

    backend.upsert_discord_user(user_id="u1", username="trent", is_admin=False, now=2)
    assert backend.is_discord_user_admin("u1") is False
