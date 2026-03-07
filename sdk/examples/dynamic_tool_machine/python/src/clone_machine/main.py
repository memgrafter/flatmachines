import asyncio
import os
from pathlib import Path

from flatmachines import FlatMachine

from .telemetry import TelemetryLogger, make_run_telemetry_dir
from .tools import ParentToolProvider


def _config_path(name: str) -> str:
    return str(Path(__file__).resolve().parents[3] / "config" / name)


async def run():
    keep_artifacts = os.getenv("CLONE_MACHINE_KEEP_ARTIFACTS", "0") == "1"
    telemetry_dir = make_run_telemetry_dir()
    telemetry = TelemetryLogger(telemetry_dir, role="parent")

    provider = ParentToolProvider(
        keep_artifacts=keep_artifacts,
        telemetry=telemetry,
        telemetry_dir=str(telemetry_dir),
    )

    machine = FlatMachine(
        config_file=_config_path("machine.yml"),
        tool_provider=provider,
    )
    provider.bind_machine(machine)

    telemetry.log_event(
        "parent_machine_start",
        machine_config=_config_path("machine.yml"),
        keep_artifacts=keep_artifacts,
    )

    await machine.execute(input={
        "task": (
            "Generate a dynamic tool with better reliability properties and cross-session reuse, "
            "then launch the child subprocess to exercise it."
        ),
    })

    telemetry.write_json(
        "parent_machine_totals.json",
        {
            "cost": machine.total_cost,
            "api_calls": machine.total_api_calls,
            "execution_id": machine.execution_id,
            "machine_name": machine.machine_name,
        },
    )
    telemetry.log_event(
        "parent_machine_end",
        cost=machine.total_cost,
        api_calls=machine.total_api_calls,
        execution_id=machine.execution_id,
    )

    print("---")
    print(f"Telemetry dir: {telemetry_dir}")
    print(f"Cost: ${machine.total_cost:.4f} | API calls: {machine.total_api_calls}")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
