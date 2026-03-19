# Integration Tests

This directory contains integration tests that require external dependencies or isolated environments.

## Running All Tests

```bash
./run.sh
```

## Test Suites

### metrics/
Tests OpenTelemetry metrics integration with console exporter.

```bash
cd metrics && ./run.sh
```

### claude_code/
Live integration tests for the Claude Code CLI adapter. Requires `claude` binary on PATH and valid auth.

Tests: simple task, tool use, session resume, concurrent sessions, error recovery, permission bypass, tool restrictions, continuation loop, stream event parsing, session holdback, append system prompt, cache metrics.

```bash
cd claude_code && ./run.sh --local
```

## Adding New Tests

1. Create a new directory: `tests/integration/<test-name>/`
2. Add a `run.sh` script that:
   - Sets up any required environment
   - Returns 0 on success, non-zero on failure
3. The main `run.sh` will auto-discover and run it
