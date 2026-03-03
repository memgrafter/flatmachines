# DFSS Deep Sleep Demo

Demonstrates **Depth-First Sparse Scheduling (DFSS)** with the scheduler
itself as a **FlatMachine** using checkpoint-and-exit ("deep sleep").

Between batches the scheduler checkpoints, exits, and uses zero processes.
A signal from a completing task wakes it to schedule the next batch.

## Key Concepts

- **Task Machine** — runs a single task via hook actions, outputs result + children
- **Scheduler Machine** — orchestrates batches: seed → hydrate → pick → claim → dispatch → settle → check → loop/sleep/done
- **DeepSleepHooks** — implements all actions (durable work lifecycle, scoring, retry/poison, signals)
- **Scoring parity** — scheduler scoring is kept isomorphic with `examples/dfss_pipeline/scheduler.py`
- **Durable backends** — SQLite for work pool, checkpoints, and signals

## Behavior (isomorphic with dfss_pipeline)

- Prefer admitted roots (saturation)
- Prefer deeper work (DFS)
- Prefer roots near completion
- Boost scarce `slow` resource tasks
- Boost cheap predecessors that unlock expensive descendants
- Retry on transient failures, terminal-fail after max attempts
- Resource gates (slow gate toggles open/closed)
- Resume after interruption

## Prerequisites

Python 3.10+ and `uv` package manager.

## Quick Start

```bash
# Run with local SDK sources
./python/run.sh --local

# Pass scheduler args
./python/run.sh --local --roots 8 --max-depth 3 --fail-rate 0.15 --seed 7

# Deterministic (no failures)
./python/run.sh --local --roots 6 --max-depth 3 --fail-rate 0 --seed 7

# Resume interrupted work
./python/run.sh --local --resume --db-path data/dfss.sqlite

# Resume + cleanup completed checkpoints
./python/run.sh --local --resume --cleanup --db-path data/dfss.sqlite
```

## CLI Arguments

| Arg | Default | Description |
|-----|---------|-------------|
| `--roots` | 8 | Number of root tasks |
| `--max-depth` | 3 | Maximum tree depth |
| `--max-workers` | 4 | (reserved for future use) |
| `--max-active-roots` | 3 | Max roots admitted simultaneously |
| `--max-attempts` | 3 | Retries before terminal failure |
| `--batch-size` | 4 | Tasks per dispatch batch |
| `--fail-rate` | 0.15 | Transient failure probability |
| `--gate-interval` | 0.8 | Seconds between slow gate toggles |
| `--seed` | 7 | RNG seed for reproducibility |
| `--db-path` | data/dfss.sqlite | SQLite database path |
| `--resume` | false | Resume from checkpoint |
| `--cleanup` | false | Delete completed checkpoints |

## Expected Output

```
Seeded roots=4, max_depth=3, max_attempts=3
  ✓ root-002/0               (d=0 slow) → leaf
  ✓ root-000/0               (d=0 fast) → leaf
  ⟳ root-001/0               retry 1/3
  ✓ root-001/0               (d=0 fast) → 2 children
  ...
  🏁 root-000 COMPLETE
  🏁 root-001 COMPLETE_WITH_TERMINAL_FAILURES
  ✓ root-003/0.1.0.0         (d=3 slow) → leaf
✅ All work complete.
Checkpoint summary: total=15, completed=14, incomplete=1
```

## Architecture

All orchestration logic lives in the **machine states + hook actions**.
The runner (`scheduler_main.py`) is thin backend/registry glue.

### Hooks registration contract (language-agnostic YAML)

The YAMLs use a language-neutral hook name:

```yaml
hooks: "deepsleep"
```

Each SDK/language runtime must register this name before machine construction.
Python does this via `HooksRegistry`:

```python
registry = HooksRegistry()
registry.register("deepsleep", lambda: DeepSleepHooks(...))
machine = FlatMachine(config_file="...", hooks_registry=registry)
```

This keeps YAML portable across languages while allowing runtime-specific hook implementations.

```
scheduler_main.py (thin runner)
  ↓ constructs backends, creates FlatMachine, calls execute()
scheduler_machine.yml (state machine)
  init → seed → hydrate → pick → claim → dispatch → settle → check_done → loop
                                                                           ↓
  sleep (wait_for "dfss/ready", checkpoint, exit)          ← no work runnable
                                                                           ↓
  report → done                                            ← all_done
```

## Old Tree Demo

The original task-fanout demo (no scheduler, no durable backends) is still
available:

```bash
cd python && .venv/bin/python -m flatagent_dfss_deepsleep.tree_demo
```

## Running Tests

```bash
cd sdk/examples/dfss_deepsleep
python -m pytest python/tests/unit/ -v
```
