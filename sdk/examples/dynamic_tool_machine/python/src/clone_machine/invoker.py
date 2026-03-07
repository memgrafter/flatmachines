from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .telemetry import TelemetryLogger


@dataclass
class ChildLaunchResult:
    status: str
    child_execution_id: str
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    child_payload: dict[str, Any] | None = None


class GeneratedToolSubprocessInvoker:
    """Launches clone_machine child runner in a subprocess.

    This is an example-local invoker abstraction so launch behavior is not
    hard-coded inside the tool provider.
    """

    def __init__(
        self,
        *,
        python_executable: str | None = None,
        module: str = "clone_machine.child_runner",
        cwd: str | None = None,
        telemetry: TelemetryLogger | None = None,
    ):
        self.python_executable = python_executable or sys.executable
        self.module = module
        self.cwd = cwd
        self.telemetry = telemetry

    async def launch(
        self,
        *,
        child_config: str,
        artifact_dir: str,
        child_execution_id: str,
        result_file: str,
        task: str,
        timeout_seconds: float,
        telemetry_dir: str | None = None,
    ) -> ChildLaunchResult:
        cmd = [
            self.python_executable,
            "-m",
            self.module,
            "--config",
            child_config,
            "--artifact-dir",
            artifact_dir,
            "--execution-id",
            child_execution_id,
            "--result-file",
            result_file,
            "--task",
            task,
        ]
        if telemetry_dir:
            cmd.extend(["--telemetry-dir", telemetry_dir])

        if self.telemetry:
            self.telemetry.log_event(
                "subprocess_exec_start",
                child_execution_id=child_execution_id,
                cmd=cmd,
                cwd=self.cwd,
                timeout_seconds=timeout_seconds,
            )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            # Best-effort shutdown
            if hasattr(proc, "terminate"):
                proc.terminate()
            if hasattr(proc, "wait"):
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    if hasattr(proc, "kill"):
                        proc.kill()
                    try:
                        await proc.wait()
                    except Exception:
                        pass
            if self.telemetry:
                self.telemetry.log_event("subprocess_exec_timeout", child_execution_id=child_execution_id)
            return ChildLaunchResult(
                status="subprocess_timeout",
                child_execution_id=child_execution_id,
            )

        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()

        if self.telemetry:
            self.telemetry.write_text(f"child/{child_execution_id}/subprocess_stdout.txt", stdout)
            self.telemetry.write_text(f"child/{child_execution_id}/subprocess_stderr.txt", stderr)

        if proc.returncode != 0:
            if self.telemetry:
                self.telemetry.log_event(
                    "subprocess_exec_failed",
                    child_execution_id=child_execution_id,
                    returncode=proc.returncode,
                )
            return ChildLaunchResult(
                status="subprocess_failed",
                child_execution_id=child_execution_id,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
            )

        result_path = Path(result_file)
        if not result_path.exists():
            if self.telemetry:
                self.telemetry.log_event(
                    "subprocess_missing_child_result",
                    child_execution_id=child_execution_id,
                    result_file=str(result_path),
                )
            return ChildLaunchResult(
                status="missing_child_result",
                child_execution_id=child_execution_id,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
            )

        try:
            child_payload = json.loads(result_path.read_text())
        except Exception as e:
            if self.telemetry:
                self.telemetry.log_event(
                    "subprocess_invalid_child_result",
                    child_execution_id=child_execution_id,
                    error=str(e),
                    result_file=str(result_path),
                )
            return ChildLaunchResult(
                status="invalid_child_result",
                child_execution_id=child_execution_id,
                stdout=stdout,
                stderr=f"failed to parse child result: {e}",
                returncode=proc.returncode,
            )

        if self.telemetry:
            self.telemetry.write_json(f"child/{child_execution_id}/result_file_payload.json", child_payload)
            self.telemetry.log_event(
                "subprocess_exec_success",
                child_execution_id=child_execution_id,
                returncode=proc.returncode,
                result_file=str(result_path),
            )

        return ChildLaunchResult(
            status="launched_subprocess",
            child_execution_id=child_execution_id,
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode,
            child_payload=child_payload,
        )
