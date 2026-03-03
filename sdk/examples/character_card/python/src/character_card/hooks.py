"""
Character Card Hooks

Provides hooks for loading character cards and managing chat interaction.
Follows SillyTavern chat completion message format.

Supports:
- User persona (description)
- LLM-driven user agent for automated responses
- Injected messages array from file
- Script-fed responses
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from flatmachines import MachineHooks
from flatagents import FlatAgent, get_logger
from .card_parser import parse_card

logger = get_logger(__name__)


class CharacterCardHooks(MachineHooks):
    """
    Hooks for character card chat workflow.
    
    Message format follows SillyTavern conventions:
    - Messages alternate user/assistant
    - If first_mes exists, starts with "[Start]" user message
    - post_history_instructions appended to user message (not saved)
    - Optional no_system_prompt mode for models like Gemma
    - Optional LLM-driven user agent
    - Optional persona and messages from JSON files
    """
    
    def __init__(
        self,
        card_path: str,
        user_name: str = "User",
        no_system_prompt: bool = False,
        user_persona: Optional[str] = None,
        persona_file: Optional[str] = None,
        messages_file: Optional[str] = None,
        auto_user: bool = False,
        script_responses: Optional[List[str]] = None,
        max_turns: Optional[int] = None,
    ):
        """
        Initialize hooks.
        
        Args:
            card_path: Path to character card file
            user_name: Name used for user messages
            no_system_prompt: If True, prepend system context to first user message
            user_persona: User description/persona text
            persona_file: Path to JSON file with persona {"name": "...", "description": "..."}
            messages_file: Path to JSON file with messages array to inject
            auto_user: If True, use LLM to generate user responses
            script_responses: List of pre-scripted user responses (used in order)
            max_turns: Maximum conversation turns before auto-quit (for auto-user)
        """
        self.card_path = card_path
        self.user_name = user_name
        self.no_system_prompt = no_system_prompt
        self.user_persona = user_persona
        self.persona_file = persona_file
        self.messages_file = messages_file
        self.auto_user = auto_user
        self.script_responses = list(script_responses) if script_responses else []
        self.script_index = 0
        self.max_turns = max_turns
        self.turn_count = 0
        
        self.card_data = None
        self.user_agent: Optional[FlatAgent] = None
    
    async def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "load_card":
            return self._load_card(context)
        elif action_name == "show_greeting":
            return self._show_greeting(context)
        elif action_name == "get_user_input":
            return await self._get_user_input(context)
        elif action_name == "update_chat_history":
            return self._update_chat_history(context)
        return context
    
    def _load_persona(self) -> tuple[str, Optional[str]]:
        """Load persona from file or use provided values."""
        name = self.user_name
        persona = self.user_persona
        
        if self.persona_file and Path(self.persona_file).exists():
            try:
                with open(self.persona_file, encoding='utf-8') as f:
                    data = json.load(f)
                    name = data.get('name', name)
                    persona = data.get('description', persona)
            except Exception as e:
                logger.warning(f"Failed to load persona file: {e}")
        
        return name, persona
    
    def _load_messages(self) -> List[Dict[str, str]]:
        """Load initial messages from file."""
        messages = []
        
        if self.messages_file and Path(self.messages_file).exists():
            try:
                with open(self.messages_file, encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        messages = data
                    elif isinstance(data, dict) and 'messages' in data:
                        messages = data['messages']
            except Exception as e:
                logger.warning(f"Failed to load messages file: {e}")
        
        return messages
    
    def _load_card(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Load character card and populate context."""
        self.card_data = parse_card(self.card_path)
        
        # Load persona
        user_name, user_persona = self._load_persona()
        self.user_name = user_name
        
        # Character data
        context["card_name"] = self.card_data["name"]
        context["card_description"] = self.card_data["description"]
        context["card_personality"] = self.card_data["personality"]
        context["card_scenario"] = self.card_data["scenario"]
        context["card_system_prompt"] = self.card_data["system_prompt"]
        context["card_first_mes"] = self.card_data["first_mes"]
        context["card_mes_example"] = self.card_data["mes_example"]
        context["post_history_instructions"] = self.card_data["post_history_instructions"]
        
        # User/settings
        context["user_name"] = user_name
        context["user_persona"] = user_persona
        context["no_system_prompt"] = self.no_system_prompt
        context["auto_user"] = self.auto_user
        
        # Load injected messages or start fresh
        context["messages"] = self._load_messages()
        
        # Load user agent if auto mode
        if self.auto_user:
            agent_path = Path(__file__).parent.parent.parent.parent / 'config' / 'user_agent.yml'
            self.user_agent = FlatAgent(config_file=str(agent_path))
        
        # Display info
        logger.info("-" * 60)
        logger.info(f"Character: {self.card_data['name']}")
        if self.card_data.get('creator'):
            logger.info(f"By: {self.card_data['creator']}")
        logger.info(f"User: {user_name}")
        if user_persona:
            logger.info(f"Persona: {user_persona[:100]}{'...' if len(user_persona) > 100 else ''}")
        if context["messages"]:
            logger.info(f"Injected messages: {len(context['messages'])}")
        if self.auto_user:
            max_str = f", max {self.max_turns} turns" if self.max_turns else ""
            logger.info(f"Mode: Auto-user (LLM-driven{max_str})")
        elif self.script_responses:
            logger.info(f"Mode: Scripted ({len(self.script_responses)} responses)")
        logger.info("-" * 60)
        
        return context
    
    def _show_greeting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Display character's first message and set up message array.
        
        If messages were injected, skip the greeting setup.
        Otherwise, if first_mes exists:
        - Add "[Start]" as first user message
        - Add first_mes as first assistant message
        """
        # Skip if messages were injected
        if context["messages"]:
            logger.info("Using injected messages")
            # Show last few messages
            for msg in context["messages"][-4:]:
                role = context["user_name"] if msg["role"] == "user" else context["card_name"]
                print(f"{role}: {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")
            print()
            return context
        
        first_mes = context.get("card_first_mes", "")
        name = context.get("card_name", "Character")
        
        if first_mes:
            # Start with user message to ensure alternation
            context["messages"].append({
                "role": "user",
                "content": "[Start]"
            })
            context["messages"].append({
                "role": "assistant",
                "content": first_mes
            })
            print(f"\n{name}: {first_mes}\n")
        
        return context
    
    async def _generate_user_response(self, context: Dict[str, Any]) -> str:
        """Generate user response via LLM agent."""
        if not self.user_agent:
            return "/quit"

        response = await self.user_agent.call(
            user_name=context.get("user_name", "User"),
            user_persona=context.get("user_persona", ""),
            card_name=context.get("card_name", "Character"),
            card_description=context.get("card_description", ""),
            chat_messages=context.get("messages", []),
        )

        if response.error:
            logger.error(f"Auto-user LLM error: {response.error.message}")
            return "/quit"

        if isinstance(response.output, dict):
            text = response.output.get("response") or response.output.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()

        if isinstance(response.content, str) and response.content.strip():
            return response.content.strip()

        return "/quit"

    async def _get_user_input(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get user input from terminal, script, or LLM agent."""
        import asyncio

        # Scripted mode - use next response from script
        if self.script_responses and self.script_index < len(self.script_responses):
            response = self.script_responses[self.script_index]
            self.script_index += 1
            print(f"{self.user_name}: {response}")
            context["user_message"] = response
            return context

        # Auto-user mode - generate via LLM
        if self.auto_user and self.user_agent:
            # Check max turns (0 means unlimited)
            if self.max_turns and self.max_turns > 0 and self.turn_count >= self.max_turns:
                logger.info(f"Reached max turns: {self.max_turns}")
                context["user_message"] = "/quit"
                return context

            # Delay between rounds in unlimited mode
            if self.max_turns == 0 and self.turn_count > 0:
                await asyncio.sleep(2)

            self.turn_count += 1

            try:
                response = await self._generate_user_response(context)
                print(f"{self.user_name}: {response}")
                context["user_message"] = response
                return context
            except Exception as e:
                logger.error(f"Auto-user error: {e}")
                context["user_message"] = "/quit"
                return context

        # Interactive mode - prompt user
        try:
            user_input = input(f"{self.user_name}: ").strip()
            context["user_message"] = user_input if user_input else "/quit"
        except (EOFError, KeyboardInterrupt):
            context["user_message"] = "/quit"
            print()

        return context
    
    def _update_chat_history(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update chat history and display response.
        
        Note: post_history_instructions is NOT saved to messages array.
        """
        user_msg = context.get("user_message", "")
        assistant_msg = context.get("assistant_message", "")
        name = context.get("card_name", "Character")
        
        context["messages"].append({"role": "user", "content": user_msg})
        context["messages"].append({"role": "assistant", "content": assistant_msg})
        
        print(f"\n{name}: {assistant_msg}\n")
        
        return context
