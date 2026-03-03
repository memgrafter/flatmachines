"""
Coding Agent Demo for FlatAgents.

An agentic coding assistant that plans, implements, and verifies
code changes with human approval gates.

Usage:
    python -m coding_agent.main "Add input validation"
    ./run.sh "Create a hello world function" --cwd /path/to/project
"""

import argparse
import asyncio
from pathlib import Path
import os
import warnings
import importlib.util

# Suppress Pydantic serialization warnings
warnings.filterwarnings('ignore', message='.*Pydantic serializer warnings.*')
warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')

from flatmachines import FlatMachine, HooksRegistry, setup_logging, get_logger
from .hooks import CodingAgentHooks

# Configure logging (respects LOG_LEVEL env var for quiet mode)
log_level = os.environ.get('LOG_LEVEL', 'INFO')
setup_logging(level=log_level)
logger = get_logger(__name__)


def _register_codebase_explorer_hooks(
    registry: HooksRegistry,
    project_root: Path,
    working_dir: Path,
) -> None:
    """Register hooks used by nested .skills/codebase_explorer machine."""
    hooks_file = project_root / ".skills" / "codebase_explorer" / "src" / "codebase_explorer" / "hooks.py"

    if not hooks_file.exists():
        logger.warning(f"Explorer hooks not found: {hooks_file}")
        registry.register("codebase-explorer", lambda: CodingAgentHooks(working_dir=str(working_dir)))
        return

    try:
        spec = importlib.util.spec_from_file_location("codebase_explorer_hooks", hooks_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to build import spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hooks_cls = getattr(module, "CodebaseExplorerHooks")
        registry.register("codebase-explorer", lambda: hooks_cls(working_dir=str(working_dir)))
    except Exception as e:
        logger.warning(f"Failed to register explorer hooks from {hooks_file}: {e}")
        registry.register("codebase-explorer", lambda: CodingAgentHooks(working_dir=str(working_dir)))


async def run(task: str, cwd: str = ".", max_iterations: int = 5):
    """
    Run the coding agent workflow.

    Args:
        task: The coding task to accomplish
        cwd: Working directory for the codebase
        max_iterations: Maximum revision iterations
    """
    logger.info("=" * 70)
    logger.info("🤖 Coding Agent")
    logger.info("=" * 70)

    # Resolve paths
    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    working_dir = Path(cwd).expanduser().resolve()
    
    # Capture actual directory user ran from (for safety checks)
    user_cwd = Path.cwd().resolve()
    
    # Register hooks by name so config hooks refs resolve correctly
    registry = HooksRegistry()
    registry.register("coding-agent", lambda: CodingAgentHooks(working_dir=str(working_dir)))
    _register_codebase_explorer_hooks(registry, config_path.parent.parent, working_dir)

    machine = FlatMachine(
        config_file=str(config_path),
        hooks_registry=registry,
    )

    logger.info(f"Machine: {machine.machine_name}")
    logger.info(f"Task: {task}")
    logger.info(f"Working Dir: {working_dir}")
    logger.info("-" * 70)

    # Execute
    result = await machine.execute(input={
        "task": task,
        "cwd": str(working_dir),
        "user_cwd": str(user_cwd),  # For path safety validation
        "max_iterations": max_iterations
    })

    # Display results
    logger.info("=" * 70)
    logger.info("📊 RESULTS")
    logger.info("=" * 70)
    logger.info(f"Status: {result.get('status', 'unknown')}")
    logger.info(f"Iterations: {result.get('iterations', 0)}")
    
    if result.get('changes'):
        changes = result['changes']
        if isinstance(changes, dict):
            logger.info(f"Summary: {changes.get('summary', '')}")
            files = changes.get('files', [])
            logger.info(f"Files affected: {len(files)}")
    
    logger.info("-" * 70)
    logger.info(f"Total API calls: {machine.total_api_calls}")
    logger.info(f"Estimated cost: ${machine.total_cost:.4f}")

    return result


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI Coding Agent - Plans, implements, and verifies code changes"
    )
    parser.add_argument(
        "task",
        help="The coding task to accomplish"
    )
    parser.add_argument(
        "--cwd", "-c",
        default=".",
        help="Working directory for the codebase (default: current directory)"
    )
    parser.add_argument(
        "--max-iterations", "-m",
        type=int,
        default=5,
        help="Maximum revision iterations (default: 5)"
    )
    args = parser.parse_args()
    
    asyncio.run(run(
        task=args.task,
        cwd=args.cwd,
        max_iterations=args.max_iterations
    ))


if __name__ == "__main__":
    main()
