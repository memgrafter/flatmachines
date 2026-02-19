from __future__ import annotations

import json
from pathlib import Path

from rlm_v2.trace import TraceRecorder, normalize_inspect_level, parse_tag_items


def test_trace_recorder_writes_event_and_manifest(tmp_path: Path) -> None:
    recorder = TraceRecorder(trace_dir=tmp_path, run_id="run-1")
    recorder.write_manifest({"hello": "world"})
    recorder.append_event("run_start", depth=0)
    recorder.append_event("run_end", depth=0, reason="final")

    manifest_path = tmp_path / "run-1" / "manifest.json"
    events_path = tmp_path / "run-1" / "events.jsonl"

    assert manifest_path.exists()
    assert events_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["run_id"] == "run-1"
    assert manifest["hello"] == "world"

    lines = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["event"] == "run_start"
    assert lines[0]["run_id"] == "run-1"
    assert "timestamp" in lines[0]
    assert lines[1]["event"] == "run_end"


def test_parse_tags_and_normalize_inspect_level() -> None:
    tags = parse_tag_items(["exp=alpha", "foo=bar", "badtag"])
    assert tags == {"exp": "alpha", "foo": "bar"}

    assert normalize_inspect_level("summary") == "summary"
    assert normalize_inspect_level("full") == "full"
    assert normalize_inspect_level("weird") == "summary"
