---
id: ftj-3adc
status: closed
deps: []
links: []
created: 2026-06-01T03:10:16Z
type: chore
priority: 4
assignee: memgrafter
---
# Extract datetime.min.replace(tzinfo=timezone.utc) as module-level constant

The sentinel value `datetime.min.replace(tzinfo=timezone.utc)` appears 7 times across `persistence.py`, mostly in `MemoryBackend.prune()` where it appears 5 times in ~25 lines.

**Occurrences**:
- `persistence.py:452` — MemoryBackend.prune fallback (no latest pointer)
- `persistence.py:457` — MemoryBackend.prune fallback (no snapshot data)
- `persistence.py:463` — MemoryBackend.prune fallback (corrupt snapshot)
- `persistence.py:467` — MemoryBackend.prune fallback (non-dict snapshot)
- `persistence.py:469` — MemoryBackend.prune fallback (`_parse_iso` returned None)
- `persistence.py:908` — SQLiteCheckpointBackend.prune fallback (per row)
- `persistence.py:910` — SQLiteCheckpointBackend.prune initial value for `executions.get()`

Each call does `datetime.min.replace(tzinfo=timezone.utc)` — the same operation every time. In `MemoryBackend.prune()` this repetition visually drowns out the actual logic: 5 fallback cases are hard to scan because the sentinel dominates the line.

**Recommendation**: Extract as a module-level constant:
```python
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
```

**File**: `sdk/python/flatmachines/flatmachines/persistence.py` (7 locations)
