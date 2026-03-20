# Parity Tests

JS SDK parity coverage against the Python SDK test manifest (824 cases).

## Running tests

```bash
# Run all parity tests
bash test.sh

# Run a single suite
bash test.sh signals-core.parity.test.ts

# Run from repo root (equivalent)
cd sdk/js && npx vitest run tests/parity/
```

**Important:** Always use `vitest run` (not `vitest` alone — that enters
watch mode and never exits).

## Structure

Each `*.parity.test.ts` file covers a topical slice of the Python manifest.
Case ownership is tracked in `../helpers/parity/test-matrix.ts`.
