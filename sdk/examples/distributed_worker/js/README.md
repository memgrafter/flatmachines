# Distributed Worker Example (JavaScript)

JS parity version of the Python distributed worker demo.

Uses the same config machines in `../config/`:
- `parallelization_checker.yml`
- `job_worker.yml`
- `echo_processor.yml`
- `stale_worker_reaper.yml`
- `profiles.yml`

## Quick start

```bash
cd sdk/examples/distributed_worker/js
./run.sh --local all --count 5 --max-workers 3
```

## Commands

```bash
./run.sh --local seed --count 10
./run.sh --local checker --max-workers 3
./run.sh --local worker
./run.sh --local reaper --threshold 60
./run.sh --local all
```

## Notes

- Uses SQLite backends for registration + work pool.
- Custom `echo_delay` action is implemented in JS hooks.
