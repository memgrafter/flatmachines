"""Tests for persistence module."""

import json
from datetime import datetime, timezone

import pytest

from flatmachines.persistence import _parse_iso, SQLiteCheckpointBackend


class TestParseIso:
    """Covers null, valid UTC, naive, invalid, and edge cases."""

    @pytest.mark.parametrize("val", [None, ""])
    def test_nullish(self, val):
        """Null or empty input returns None."""
        assert _parse_iso(val) is None

    def test_utc_zulu(self):
        """'Z' suffix is replaced with +00:00 and parsed as UTC."""
        result = _parse_iso("2025-06-01T12:00:00Z")
        assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_utc_plus_zero(self):
        """Explicit +00:00 offset returns UTC."""
        result = _parse_iso("2025-06-01T12:00:00+00:00")
        assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_positive_offset(self):
        """Positive offset is converted to UTC."""
        result = _parse_iso("2025-06-01T14:00:00+02:00")
        assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_negative_offset(self):
        """Negative offset is converted to UTC."""
        result = _parse_iso("2025-06-01T08:00:00-04:00")
        assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_naive_datetime(self):
        """Naive datetime (no tzinfo) is assumed UTC."""
        result = _parse_iso("2025-06-01T12:00:00")
        assert result == datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert result.tzinfo is timezone.utc

    def test_midnight(self):
        """Midnight edge case."""
        result = _parse_iso("2025-01-01T00:00:00Z")
        assert result == datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_with_microseconds(self):
        """Microsecond precision preserved."""
        result = _parse_iso("2025-06-01T12:00:00.123456Z")
        assert result == datetime(2025, 6, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)

    def test_invalid_string(self):
        """Garbage string returns None."""
        assert _parse_iso("not-a-date") is None

    def test_garbled_prefix(self):
        """Partially date-like but invalid returns None."""
        assert _parse_iso("2025-99-01T12:00:00") is None

    def test_random_gibberish(self):
        """Complete gibberish returns None."""
        assert _parse_iso("xyz") is None


class TestSQLiteCheckpointCreatedAt:
    """Verify created_at is stored verbatim (no datetime round-trip)."""

    @pytest.mark.asyncio
    async def test_created_at_stored_verbatim(self, tmp_path):
        """A snapshot's created_at is stored exactly as-provided."""
        db_path = str(tmp_path / "test.db")
        backend = SQLiteCheckpointBackend(db_path)

        execution_id = "test-exec-001"
        key = f"{execution_id}/step_000001_test.json"
        created_at = "2026-05-31T12:34:56.789000+00:00"

        value = json.dumps({
            "execution_id": execution_id,
            "machine_name": "test-machine",
            "created_at": created_at,
        }).encode("utf-8")

        await backend.save(key, value)

        row = backend._conn.execute(
            "SELECT created_at FROM machine_checkpoints WHERE checkpoint_key = ?",
            (key,),
        ).fetchone()

        assert row is not None
        assert row["created_at"] == created_at

    @pytest.mark.asyncio
    async def test_created_at_default_when_missing(self, tmp_path):
        """When snapshot lacks created_at, _utc_now_iso() is used as fallback."""
        db_path = str(tmp_path / "test.db")
        backend = SQLiteCheckpointBackend(db_path)

        execution_id = "test-exec-002"
        key = f"{execution_id}/step_000001_test.json"

        value = json.dumps({
            "execution_id": execution_id,
            "machine_name": "test-machine",
            # no created_at key
        }).encode("utf-8")

        await backend.save(key, value)

        row = backend._conn.execute(
            "SELECT created_at FROM machine_checkpoints WHERE checkpoint_key = ?",
            (key,),
        ).fetchone()

        assert row is not None
        assert row["created_at"] is not None
        assert row["created_at"].endswith("+00:00")

    @pytest.mark.asyncio
    async def test_created_at_does_not_mutate_on_round_trip(self, tmp_path):
        """Z suffix and non-UTC offsets are stored exactly as-given (no normalization)."""
        db_path = str(tmp_path / "test.db")
        backend = SQLiteCheckpointBackend(db_path)

        variants = [
            ("2026-05-31T12:00:00Z", "2026-05-31T12:00:00Z"),
            ("2026-05-31T14:00:00+02:00", "2026-05-31T14:00:00+02:00"),
            ("2026-05-31T08:00:00-04:00", "2026-05-31T08:00:00-04:00"),
            ("2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        ]
        execution_id = "test-exec-003"

        for idx, (created_at, expected) in enumerate(variants):
            key = f"{execution_id}/step_{idx:06d}_test.json"
            value = json.dumps({
                "execution_id": execution_id,
                "machine_name": "test-machine",
                "created_at": created_at,
            }).encode("utf-8")

            await backend.save(key, value)

            row = backend._conn.execute(
                "SELECT created_at FROM machine_checkpoints WHERE checkpoint_key = ?",
                (key,),
            ).fetchone()
            assert row is not None
            assert row["created_at"] == expected, (
                f"Expected '{expected}', got '{row['created_at']}'"
            )
