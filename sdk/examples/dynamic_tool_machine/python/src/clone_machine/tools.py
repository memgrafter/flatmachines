from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any, Dict

from flatagents.tools import ToolResult
from flatmachines import FlatMachine

from .invoker import GeneratedToolSubprocessInvoker
from .telemetry import TelemetryLogger


class ParentToolProvider:
    """Native tools for phase 1.

    - generate_native_tool: deterministic codegen (new artifact each run)
    - launch_generated_machine: launch subprocess child that loads artifact

    Launching is delegated to GeneratedToolSubprocessInvoker.
    """

    def __init__(
        self,
        *,
        invoker: GeneratedToolSubprocessInvoker | None = None,
        launch_timeout_seconds: float = 90.0,
        keep_artifacts: bool = False,
        telemetry: TelemetryLogger | None = None,
        telemetry_dir: str | None = None,
    ):
        self._machine = None
        self._last_artifact_dir: Path | None = None
        self._last_manifest: dict[str, Any] | None = None
        self._telemetry = telemetry
        self._telemetry_dir = telemetry_dir
        self._invoker = invoker or GeneratedToolSubprocessInvoker(
            cwd=str(_python_root()),
            telemetry=telemetry,
        )
        self._launch_timeout_seconds = launch_timeout_seconds
        self._keep_artifacts = keep_artifacts

    def bind_machine(self, machine: FlatMachine) -> None:
        self._machine = machine

    def get_tool_definitions(self):
        return []

    async def execute_tool(self, name: str, tool_call_id: str, arguments: Dict[str, object]) -> ToolResult:
        if self._machine is None:
            return ToolResult(content="Tool provider not bound to machine", is_error=True)

        if self._telemetry:
            self._telemetry.log_event(
                "parent_tool_call_start",
                tool_name=name,
                tool_call_id=tool_call_id,
                arguments=arguments,
            )

        if name == "generate_native_tool":
            result = await self._generate_native_tool(arguments)
        elif name == "launch_generated_machine":
            result = await self._launch_generated_machine(arguments)
        else:
            result = ToolResult(content=f"Unknown tool: {name}", is_error=True)

        if self._telemetry:
            self._telemetry.log_event(
                "parent_tool_call_end",
                tool_name=name,
                tool_call_id=tool_call_id,
                is_error=result.is_error,
                content=result.content,
            )

        return result

    def _cleanup_artifact_dir(self, artifact_dir: Path | None) -> None:
        if artifact_dir and artifact_dir.exists():
            if self._telemetry:
                self._telemetry.log_event("artifact_cleanup", artifact_dir=str(artifact_dir))
            shutil.rmtree(artifact_dir, ignore_errors=True)

    def _cleanup_previous_artifacts(self) -> None:
        if self._keep_artifacts:
            return
        self._cleanup_artifact_dir(self._last_artifact_dir)
        self._last_artifact_dir = None
        self._last_manifest = None

    async def _generate_native_tool(self, arguments: Dict[str, object]) -> ToolResult:
        # Keep at most one artifact tree by default to avoid tempdir leaks.
        self._cleanup_previous_artifacts()

        run_id = uuid.uuid4().hex[:10]

        namespace = str(arguments.get("namespace", "default")).strip() or "default"
        namespace_slug = _slugify(namespace)
        reuse_store = _as_bool(arguments.get("reuse_store", True), default=True)

        tool_name = f"generated_native_tool_{namespace_slug}"

        artifact_dir = Path(tempfile.mkdtemp(prefix=f"clone_machine_{run_id}_"))
        module_path = artifact_dir / "generated_tool.py"
        manifest_path = artifact_dir / "tool_manifest.json"

        store_root = Path(os.getenv("CLONE_MACHINE_TOOL_STORE_DIR", str(_python_root() / ".tool_store")))
        storage_file = store_root / f"{namespace_slug}.json"
        if not reuse_store and storage_file.exists():
            storage_file.unlink(missing_ok=True)

        module_code = textwrap.dedent(
            f"""
            from __future__ import annotations

            import hashlib
            import json
            import os
            import time
            from pathlib import Path

            RUN_ID = {run_id!r}
            NAMESPACE = {namespace!r}
            STORAGE_FILE = Path({str(storage_file)!r})


            def _empty_store() -> dict:
                return {{
                    "namespace": NAMESPACE,
                    "items": {{}},
                    "revisions": {{}},
                    "updated_at": None,
                }}


            def _load_store() -> dict:
                if not STORAGE_FILE.exists():
                    return _empty_store()
                try:
                    payload = json.loads(STORAGE_FILE.read_text(encoding="utf-8"))
                except Exception:
                    return _empty_store()

                if not isinstance(payload, dict):
                    return _empty_store()

                payload.setdefault("namespace", NAMESPACE)
                payload.setdefault("items", {{}})
                payload.setdefault("revisions", {{}})
                payload.setdefault("updated_at", None)

                if not isinstance(payload["items"], dict):
                    payload["items"] = {{}}
                if not isinstance(payload["revisions"], dict):
                    payload["revisions"] = {{}}

                return payload


            def _write_store(payload: dict) -> None:
                STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
                tmp = STORAGE_FILE.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(tmp, STORAGE_FILE)


            def _ok(**extra: object) -> str:
                base = {{
                    "status": "ok",
                    "run_id": RUN_ID,
                    "namespace": NAMESPACE,
                    **extra,
                }}
                return json.dumps(base, sort_keys=True)


            def _err(message: str) -> str:
                return json.dumps(
                    {{
                        "status": "error",
                        "run_id": RUN_ID,
                        "namespace": NAMESPACE,
                        "error": message,
                    }},
                    sort_keys=True,
                )


            def run(arguments: dict) -> str:
                operation = str(arguments.get("operation", "")).strip().lower()
                key = str(arguments.get("key", "")).strip()
                value = arguments.get("value")

                store = _load_store()
                items = store["items"]
                revisions = store["revisions"]

                if operation == "put":
                    if not key:
                        return _err("key is required for put")
                    if value is None:
                        return _err("value is required for put")

                    value_str = str(value)
                    prior = items.get(key)
                    idempotent = prior == value_str
                    if not idempotent:
                        revisions[key] = int(revisions.get(key, 0)) + 1

                    items[key] = value_str
                    store["updated_at"] = int(time.time())
                    _write_store(store)

                    checksum = hashlib.sha256(value_str.encode("utf-8")).hexdigest()[:12]
                    return _ok(
                        operation="put",
                        key=key,
                        value=value_str,
                        revision=int(revisions.get(key, 0)),
                        idempotent=idempotent,
                        checksum=checksum,
                        storage_file=str(STORAGE_FILE),
                    )

                if operation == "get":
                    if not key:
                        return _err("key is required for get")
                    found = key in items
                    return _ok(
                        operation="get",
                        key=key,
                        found=found,
                        value=items.get(key),
                        revision=int(revisions.get(key, 0)),
                        storage_file=str(STORAGE_FILE),
                    )

                if operation == "delete":
                    if not key:
                        return _err("key is required for delete")
                    existed = key in items
                    if existed:
                        items.pop(key, None)
                        revisions[key] = int(revisions.get(key, 0)) + 1
                        store["updated_at"] = int(time.time())
                        _write_store(store)
                    return _ok(
                        operation="delete",
                        key=key,
                        removed=existed,
                        revision=int(revisions.get(key, 0)),
                        storage_file=str(STORAGE_FILE),
                    )

                if operation == "list":
                    limit_raw = arguments.get("limit", 20)
                    try:
                        limit = max(1, min(100, int(limit_raw)))
                    except Exception:
                        limit = 20
                    keys = sorted(items.keys())[:limit]
                    return _ok(
                        operation="list",
                        keys=keys,
                        count=len(items),
                        storage_file=str(STORAGE_FILE),
                    )

                return _err("operation must be one of: put, get, delete, list")
            """
        ).strip() + "\n"

        manifest = {
            "run_id": run_id,
            "tool_name": tool_name,
            "description": (
                "Generated durable key-value memory tool with atomic writes "
                f"for namespace '{namespace}'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "One of: put, get, delete, list",
                    },
                    "key": {"type": "string", "description": "Item key for put/get/delete"},
                    "value": {"type": "string", "description": "Item value for put"},
                    "limit": {"type": "integer", "description": "Max keys for list (1-100)"},
                },
                "required": ["operation"],
            },
            "module_file": str(module_path),
            "entrypoint": "run",
            "namespace": namespace,
            "storage_file": str(storage_file),
            "reuse_store": reuse_store,
        }

        module_path.write_text(module_code)
        manifest_path.write_text(json.dumps(manifest, indent=2))

        self._last_artifact_dir = artifact_dir
        self._last_manifest = manifest

        if self._telemetry:
            self._telemetry.log_event(
                "generated_tool_created",
                run_id=run_id,
                tool_name=tool_name,
                namespace=namespace,
                reuse_store=reuse_store,
                storage_file=str(storage_file),
                artifact_dir=str(artifact_dir),
                module_path=str(module_path),
                manifest_path=str(manifest_path),
            )
            self._telemetry.write_text(f"generated/{run_id}/generated_tool.py", module_code)
            self._telemetry.write_json(f"generated/{run_id}/tool_manifest.json", manifest)

        return ToolResult(
            content=json.dumps(
                {
                    "status": "generated",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "namespace": namespace,
                    "storage_file": str(storage_file),
                    "reuse_store": reuse_store,
                    "artifact_dir": str(artifact_dir),
                },
                indent=2,
            )
        )

    async def _launch_generated_machine(self, arguments: Dict[str, object]) -> ToolResult:
        if self._last_artifact_dir is None:
            return ToolResult(content="No generated tool available. Call generate_native_tool first.", is_error=True)

        artifact_dir = self._last_artifact_dir
        manifest = dict(self._last_manifest or {})
        child_id = str(uuid.uuid4())
        result_file = artifact_dir / f"child_result_{child_id}.json"
        child_config = str(_config_path("child_machine.yml"))

        explicit_task = str(arguments.get("task", "")).strip()
        if explicit_task:
            task = explicit_task
        else:
            task = (
                "Use the generated durable memory tool to validate reliability. "
                f"Run put(key='latest_run', value='{manifest.get('run_id', 'unknown')}'), "
                "then get(key='latest_run'), then list(limit=5). "
                "Return a concise summary including all raw tool outputs."
            )

        if self._telemetry:
            self._telemetry.log_event(
                "child_launch_requested",
                child_execution_id=child_id,
                child_config=child_config,
                artifact_dir=str(artifact_dir),
                result_file=str(result_file),
                task=task,
            )

        launch = await self._invoker.launch(
            child_config=child_config,
            artifact_dir=str(artifact_dir),
            child_execution_id=child_id,
            result_file=str(result_file),
            task=task,
            timeout_seconds=self._launch_timeout_seconds,
            telemetry_dir=self._telemetry_dir,
        )

        payload = {
            "status": launch.status,
            "child_execution_id": launch.child_execution_id,
            "artifact_dir": str(artifact_dir),
            "tool_name": manifest.get("tool_name"),
            "namespace": manifest.get("namespace"),
            "storage_file": manifest.get("storage_file"),
            "stdout": launch.stdout,
            "stderr": launch.stderr,
            "returncode": launch.returncode,
        }
        if launch.child_payload is not None:
            payload["child_payload"] = launch.child_payload

        is_error = launch.status != "launched_subprocess"

        if self._telemetry:
            self._telemetry.write_json(f"child/{child_id}/launch_result.json", payload)

        # Artifact lifecycle: clean generated artifacts after launch by default.
        if not self._keep_artifacts:
            self._cleanup_artifact_dir(artifact_dir)
            self._last_artifact_dir = None
            self._last_manifest = None
            payload["artifacts_retained"] = False
        else:
            payload["artifacts_retained"] = True

        return ToolResult(content=json.dumps(payload, indent=2), is_error=is_error)


class GeneratedToolProvider:
    """Tool provider used by child subprocess.

    It reconstructs the generated native tool from artifact manifest + module file.
    """

    def __init__(self, artifact_dir: str | Path, *, telemetry: TelemetryLogger | None = None):
        self._artifact_dir = Path(artifact_dir)
        self._telemetry = telemetry
        self._manifest = self._load_manifest()
        self._callable = self._load_callable()

    def _load_manifest(self) -> dict[str, Any]:
        manifest_path = self._artifact_dir / "tool_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"tool_manifest.json not found in {self._artifact_dir}")
        manifest = json.loads(manifest_path.read_text())
        if self._telemetry:
            self._telemetry.log_event(
                "child_manifest_loaded",
                manifest_path=str(manifest_path),
                tool_name=manifest.get("tool_name"),
                run_id=manifest.get("run_id"),
            )
            self._telemetry.write_json(
                f"child/{manifest.get('run_id', 'unknown')}/manifest_seen_by_child.json",
                manifest,
            )
        return manifest

    def _load_callable(self):
        module_file = Path(self._manifest["module_file"])
        entrypoint = self._manifest.get("entrypoint", "run")

        spec = importlib.util.spec_from_file_location("clone_machine_generated_tool", module_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load generated module: {module_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        fn = getattr(module, entrypoint, None)
        if fn is None:
            raise RuntimeError(f"Entrypoint '{entrypoint}' not found in {module_file}")

        if self._telemetry:
            self._telemetry.log_event(
                "child_generated_callable_loaded",
                module_file=str(module_file),
                entrypoint=entrypoint,
            )
            try:
                self._telemetry.write_text(
                    f"child/{self._manifest.get('run_id', 'unknown')}/generated_tool_seen_by_child.py",
                    module_file.read_text(),
                )
            except Exception as e:
                self._telemetry.log_event("child_generated_tool_read_failed", error=str(e))

        return fn

    def get_tool_definitions(self):
        defs = [
            {
                "type": "function",
                "function": {
                    "name": self._manifest["tool_name"],
                    "description": self._manifest["description"],
                    "parameters": self._manifest["parameters"],
                },
            }
        ]
        if self._telemetry:
            self._telemetry.write_json(
                f"child/{self._manifest.get('run_id', 'unknown')}/tool_definitions.json",
                defs,
            )
        return defs

    async def execute_tool(self, name: str, tool_call_id: str, arguments: Dict[str, object]) -> ToolResult:
        expected = self._manifest["tool_name"]
        if name != expected:
            if self._telemetry:
                self._telemetry.log_event(
                    "child_tool_call_unknown",
                    expected=expected,
                    received=name,
                    tool_call_id=tool_call_id,
                    arguments=arguments,
                )
            return ToolResult(content=f"Unknown generated tool: {name}", is_error=True)

        if self._telemetry:
            self._telemetry.log_event(
                "child_tool_call_start",
                tool_name=name,
                tool_call_id=tool_call_id,
                arguments=arguments,
            )

        try:
            value = self._callable(arguments)
            result = ToolResult(content=str(value))
            if self._telemetry:
                self._telemetry.log_event(
                    "child_tool_call_end",
                    tool_name=name,
                    tool_call_id=tool_call_id,
                    is_error=False,
                    content=result.content,
                )
            return result
        except Exception as e:
            if self._telemetry:
                self._telemetry.log_event(
                    "child_tool_call_end",
                    tool_name=name,
                    tool_call_id=tool_call_id,
                    is_error=True,
                    error=str(e),
                )
            return ToolResult(content=f"Generated tool failed: {e}", is_error=True)


def _python_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "config" / name


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return cleaned or "default"


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default
