"""
OS listener demo for FlatMachines signals.

One code path for macOS + Linux:
- machine parks on wait_for
- producer calls send_and_notify(..., trigger=file)
- OS file watcher starts `dispatch-once`
- dispatcher resumes parked machines

Activation templates live in ../config/activation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

from flatmachines import (
    CheckpointManager,
    ConfigStoreResumer,
    FileTrigger,
    FlatMachine,
    NoOpTrigger,
    SQLiteCheckpointBackend,
    SQLiteSignalBackend,
    SocketTrigger,
    get_logger,
    send_and_notify,
    setup_logging,
)
from flatmachines.dispatch_signals import run_listen, run_once

setup_logging(level="INFO")
logger = get_logger(__name__)


def _example_root() -> Path:
    # .../sdk/examples/listener_os/python/src/listener_os/main.py -> listener_os/
    return Path(__file__).resolve().parents[3]


def _default_paths() -> Dict[str, Path]:
    root = _example_root()
    data_dir = root / "data"
    return {
        "root": root,
        "data_dir": data_dir,
        "machine": root / "config" / "machine.yml",
        "activation_dir": root / "config" / "activation",
        "db": data_dir / "listener_os.sqlite",
        "trigger_base": data_dir / "trigger",
        "socket": data_dir / "trigger.sock",
        "out_log": data_dir / "activation.out.log",
        "err_log": data_dir / "activation.err.log",
    }


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _bool(value: str) -> bool:
    v = value.strip().lower()
    if v in {"1", "true", "t", "yes", "y"}:
        return True
    if v in {"0", "false", "f", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool: {value}")


def _detect_os(arg: str) -> str:
    if arg != "auto":
        return arg
    if sys.platform.startswith("darwin"):
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"unsupported platform for --os auto: {sys.platform}")


def _build_backends(db_path: Path):
    _ensure_parent(db_path)
    signal_backend = SQLiteSignalBackend(db_path=str(db_path))
    persistence = SQLiteCheckpointBackend(db_path=str(db_path))
    config_store = persistence.config_store
    return signal_backend, persistence, config_store


def _machine(config_path: Path, db_path: Path, signal_backend) -> FlatMachine:
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = config.setdefault("data", {})
    existing = data.get("persistence") if isinstance(data.get("persistence"), dict) else {}
    data["persistence"] = {
        **existing,
        "enabled": True,
        "backend": "sqlite",
        "db_path": str(db_path),
    }

    return FlatMachine(
        config_dict=config,
        signal_backend=signal_backend,
    )


def _read_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _render_template(text: str, values: Dict[str, str]) -> str:
    rendered = text
    for k, v in values.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
    return rendered


def _resolve_exec(executable: str) -> str:
    """Resolve executable to an absolute path when possible.

    systemd rejects ExecStart values that contain a slash but are not absolute
    (e.g. '.venv/bin/python'). Keep symlink paths intact (don't dereference),
    so venv python shims still behave like the venv interpreter.
    """
    if os.sep in executable or (os.altsep and os.altsep in executable):
        return os.path.abspath(os.path.expanduser(executable))

    found = shutil.which(executable)
    if found:
        return found

    return executable


def _activation_values(args) -> Dict[str, str]:
    paths = _default_paths()
    db = Path(args.db_path).expanduser().resolve() if getattr(args, "db_path", None) else paths["db"]
    trigger_base = Path(args.trigger_base).expanduser().resolve() if getattr(args, "trigger_base", None) else paths["trigger_base"]
    trigger_file = trigger_base / "trigger"
    python_arg = getattr(args, "python", None)
    python_exec = _resolve_exec(python_arg) if python_arg else sys.executable
    label = getattr(args, "label", None) or "dev.flatmachines.listener_os"
    service_name = getattr(args, "service_name", None) or "listener-os-dispatch"

    return {
        "LABEL": label,
        "SERVICE_NAME": service_name,
        "PYTHON": python_exec,
        "WORKDIR": str((paths["root"] / "python").resolve()),
        "DB_PATH": str(db),
        "TRIGGER_FILE": str(trigger_file),
        "OUT_LOG": str(paths["out_log"]),
        "ERR_LOG": str(paths["err_log"]),
    }


def _render_activation(os_name: str, args) -> Dict[str, str]:
    paths = _default_paths()
    files_dir = paths["activation_dir"]
    vals = _activation_values(args)

    if os_name == "macos":
        tpl = _read_template(files_dir / "macos" / "launchd.plist.tmpl")
        return {"plist": _render_template(tpl, vals)}

    service_tpl = _read_template(files_dir / "linux" / "listener-os-dispatch.service.tmpl")
    path_tpl = _read_template(files_dir / "linux" / "listener-os-dispatch.path.tmpl")
    return {
        "service": _render_template(service_tpl, vals),
        "path": _render_template(path_tpl, vals),
    }


def _launchd_target_path(label: str, arg_path: str | None) -> Path:
    if arg_path:
        return Path(arg_path).expanduser().resolve()
    return (Path.home() / "Library" / "LaunchAgents" / f"{label}.plist").resolve()


def _systemd_target_paths(service_name: str, units_dir: str | None) -> Tuple[Path, Path]:
    base = Path(units_dir).expanduser().resolve() if units_dir else (Path.home() / ".config" / "systemd" / "user").resolve()
    return base / f"{service_name}.service", base / f"{service_name}.path"


def _run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _resumer(signal_backend, persistence, config_store) -> ConfigStoreResumer:
    """Build a ConfigStoreResumer for the demo machine."""
    return ConfigStoreResumer(signal_backend, persistence, config_store)


async def _pending_by_channel(signal_backend) -> Dict[str, int]:
    """Return pending signal counts by channel."""
    channels = await signal_backend.channels()
    return {ch: len(await signal_backend.peek(ch)) for ch in channels}


async def cmd_park(args) -> None:
    paths = _default_paths()
    db_path = Path(args.db_path) if args.db_path else paths["db"]
    signal_backend, _, _ = _build_backends(db_path)

    machine = _machine(paths["machine"], db_path, signal_backend)
    result = await machine.execute(input={"task_id": args.task_id})

    print(json.dumps({"execution_id": machine.execution_id, "result": result}, indent=2))


async def cmd_send(args) -> None:
    paths = _default_paths()
    db_path = Path(args.db_path) if args.db_path else paths["db"]
    trigger_base = Path(args.trigger_base) if args.trigger_base else paths["trigger_base"]
    socket_path = Path(args.socket_path) if args.socket_path else paths["socket"]

    signal_backend, _, _ = _build_backends(db_path)

    if args.trigger == "none":
        trigger_backend = NoOpTrigger()
    elif args.trigger == "file":
        trigger_backend = FileTrigger(base_path=str(trigger_base))
    else:
        trigger_backend = SocketTrigger(socket_path=str(socket_path))

    channel = f"approval/{args.task_id}"
    payload = {"approved": args.approved, "reviewer": args.reviewer}

    signal_id = await send_and_notify(
        signal_backend=signal_backend,
        trigger_backend=trigger_backend,
        channel=channel,
        data=payload,
    )

    print(json.dumps({
        "signal_id": signal_id,
        "channel": channel,
        "payload": payload,
        "trigger": args.trigger,
    }, indent=2))


async def cmd_dispatch_once(args) -> None:
    paths = _default_paths()
    db_path = Path(args.db_path) if args.db_path else paths["db"]
    signal_backend, persistence, config_store = _build_backends(db_path)

    pending_before = await _pending_by_channel(signal_backend)
    resumer = _resumer(signal_backend, persistence, config_store)
    results = await run_once(signal_backend, persistence, resumer=resumer)
    pending_after = await _pending_by_channel(signal_backend)

    resumed_total = sum(len(ids) for ids in results.values())
    print(json.dumps({
        "resumed_by_channel": results,
        "resumed_total": resumed_total,
        "pending_before": pending_before,
        "pending_after": pending_after,
    }, indent=2, default=str))


async def cmd_listen(args) -> None:
    paths = _default_paths()
    db_path = Path(args.db_path) if args.db_path else paths["db"]
    socket_path = Path(args.socket_path) if args.socket_path else paths["socket"]
    signal_backend, persistence, config_store = _build_backends(db_path)

    resumer = _resumer(signal_backend, persistence, config_store)

    stop_event = asyncio.Event()
    stopper = None
    if args.duration and args.duration > 0:
        async def stop_later():
            await asyncio.sleep(args.duration)
            stop_event.set()
        stopper = asyncio.create_task(stop_later())

    try:
        await run_listen(
            signal_backend,
            persistence,
            socket_path=str(socket_path),
            resumer=resumer,
            stop_event=stop_event,
        )
    finally:
        if stopper:
            stopper.cancel()


async def cmd_status(args) -> None:
    paths = _default_paths()
    db_path = Path(args.db_path) if args.db_path else paths["db"]
    signal_backend, persistence, _ = _build_backends(db_path)

    channels = await signal_backend.channels()
    pending = {ch: len(await signal_backend.peek(ch)) for ch in channels}

    execution_ids = await persistence.list_execution_ids()
    waiting: Dict[str, list[str]] = {}
    for eid in execution_ids:
        snapshot = await CheckpointManager(persistence, eid).load_latest()
        if snapshot and snapshot.waiting_channel:
            waiting.setdefault(snapshot.waiting_channel, []).append(eid)

    print(json.dumps({
        "db_path": str(db_path),
        "pending_signals": pending,
        "waiting_machines": waiting,
    }, indent=2))


async def cmd_reset(args) -> None:
    paths = _default_paths()
    data_dir = Path(args.data_dir) if args.data_dir else paths["data_dir"]
    if data_dir.exists():
        shutil.rmtree(data_dir)
    print(json.dumps({"removed": str(data_dir)}))


def cmd_render_activation(args) -> None:
    os_name = _detect_os(args.os)
    rendered = _render_activation(os_name, args)

    if os_name == "macos":
        print(rendered["plist"])
        return

    service_name = _activation_values(args)["SERVICE_NAME"]
    print(f"# {service_name}.service")
    print(rendered["service"])
    print(f"# {service_name}.path")
    print(rendered["path"])


def cmd_install_activation(args) -> None:
    os_name = _detect_os(args.os)
    values = _activation_values(args)
    rendered = _render_activation(os_name, args)
    paths = _default_paths()

    # Ensure trigger parent/log directories exist before watcher activation
    trigger_file = Path(values["TRIGGER_FILE"])
    trigger_file.parent.mkdir(parents=True, exist_ok=True)
    trigger_file.touch(exist_ok=True)
    paths["data_dir"].mkdir(parents=True, exist_ok=True)

    if os_name == "macos":
        plist_path = _launchd_target_path(values["LABEL"], args.plist_path)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(rendered["plist"], encoding="utf-8")

        domain = f"gui/{os.getuid()}"
        _run_cmd(["launchctl", "bootout", domain, str(plist_path)], check=False)
        _run_cmd(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
        _run_cmd(["launchctl", "enable", f"{domain}/{values['LABEL']}"], check=False)

        print(json.dumps({
            "installed": True,
            "os": os_name,
            "label": values["LABEL"],
            "plist": str(plist_path),
            "trigger_file": values["TRIGGER_FILE"],
        }, indent=2))
        return

    # linux
    service_path, path_path = _systemd_target_paths(values["SERVICE_NAME"], args.units_dir)
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(rendered["service"], encoding="utf-8")
    path_path.write_text(rendered["path"], encoding="utf-8")

    _run_cmd(["systemctl", "--user", "daemon-reload"], check=True)
    _run_cmd(["systemctl", "--user", "enable", "--now", f"{values['SERVICE_NAME']}.path"], check=True)

    print(json.dumps({
        "installed": True,
        "os": os_name,
        "service": str(service_path),
        "path": str(path_path),
        "trigger_file": values["TRIGGER_FILE"],
    }, indent=2))


def cmd_uninstall_activation(args) -> None:
    os_name = _detect_os(args.os)
    values = _activation_values(args)

    if os_name == "macos":
        plist_path = _launchd_target_path(values["LABEL"], args.plist_path)
        domain = f"gui/{os.getuid()}"
        _run_cmd(["launchctl", "bootout", domain, str(plist_path)], check=False)
        if plist_path.exists():
            plist_path.unlink()

        print(json.dumps({
            "uninstalled": True,
            "os": os_name,
            "label": values["LABEL"],
            "plist": str(plist_path),
        }, indent=2))
        return

    # linux
    service_path, path_path = _systemd_target_paths(values["SERVICE_NAME"], args.units_dir)
    _run_cmd(["systemctl", "--user", "disable", "--now", f"{values['SERVICE_NAME']}.path"], check=False)
    _run_cmd(["systemctl", "--user", "stop", f"{values['SERVICE_NAME']}.service"], check=False)
    if service_path.exists():
        service_path.unlink()
    if path_path.exists():
        path_path.unlink()
    _run_cmd(["systemctl", "--user", "daemon-reload"], check=False)

    print(json.dumps({
        "uninstalled": True,
        "os": os_name,
        "service": str(service_path),
        "path": str(path_path),
    }, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OS listener demo (macOS + Linux)")
    sub = p.add_subparsers(dest="command", required=True)

    park = sub.add_parser("park", help="start machine and park on wait_for")
    park.add_argument("--task-id", required=True)
    park.add_argument("--db-path")

    send = sub.add_parser("send", help="send signal and notify trigger")
    send.add_argument("--task-id", required=True)
    send.add_argument("--approved", type=_bool, default=True)
    send.add_argument("--reviewer", default="demo-user")
    send.add_argument("--trigger", choices=["none", "file", "socket"], default="file")
    send.add_argument("--trigger-base")
    send.add_argument("--socket-path")
    send.add_argument("--db-path")

    once = sub.add_parser("dispatch-once", help="drain pending signals and resume waiters")
    once.add_argument("--db-path")

    listen = sub.add_parser("listen", help="listen on UDS and dispatch on triggers")
    listen.add_argument("--socket-path")
    listen.add_argument("--db-path")
    listen.add_argument("--duration", type=float, default=0.0, help="optional auto-stop seconds")

    status = sub.add_parser("status", help="show pending signals and waiting machines")
    status.add_argument("--db-path")

    reset = sub.add_parser("reset", help="delete demo data directory")
    reset.add_argument("--data-dir")

    render = sub.add_parser("print-activation", help="print rendered launchd/systemd files")
    render.add_argument("--os", choices=["auto", "macos", "linux"], default="auto")
    render.add_argument("--python")
    render.add_argument("--db-path")
    render.add_argument("--trigger-base")
    render.add_argument("--label")
    render.add_argument("--service-name")

    install = sub.add_parser("install-activation", help="install + enable launchd/systemd watcher")
    install.add_argument("--os", choices=["auto", "macos", "linux"], default="auto")
    install.add_argument("--python")
    install.add_argument("--db-path")
    install.add_argument("--trigger-base")
    install.add_argument("--label")
    install.add_argument("--service-name")
    install.add_argument("--plist-path", help="macOS override plist path")
    install.add_argument("--units-dir", help="Linux override systemd user units dir")

    uninstall = sub.add_parser("uninstall-activation", help="disable + remove launchd/systemd watcher")
    uninstall.add_argument("--os", choices=["auto", "macos", "linux"], default="auto")
    uninstall.add_argument("--label")
    uninstall.add_argument("--service-name")
    uninstall.add_argument("--plist-path", help="macOS override plist path")
    uninstall.add_argument("--units-dir", help="Linux override systemd user units dir")
    uninstall.add_argument("--db-path")
    uninstall.add_argument("--trigger-base")

    return p


async def _async_main(args) -> None:
    if args.command == "park":
        await cmd_park(args)
    elif args.command == "send":
        await cmd_send(args)
    elif args.command == "dispatch-once":
        await cmd_dispatch_once(args)
    elif args.command == "listen":
        await cmd_listen(args)
    elif args.command == "status":
        await cmd_status(args)
    elif args.command == "reset":
        await cmd_reset(args)
    elif args.command == "print-activation":
        cmd_render_activation(args)
    elif args.command == "install-activation":
        cmd_install_activation(args)
    elif args.command == "uninstall-activation":
        cmd_uninstall_activation(args)
    else:
        raise ValueError(f"unknown command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
