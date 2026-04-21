import asyncio
from pathlib import Path
from flatmachines import FlatMachine, LoggingHooks, setup_logging, get_logger

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run():
    config_path = (
        Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    )
    machine = FlatMachine(config_file=str(config_path), lifecycle_hooks=LoggingHooks())

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"States: {list(machine.states.keys())}")

    result = await machine.execute(input={"task": "Analyze market trends"})

    logger.info("Result:")
    logger.info(f"  Success: {result.get('success')}")
    if result.get('success'):
        logger.info(f"  Result: {result.get('result')}")
    else:
        logger.info(f"  Summary: {result.get('summary')}")
        logger.info(f"  Error: {result.get('error_type')}")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
