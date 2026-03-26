# DFSS Deep Sleep Demo (JavaScript)

JS parity implementation for the Python DFSS deep-sleep scheduler.

Uses the same machine configs in `../config/`:
- `scheduler_machine.yml`
- `task_machine.yml`

## Quick start

```bash
cd sdk/examples/dfss_deepsleep/js
./run.sh --local --roots 4 --max-depth 2 --fail-rate 0 --seed 7
```

Resume parked execution:

```bash
./run.sh --local --resume --db-path data/dfss.sqlite
```

## Notes

- Scheduler orchestration remains in YAML machine states.
- JS hooks implement scheduler/task actions (`deepsleep` hook registry name).
- Uses SQLite work pool + checkpoints + signals in one DB file.
