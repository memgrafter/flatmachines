"""
Character Card Chat Demo for FlatAgents.

Loads a Character Card V1/V2/V3 PNG or JSON file and enables
interactive chat with the character.

Features:
- User persona support (description)
- LLM-driven auto-user mode
- Inject messages from file
- Scripted responses

Usage:
    ./run.sh card.png
    ./run.sh card.png --user "Alice" --persona "A curious student"
    ./run.sh card.png --persona-file persona.json
    ./run.sh card.png --messages-file history.json
    ./run.sh card.png --auto-user
"""

import argparse
import asyncio
from pathlib import Path

from flatmachines import FlatMachine, HooksRegistry, setup_logging, get_logger
from .hooks import CharacterCardHooks

# Configure logging
setup_logging(level='INFO')
logger = get_logger(__name__)


async def run(
    card_path: str,
    user_name: str = "User",
    user_persona: str = None,
    persona_file: str = None,
    messages_file: str = None,
    no_system_prompt: bool = False,
    auto_user: bool = False,
    max_turns: int = None,
):
    """Run character card chat."""
    if not Path(card_path).exists():
        logger.error(f"Card file not found: {card_path}")
        return None
    
    config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'machine.yml'
    hooks_registry = HooksRegistry()
    hooks_registry.register(
        "character-card-hooks",
        lambda: CharacterCardHooks(
            card_path=card_path,
            user_name=user_name,
            user_persona=user_persona,
            persona_file=persona_file,
            messages_file=messages_file,
            no_system_prompt=no_system_prompt,
            auto_user=auto_user,
            max_turns=max_turns,
        ),
    )

    machine = FlatMachine(
        config_file=str(config_path),
        hooks_registry=hooks_registry,
    )
    
    print("\nType '/quit' to exit.\n")
    
    result = await machine.execute(input={})
    
    logger.info("=" * 60)
    logger.info("Chat ended")
    logger.info(f"Character: {result.get('character', 'Unknown')}")
    logger.info(f"Messages: {result.get('turns', 0)}")
    logger.info(f"API calls: {machine.total_api_calls}")
    logger.info(f"Cost: ${machine.total_cost:.4f}")
    logger.info("=" * 60)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Chat with a character from a V1/V2/V3 character card"
    )
    parser.add_argument("card", help="Path to character card (PNG/JSON)")
    
    # User identity
    parser.add_argument("--user", "-u", default="User", help="User name")
    parser.add_argument("--persona", "-p", help="User persona/description")
    parser.add_argument("--persona-file", help="JSON file with user persona")
    
    # Messages
    parser.add_argument("--messages-file", "-m", help="JSON file with initial messages")
    
    # Modes
    parser.add_argument("--no-system-prompt", action="store_true",
                       help="No system prompt (for Gemma, etc.)")
    parser.add_argument("--auto-user", "-a", action="store_true",
                       help="LLM-driven user responses (default: 1 turn)")
    parser.add_argument("--max-turns", "-t", type=int,
                       help="Max conversation turns for auto-user (default: 1)")
    
    args = parser.parse_args()
    
    # Default max_turns to 1 when auto_user is enabled
    max_turns = args.max_turns
    if args.auto_user and max_turns is None:
        max_turns = 1
    
    asyncio.run(run(
        card_path=args.card,
        user_name=args.user,
        user_persona=args.persona,
        persona_file=args.persona_file,
        messages_file=args.messages_file,
        no_system_prompt=args.no_system_prompt,
        auto_user=args.auto_user,
        max_turns=max_turns,
    ))


if __name__ == "__main__":
    main()
