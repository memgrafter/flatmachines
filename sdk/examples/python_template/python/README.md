# Python Template

FlatMachines template project with sequence + fan-out (map-reduce) workflow and SQLite persistence.

## Workflow

```
start -> classify_first -> analyze_all (foreach) -> done
                              |
                     per-doc sub-machine:
                   classify -> summarize -> extract -> aggregate
```

## Features

- Sequential state transitions
- `foreach` dynamic parallelism (processes N documents in parallel)
- SQLite persistence (`SQLiteCheckpointBackend`, `SQLiteLeaseLock`, `SQLiteConfigStore`)
- Mock LLM provider for testing without API keys
- LiteLLM backend with model profiles

## Quick Start

```bash
# Run with mock backend (no API key needed)
./run.sh --local --mock

# Run with real LLM (requires OPENAI_API_KEY)
./run.sh --local

# Run tests
.venv/bin/python -m pytest tests/ -v
```

## Files

```
config/
  machine.yml          # Main machine: sequence + foreach
  analyze_machine.yml  # Per-doc sub-machine: classify + summarize + extract + aggregate
  classify_agent.yml   # Document classifier agent
  summarize_agent.yml  # Document summarizer agent
  extract_agent.yml    # Entity extractor agent
  aggregate_agent.yml  # Report aggregator agent
  profiles.yml         # Model profiles (litellm)
python/
  src/python_template/
    main.py            # Entry point
    mock_provider.py   # Mock LLM backend (patches litellm.acompletion)
  tests/
    test_mock_provider.py   # Unit tests for mock provider
    test_template_run.py    # Integration test (full machine run)
  run.sh               # Setup + run script
  pyproject.toml
```
