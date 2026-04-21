"""
MDAP Hooks for FlatMachine.

Deprecated: the runnable MDAP example now uses the built-in `mdap_voting`
execution type declared in `config/machine.yml`, not these hooks.

Provides multi-sampling and voting hooks for MDAP-style orchestration.
The voting logic (first_to_ahead_by_k) runs as part of agent execution.
"""

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import jsonschema

from flatmachines import MachineHooks
from flatagents import FlatAgent

logger = logging.getLogger(__name__)


@dataclass
class MDAPConfig:
    """MDAP-specific configuration."""
    k_margin: int = 3
    max_candidates: int = 10
    max_response_tokens: int = 2048


@dataclass
class MDAPMetrics:
    """Execution metrics collected during MDAP runs."""
    total_samples: int = 0
    total_red_flags: int = 0
    red_flags_by_reason: Dict[str, int] = field(default_factory=dict)
    samples_per_step: List[int] = field(default_factory=list)

    def record_red_flag(self, reason: str):
        self.total_red_flags += 1
        self.red_flags_by_reason[reason] = self.red_flags_by_reason.get(reason, 0) + 1


class MDAPHooks(MachineHooks):
    """
    MDAP voting hooks for FlatMachine.
    
    Implements first-to-ahead-by-k voting from the MAKER paper.
    """

    def __init__(self, config: Optional[MDAPConfig] = None):
        self.config = config or MDAPConfig()
        self.metrics = MDAPMetrics()
        self._patterns: Dict[str, Tuple[re.Pattern, str]] = {}
        self._validation_schema: Optional[Dict] = None
        self._current_agent: Optional[FlatAgent] = None

    def configure_from_agent(self, agent: FlatAgent):
        """Load parsing and validation config from agent metadata."""
        self._current_agent = agent
        
        # Load MDAP config
        mdap_config = agent.metadata.get('mdap', {})
        self.config = MDAPConfig(
            k_margin=mdap_config.get('k_margin', 3),
            max_candidates=mdap_config.get('max_candidates', 10),
            max_response_tokens=mdap_config.get('max_response_tokens', 2048),
        )

        # Load parsing patterns
        parsing_config = agent.metadata.get('parsing', {})
        self._patterns = {}
        for field_name, field_config in parsing_config.items():
            pattern = field_config.get('pattern')
            if pattern:
                self._patterns[field_name] = (
                    re.compile(pattern, re.DOTALL),
                    field_config.get('type', 'str')
                )

        # Load validation schema
        self._validation_schema = agent.metadata.get('validation', None)

    def _parse_response(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response using regex patterns."""
        if not self._patterns:
            return None

        result = {}
        for field_name, (pattern, field_type) in self._patterns.items():
            match = pattern.search(content)
            if match:
                value = match.group(1)
                if field_type == 'json':
                    try:
                        result[field_name] = json.loads(value)
                    except json.JSONDecodeError:
                        return None
                elif field_type == 'int':
                    try:
                        result[field_name] = int(value)
                    except ValueError:
                        return None
                else:
                    result[field_name] = value
            else:
                return None

        return result

    def _validate_parsed(self, parsed: Dict[str, Any]) -> bool:
        """Validate parsed result against JSON Schema."""
        if not self._validation_schema:
            return True

        try:
            jsonschema.validate(instance=parsed, schema=self._validation_schema)
            return True
        except jsonschema.ValidationError:
            return False

    def _check_red_flags(self, content: str, parsed: Optional[Dict[str, Any]]) -> Optional[str]:
        """Check response for red flags per MAKER paper."""
        if parsed is None:
            return "format_error"

        if not self._validate_parsed(parsed):
            return "validation_failed"

        estimated_tokens = len(content) // 4
        if estimated_tokens > self.config.max_response_tokens:
            return "length_exceeded"

        return None

    async def voting_call(self, agent: FlatAgent, input_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Multi-sample with voting - replaces single agent call.
        
        Returns the winning parsed response or None.
        """
        import litellm

        self.configure_from_agent(agent)

        votes: Counter = Counter()
        responses: Dict[str, Dict[str, Any]] = {}
        num_samples = 0

        for _ in range(self.config.max_candidates):
            try:
                # Render prompts
                system_prompt = agent._render_system_prompt(input_data)
                user_prompt = agent._render_user_prompt(input_data)

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]

                response = await litellm.acompletion(
                    model=agent.model,
                    messages=messages,
                    temperature=agent.temperature,
                    max_tokens=agent.max_tokens,
                )

                agent.total_api_calls += 1
                num_samples += 1
                self.metrics.total_samples += 1

                content = response.choices[0].message.content
                if content is None:
                    continue

                # Parse and check
                parsed = self._parse_response(content)
                flag_reason = self._check_red_flags(content, parsed)
                
                if flag_reason:
                    self.metrics.record_red_flag(flag_reason)
                    continue

                # Vote
                key = json.dumps(parsed, sort_keys=True)
                votes[key] += 1
                responses[key] = parsed

                # Check for winner
                if votes[key] >= self.config.k_margin:
                    self.metrics.samples_per_step.append(num_samples)
                    return parsed

                if len(votes) >= 2:
                    top = votes.most_common(2)
                    if top[0][1] - top[1][1] >= self.config.k_margin:
                        self.metrics.samples_per_step.append(num_samples)
                        return responses[top[0][0]]

            except Exception as e:
                logger.warning(f"Sample failed: {e}")
                continue

        # Majority fallback
        self.metrics.samples_per_step.append(num_samples)
        if votes:
            winner_key = votes.most_common(1)[0][0]
            return responses[winner_key]

        return None

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"MDAP: Entering state {state_name}")
        return context

    def on_transition(self, from_state: str, to_state: str, context: Dict[str, Any]) -> str:
        logger.info(f"MDAP: {from_state} -> {to_state}")
        return to_state

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "total_samples": self.metrics.total_samples,
            "total_red_flags": self.metrics.total_red_flags,
            "red_flags_by_reason": self.metrics.red_flags_by_reason,
            "samples_per_step": self.metrics.samples_per_step,
        }
