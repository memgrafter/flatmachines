# DFSS Pipeline Example (Python)

This example demonstrates **depth-first saturation scheduling (DFSS)** with:

- `FlatMachine` per task execution
- `SQLiteCheckpointBackend` for machine checkpoints
- `SQLiteWorkBackend(...).pool("tasks")` for durable pending work
- resume after interruption (`--resume`)
- gated scarce resource (`slow` gate open/closed)

## Run

```bash
cd sdk/examples/dfss_pipeline/python

# run tests
./test.sh

# fresh run
./run.sh --local --roots 8 --max-depth 3 --max-workers 4 --seed 7 --db-path data/dfss.sqlite

# deterministic (no transient failures)
./run.sh --local --roots 6 --max-depth 3 --seed 7 --fail-rate 0 --db-path data/dfss.sqlite

# resume interrupted work
./run.sh --local --resume --db-path data/dfss.sqlite

# resume + delete completed checkpoints
./run.sh --local --resume --cleanup --db-path data/dfss.sqlite
```

## Expected behavior

- `root-000` quickly exposes two `slow` tasks at depth 2.
- `root-001` has a depth-3 `slow` task behind `fast` predecessors marked with `has_expensive_descendant=true`.
- Scheduler prefers admitted/deeper/near-complete roots while boosting scarce `slow` work and predecessor drills.
- Output logs include gate transitions (`slow gate -> OPEN/CLOSED`) and per-root completion.

## Interrupt + resume walkthrough

1. Start a run (`./run.sh --local ...`).
2. Press `Ctrl+C`.
3. Resume (`./run.sh --local --resume --db-path ...`).
4. Resume path releases stale claims (`pool.release_by_worker("scheduler")`), rebuilds candidates from SQLite pending rows, and continues.

## Layout

```
python/
  pyproject.toml
  run.sh
  test.sh
  src/flatagent_dfss_pipeline/
    main.py
    hooks.py
    scheduler.py
    task_machine.py
    workflow_plan.py
  tests/
    unit/
    integration/
```
