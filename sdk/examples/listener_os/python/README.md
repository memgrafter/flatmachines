# Listener OS Example (Python)

Demonstrates **real OS activation** for `wait_for` signals on macOS and Linux.

## What this proves

- Machine parks on `wait_for` (`approval/{{ task_id }}`)
- Producer calls `send_and_notify(..., trigger=file)`
- OS watcher (launchd/systemd) starts `dispatch-once`
- Parked machine resumes

> `run.sh` **fails** unless OS activation is working. It does **not** manually call `dispatch-once`.

## Template files (in config/activation)

- `../config/activation/macos/launchd.plist.tmpl`
- `../config/activation/linux/listener-os-dispatch.service.tmpl`
- `../config/activation/linux/listener-os-dispatch.path.tmpl`

These are rendered by the Python CLI and installed as user-level services.

## Quick start (strict OS integration check)

```bash
cd sdk/examples/listener_os/python
./run.sh --local
```

`run.sh` will ask for explicit approval before making OS service/login-item changes.

Options:

```bash
# non-interactive approval (CI/scripted)
./run.sh --local --yes

# keep service installed after success
./run.sh --local --keep-activation

# custom timeout + task id
./run.sh --local --timeout 30 --task-id my-task
```

## CLI commands

```bash
# reset demo data
python -m listener_os.main reset

# park machine
python -m listener_os.main park --task-id task-001

# send signal + notify trigger
python -m listener_os.main send --task-id task-001 --approved true --reviewer alice --trigger file

# dispatcher runtime commands
python -m listener_os.main dispatch-once
python -m listener_os.main listen

# status
python -m listener_os.main status

# render activation files from templates
python -m listener_os.main print-activation --os auto

# install / uninstall OS activation
python -m listener_os.main install-activation --os auto
python -m listener_os.main uninstall-activation --os auto
```

## Notes

- macOS installs user plist under `~/Library/LaunchAgents/`
- Linux installs user units under `~/.config/systemd/user/`
- default state/log/db files live under `../data/`
