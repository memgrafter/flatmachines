from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class TelemetryPaths:
    root: Path
    events_file: Path


class TelemetryLogger:
    """Tiny JSONL telemetry logger for this example.

    - `log_event(...)` appends structured events to `<role>_events.jsonl`
    - `write_text(...)` and `write_json(...)` persist snapshots/artifacts
    """

    def __init__(self, root_dir: str | Path, *, role: str):
        self.root = Path(root_dir)
        self.role = role
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_file = self.root / f"{role}_events.jsonl"

    def log_event(self, event: str, **data: Any) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": self.role,
            "event": event,
            **data,
        }
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")

    def write_text(self, relative_path: str | Path, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, relative_path: str | Path, payload: Any) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path


def make_run_telemetry_dir(base_dir: str | Path | None = None) -> Path:
    """Create and return a run telemetry directory.

    Resolution order:
    1) explicit `base_dir`
    2) env `CLONE_MACHINE_TELEMETRY_DIR`
    3) `<python_root>/.telemetry`
    """
    if base_dir is not None:
        root = Path(base_dir)
    else:
        env = os.getenv("CLONE_MACHINE_TELEMETRY_DIR")
        if env:
            root = Path(env)
        else:
            root = Path(__file__).resolve().parents[2] / ".telemetry"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = uuid.uuid4().hex[:8]
    run_root = root / f"clone_machine_run_{stamp}_{run_id}"
    run_root.mkdir(parents=True, exist_ok=True)
    return run_root
