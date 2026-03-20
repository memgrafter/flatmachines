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
import ast
import json
import pathlib
from datetime import datetime, timezone

root = pathlib.Path('sdk/python/tests')
files = []

def discover_tests(path: pathlib.Path):
    module = ast.parse(path.read_text(encoding='utf-8'))
    tests = []

    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
            tests.append(node.name)
        elif isinstance(node, ast.ClassDef):
            methods = [
                f"{node.name}.{member.name}"
                for member in node.body
                if isinstance(member, ast.FunctionDef) and member.name.startswith('test_')
            ]
            tests.extend(methods)

    return tests

for path in sorted(root.rglob('test_*.py')):
    tests = discover_tests(path)
    if tests:
        files.append({
            'file': path.as_posix(),
            'tests': tests,
        })

total = sum(len(item['tests']) for item in files)
manifest = {
    'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    'source_root': root.as_posix(),
    'total_tests': total,
    'files': files,
}

out = pathlib.Path('sdk/js/tests/holdback/python-sdk-tests-manifest.json')
out.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(f"wrote {out} with {total} tests")
PY
```

Then run:

```bash
cd sdk/js
npm test -- tests/holdback/python-sdk-parity.test.ts
```
