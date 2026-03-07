from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from flatmachines import FlatMachine

from .telemetry import TelemetryLogger
from .tools import GeneratedToolProvider


async def run_child(
    *,
    config_file: str,
    artifact_dir: str,
    execution_id: str,
    result_file: str,
    task: str,
    telemetry_dir: str | None = None,
):
    telemetry = None
    if telemetry_dir:
        telemetry = TelemetryLogger(telemetry_dir, role=f"child_{execution_id[:8]}")
        telemetry.log_event(
            "child_runner_start",
            execution_id=execution_id,
            config_file=config_file,
            artifact_dir=artifact_dir,
            result_file=result_file,
            task=task,
        )
        try:
            telemetry.write_text(
                f"child/{execution_id}/child_machine_source.yml",
                Path(config_file).read_text(encoding="utf-8"),
            )
        except Exception as e:
            telemetry.log_event("child_machine_source_read_failed", error=str(e))

    provider = GeneratedToolProvider(artifact_dir, telemetry=telemetry)

    machine = FlatMachine(
        config_file=config_file,
        tool_provider=provider,
        _execution_id=execution_id,
    )

    if telemetry:
        telemetry.write_json(f"child/{execution_id}/child_machine_resolved_config.json", machine.config)
        telemetry.log_event(
            "child_machine_initialized",
            machine_name=machine.machine_name,
            execution_id=machine.execution_id,
        )

    result = await machine.execute(input={"task": task})

    payload = {
        "execution_id": execution_id,
        "result": result,
        "cost": machine.total_cost,
        "api_calls": machine.total_api_calls,
    }
    Path(result_file).write_text(json.dumps(payload, indent=2))

    if telemetry:
        telemetry.write_json(f"child/{execution_id}/child_result_payload.json", payload)
        telemetry.log_event(
            "child_runner_end",
            execution_id=execution_id,
            cost=machine.total_cost,
            api_calls=machine.total_api_calls,
        )


def main():
    parser = argparse.ArgumentParser(description="Child subprocess runner for clone_machine")
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--telemetry-dir", required=False)
    args = parser.parse_args()

    asyncio.run(
        run_child(
            config_file=args.config,
            artifact_dir=args.artifact_dir,
            execution_id=args.execution_id,
            result_file=args.result_file,
            task=args.task,
            telemetry_dir=args.telemetry_dir,
        )
    )


if __name__ == "__main__":
    main()
