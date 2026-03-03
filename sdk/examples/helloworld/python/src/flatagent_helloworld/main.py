import asyncio
import os
from pathlib import Path
from typing import Dict, Any, Optional

from flatmachines import FlatMachine, HooksRegistry, LoggingHooks, setup_logging, get_logger

# Configure logging for the entire application
setup_logging(level='INFO')
logger = get_logger(__name__)


class HelloWorldHooks(LoggingHooks):
    """Hooks for the HelloWorld demo with append_char action."""

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]]
    ):
        output = super().on_state_exit(state_name, context, output)
        if state_name == "build_char" and output:
            next_char = output.get("next_char")
            if next_char is None:
                next_char = output.get("content")
            if next_char:
                ch = str(next_char)[0]
                current = context.get("current", "")
                expected = context.get("expected_char")
                status = "match" if expected is not None and ch == expected else "mismatch"
                print(f"{current}{ch} ({status})")
        return output

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "append_char":
            last_output = context.get("last_output", "")
            if last_output:
                context["current"] = context["current"] + str(last_output)[0]
        return context


async def run():
    """
    Main function to run the FlatMachine HelloWorld demo.

    The loop and state management is now handled by FlatMachine,
    defined in config/machine.yml.
    """
    logger.info("--- Starting FlatMachine HelloWorld Demo ---")

    # Load the machine from YAML
    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    hooks_registry = HooksRegistry()
    hooks_registry.register("hello-world-hooks", HelloWorldHooks)

    machine = FlatMachine(
        config_file=str(config_path),
        hooks_registry=hooks_registry,
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")

    target = "Hello, World!"
    logger.info(f"Target: '{target}'")
    logger.info("Building character by character...")

    # Execute the machine - all loop logic is in the config
    # Limit to 20 agent calls (14 chars + buffer) to prevent runaway loops
    result = await machine.execute(input={"target": target}, max_agent_calls=20)

    logger.info("--- Execution Complete ---")
    logger.info(f"Final: '{result.get('result', '')}'")

    if result.get('success'):
        logger.info("Success! The machine built the string correctly.")
    else:
        logger.warning("Failure. The machine did not build the string correctly.")

    logger.info("--- Execution Statistics ---")
    logger.info(f"Total Cost: ${machine.total_cost:.4f}")
    logger.info(f"Total API Calls: {machine.total_api_calls}")


def main():
    """Synchronous entry point for the script defined in pyproject.toml."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
