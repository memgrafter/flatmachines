---
id: ftj-6dgd
status: closed
deps: []
links: []
created: 2026-06-01T03:10:16Z
type: chore
priority: 3
assignee: memgrafter
---
# _parse_iso is overwrought — dead branches and unnecessary generality

The `_parse_iso` function in persistence.py tries to be a general-purpose ISO-8601 parser when it only ever handles our own output format. Three of its four code paths are dead for internal data.

**Issue**: The function has four branches, three of which never fire for data written by our own `_utc_now_iso()`:

1. `isinstance(ts, str)` check (line 983) — Redundant. The type annotation is `Optional[str]` and the `if not ts` guard on line 980 already ensures a non-empty string. `ts.replace("Z", ...)` would fail on a non-string anyway, so this guard saves nothing.

2. `Z` → `+00:00` replace (line 983) — `_utc_now_iso()` produces `datetime.now(timezone.utc).isoformat()` which always yields `+00:00`, never `Z`. This is a dead path for our own data.

3. `astimezone(timezone.utc)` on line 988 — Only fires if the parsed datetime has a non-UTC tzinfo. But we only ever write `+00:00` datetimes, and `replace(tzinfo=timezone.utc)` on line 986 already handles naive datetimes. So this branch catches a case we never produce.

4. The actual work path — lines 980-987 excluding the dead branches — is: guard null, `fromisoformat`, catch errors, handle naive. That's the only path that matters.

**Recommendation**: Either simplify to just the live paths, or add comments explaining which branches exist for external data resilience and why.

**File**: `sdk/python/flatmachines/flatmachines/persistence.py:979-989`
