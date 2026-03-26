# Listener OS Example (JavaScript)

JS parity implementation for the listener/signal demo.

Uses the same machine config in `../config/machine.yml`.

## Quick start (local smoke)

```bash
cd sdk/examples/listener_os/js
./run.sh --local
```

Default runner flow:
1. reset
2. park machine on `wait_for`
3. send signal
4. dispatch-once
5. show status

## CLI commands

```bash
./run.sh --local reset
./run.sh --local park --task-id task-001
./run.sh --local send --task-id task-001 --approved true --reviewer alice --trigger file
./run.sh --local dispatch-once
./run.sh --local status
```

## Notes

- Uses SQLite signals + SQLite checkpoints.
- Uses `ConfigStoreResumer` + `run_once` to resume parked machines.
- Focused on signal/wait overlap; OS activation template install/uninstall is still Python-first.
