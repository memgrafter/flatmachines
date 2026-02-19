"""Structured trace utilities for RLM v2 inspect mode."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class TracePaths:
    run_dir: Path
    events_file: Path
    manifest_file: Path


class TraceRecorder:
    """Thread-safe JSONL trace writer keyed by run_id."""

    _global_lock = threading.RLock()
    _file_locks: dict[str, threading.RLock] = {}

    def __init__(self, *, trace_dir: str | Path, run_id: str):
        self.run_id = str(run_id)
        self.trace_dir = Path(trace_dir).expanduser().resolve()
        self.paths = self._build_paths(self.trace_dir, self.run_id)
        self.paths.run_dir.mkdir(parents=True, exist_ok=True)
        self._events_lock = self._get_lock(str(self.paths.events_file))
        self._manifest_lock = self._get_lock(str(self.paths.manifest_file))

    @classmethod
    def _build_paths(cls, trace_dir: Path, run_id: str) -> TracePaths:
        run_dir = trace_dir / run_id
        return TracePaths(
            run_dir=run_dir,
            events_file=run_dir / "events.jsonl",
            manifest_file=run_dir / "manifest.json",
        )

    @classmethod
    def _get_lock(cls, key: str) -> threading.RLock:
        with cls._global_lock:
            lock = cls._file_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._file_locks[key] = lock
            return lock

    def append_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": event_type,
            "run_id": self.run_id,
            "timestamp": utc_now_iso(),
            "ts": time.time(),
        }
        payload.update(fields)

        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._events_lock:
            with self.paths.events_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

        return payload

    def write_manifest(self, manifest: Dict[str, Any]) -> None:
        payload: Dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": utc_now_iso(),
            **manifest,
        }
        with self._manifest_lock:
            with self.paths.manifest_file.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)


def parse_tag_items(items: list[str]) -> dict[str, str]:
    """Parse CLI tag items in key=value format."""
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            out[key] = value
    return out


def normalize_inspect_level(value: str | None) -> str:
    if not value:
        return "summary"
    lowered = value.lower().strip()
    if lowered in {"summary", "full"}:
        return lowered
    return "summary"


__all__ = [
    "TraceRecorder",
    "TracePaths",
    "hash_text",
    "normalize_inspect_level",
    "parse_tag_items",
    "utc_now_iso",
]
