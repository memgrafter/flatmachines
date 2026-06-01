---
id: ftj-raxi
status: closed
deps: []
links: []
created: 2026-06-01T03:10:16Z
type: chore
priority: 3
assignee: memgrafter
---
# SQLite _upsert_checkpoint has unexplained datetime round-trip

In SQLiteCheckpointBackend._upsert_checkpoint(), the `created_at` column value goes through a parse-then-reformat round-trip without explanation.

**Code** (lines 774-778):
```python
snapshot_created_at = _parse_iso(snapshot.get("created_at"))
if snapshot_created_at is not None:
    created_at = snapshot_created_at.isoformat()
```

**Issue**: The `created_at` value in the snapshot JSON was written by `_utc_now_iso()` which produces `datetime.now(timezone.utc).isoformat()` — already a valid UTC ISO string. Parsing it into a datetime object and formatting it back via `.isoformat()` is a no-op:

- Input: `"2026-05-31T19:02:13.123456+00:00"`
- Parse: `datetime(2026, 5, 31, 19, 2, 13, 123456, tzinfo=timezone.utc)`
- Re-format: `"2026-05-31T19:02:13.123456+00:00"` — identical

If this round-trip exists to normalize timezone offsets (e.g., `Z` → `+00:00` or `-05:00` → `+00:00`) or to handle data from older versions that might have stored naive datetimes, that's valid — but the code doesn't say so. A future reader will wonder why the extra work.

**Recommendation**: Either remove the round-trip or add a comment explaining what normalization it's performing.

**File**: `sdk/python/flatmachines/flatmachines/persistence.py:774-778`
