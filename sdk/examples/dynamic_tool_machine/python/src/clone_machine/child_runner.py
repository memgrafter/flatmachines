from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from flatmachines import FlatMachine

from .tools import GeneratedToolProvider


async def run_child(
    *,
    config_file: str,
    artifact_dir: str,
    execution_id: str,
    result_file: str,
    task: str,
):
    provider = GeneratedToolProvider(artifact_dir)

    machine = FlatMachine(
        config_file=config_file,
        tool_provider=provider,
        _execution_id=execution_id,
    )

    result = await machine.execute(input={"task": task})

    payload = {
        "execution_id": execution_id,
        "result": result,
        "cost": machine.total_cost,
        "api_calls": machine.total_api_calls,
    }
    Path(result_file).write_text(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Child subprocess runner for clone_machine")
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--result-file", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()

    asyncio.run(
        run_child(
            config_file=args.config,
            artifact_dir=args.artifact_dir,
            execution_id=args.execution_id,
            result_file=args.result_file,
            task=args.task,
        )
    )


if __name__ == "__main__":
    main()
