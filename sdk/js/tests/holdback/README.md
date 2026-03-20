# Python SDK Holdback Parity Snapshot

This holdback suite snapshots the Python SDK test inventory at:

- `2026-03-20T08:38:22`
- source: `sdk/python/tests`
- total tests: `824`

## Files

- `python-sdk-tests-manifest.json` — canonical test inventory (file + test names)
- `python-sdk-parity.test.ts` — Vitest suite that:
  - validates manifest integrity (count + uniqueness)
  - exposes one `it.todo(...)` per Python test case

## Regenerating the manifest

From repo root:

```bash
python3 - <<'PY'
import ast, json, pathlib
root=pathlib.Path('sdk/python/tests')