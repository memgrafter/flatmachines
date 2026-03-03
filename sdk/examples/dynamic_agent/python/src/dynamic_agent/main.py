"""
Dynamic Agent Example

Demonstrates On-The-Fly (OTF) agent generation with:
- Pre-execution supervisor validation
- Human-in-the-loop review with conditional options
- Iterative refinement based on feedback
"""

import asyncio
import argparse
import os
import sys

# Add src to path for local imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flatmachines import FlatMachine, get_logger
from dynamic_agent.hooks import OTFAgentHooks, UserQuit

logger = get_logger(__name__)


async def main(task: str, style_hints: str = "") -> None:
    """Run the dynamic agent example."""
    
    print("\n" + "=" * 70)
    print("DYNAMIC AGENT - On-The-Fly Agent Generation")
    print("=" * 70)
    print(f"\nTask: {task}")
    if style_hints:
        print(f"Style hints: {style_hints}")
    print("\n")
    
    # Get config paths relative to this file
    config_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
    config_path = os.path.join(config_dir, "config", "machine.yml")
    profiles_path = os.path.join(config_dir, "config", "profiles.yml")

    # Create hooks (with profiles for dynamically generated agents)
    hooks = OTFAgentHooks(profiles_file=profiles_path)
    
    # Create and run machine
    machine = FlatMachine(
        config_file=config_path,
        hooks=hooks
    )
    
    try:
        result = await machine.execute({
            "task": task,
            "style_hints": style_hints
        })
        
        print("\n" + "=" * 70)
        print("FINAL RESULT")
        print("=" * 70)
        
        if result.get("error"):
            print(f"\n❌ Error: {result['error']}")
            if result.get("last_concerns"):
                print(f"Last concerns: {result['last_concerns']}")
        else:
            print(f"\n📝 Content:\n{result.get('content', '(none)')}")
            print(f"\n📊 Attempts: {result.get('attempts', 'N/A')}")
        
        print("\n📈 Metrics:")
        for key, value in hooks.get_metrics().items():
            print(f"   {key}: {value}")
        
    except (UserQuit, KeyboardInterrupt):
        print("\n\nExecution cancelled by user.")
        return


def cli():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Dynamic Agent - On-The-Fly Agent Generation"
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="Write a haiku about the beauty of mountain sunrises",
        help="The creative writing task"
    )
    parser.add_argument(
        "--style",
        default="",
        help="Style hints for the writing (e.g., 'humorous', 'melancholic')"
    )
    
    args = parser.parse_args()
    asyncio.run(main(args.task, args.style))


if __name__ == "__main__":
    cli()
