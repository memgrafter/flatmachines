"""
OTF Agent Hooks

Provides:
- parse_generator_spec: Deterministically parse generator plain-text spec
- parse_supervisor_review: Deterministically parse supervisor decision
- human_review_otf: Human-in-the-loop review of supervisor analysis
- otf_execute: Execute the approved OTF agent
"""

import json
import os
import re
import asyncio
from typing import Any, Dict, Optional

from flatmachines import MachineHooks
from flatagents import FlatAgent, get_logger
from flatagents.profiles import load_profiles_from_file

# Allow nested event loops for running async code from sync hooks
import nest_asyncio
nest_asyncio.apply()

logger = get_logger(__name__)


class UserQuit(Exception):
    """Raised when the human reviewer chooses to quit the demo."""


class OTFAgentHooks(MachineHooks):
    """Hooks for On-The-Fly agent execution with human-in-the-loop."""

    def __init__(self, profiles_file: Optional[str] = None):
        self.metrics = {
            "agents_generated": 0,
            "agents_executed": 0,
            "supervisor_rejections": 0,
            "human_denials": 0,
        }

        self._profiles_file = os.path.abspath(profiles_file) if profiles_file else None
        self._profiles_dict = None

        if self._profiles_file and os.path.exists(self._profiles_file):
            try:
                self._profiles_dict = load_profiles_from_file(self._profiles_file)
            except Exception as e:
                logger.warning(f"Failed to load profiles from {self._profiles_file}: {e}")

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom actions."""
        if action_name == "parse_generator_spec":
            return self._parse_generator_spec(context)
        if action_name == "parse_supervisor_review":
            return self._parse_supervisor_review(context)
        if action_name == "human_review_otf":
            return self._human_review_otf(context)
        if action_name == "otf_execute":
            return self._otf_execute(context)
        return context

    def _normalize_temperature(self, value: Any, default: float = 0.6) -> float:
        """Normalize temperature to profile-friendly 0.6 or 1.0."""
        try:
            temp = float(value)
        except (TypeError, ValueError):
            temp = default
        return 1.0 if temp >= 0.8 else 0.6

    def _to_int(self, value: Any, default: int = 0) -> int:
        """Best-effort integer coercion for machine context values."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_output_fields_block(self, text: str) -> Dict[str, Any]:
        """Parse Output Fields section from generator text into a dict."""
        block = (text or "").strip()
        if not block:
            return {"content": "The creative writing output"}

        # Accept JSON object if model provided one
        if block.startswith("{"):
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict) and parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # Parse bullet/list key-value lines
        fields: Dict[str, Any] = {}
        for line in block.splitlines():
            m = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$", line)
            if m:
                key = m.group(1)
                desc = m.group(2).strip()
                fields[key] = desc

        if not fields:
            fields = {"content": "The creative writing output"}

        return fields

    def _parse_generator_spec(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministically parse generator output (plain text labeled sections)."""
        raw = str(context.get("raw_generator") or "")

        name = None
        system_lines = []
        user_lines = []
        output_lines = []
        temperature = None
        current_section = None

        for line in raw.replace("\r\n", "\n").split("\n"):
            m_name = re.match(r"^\s*Name\s*:\s*(.*)$", line, re.IGNORECASE)
            if m_name:
                name = m_name.group(1).strip() or name
                current_section = None
                continue

            m_system = re.match(r"^\s*System Prompt\s*:\s*(.*)$", line, re.IGNORECASE)
            if m_system:
                current_section = "system"
                first = m_system.group(1).rstrip()
                if first:
                    system_lines.append(first)
                continue

            m_user = re.match(r"^\s*User Prompt Template\s*:\s*(.*)$", line, re.IGNORECASE)
            if m_user:
                current_section = "user"
                first = m_user.group(1).rstrip()
                if first:
                    user_lines.append(first)
                continue

            m_temp = re.match(r"^\s*Temperature\s*:\s*(.*)$", line, re.IGNORECASE)
            if m_temp:
                temperature = m_temp.group(1).strip()
                current_section = None
                continue

            m_output = re.match(r"^\s*Output Fields\s*:\s*(.*)$", line, re.IGNORECASE)
            if m_output:
                current_section = "output"
                first = m_output.group(1).rstrip()
                if first:
                    output_lines.append(first)
                continue

            if current_section == "system":
                system_lines.append(line)
            elif current_section == "user":
                user_lines.append(line)
            elif current_section == "output":
                output_lines.append(line)

        parsed_name = (name or "otf-agent").strip()
        parsed_system = "\n".join(system_lines).strip() or "You are a helpful creative writer."
        parsed_user = "\n".join(user_lines).strip() or "{{ input.task }}"
        parsed_temp = self._normalize_temperature(temperature, default=0.6)
        parsed_output_fields = self._parse_output_fields_block("\n".join(output_lines))

        # Ensure task placeholder exists for proper task injection
        if "<<input.task>>" not in parsed_user and "{{ input.task }}" not in parsed_user:
            if parsed_user:
                parsed_user = f"{parsed_user}\n\n{{{{ input.task }}}}"
            else:
                parsed_user = "{{ input.task }}"

        context["otf_name"] = parsed_name
        context["otf_system"] = parsed_system
        context["otf_user"] = parsed_user
        context["otf_temperature"] = parsed_temp
        context["otf_output_fields"] = parsed_output_fields

        # output_to_context Jinja renderings are strings; normalize loop counters
        # so transition comparisons like ">=" operate on numbers.
        context["generation_attempts"] = self._to_int(context.get("generation_attempts"), 0)
        context["max_attempts"] = self._to_int(context.get("max_attempts"), 3)

        if not raw.strip():
            context["supervisor_concerns"] = "Generator returned empty text; used default fallbacks."

        return context

    def _extract_supervisor_block(self, text: str, label: str, next_label: Optional[str] = None) -> str:
        """Extract text after LABEL: until NEXT_LABEL: (or end)."""
        if next_label:
            pattern = rf"(?is)^\s*{re.escape(label)}\s*:\s*(.*?)^\s*{re.escape(next_label)}\s*:"
        else:
            pattern = rf"(?is)^\s*{re.escape(label)}\s*:\s*(.*)$"
        match = re.search(pattern, text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _parse_supervisor_review(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministically parse supervisor result from required plain-text format."""
        raw = str(context.get("raw_supervisor") or "")

        decision_match = re.search(r"(?im)^\s*DECISION\s*:\s*(APPROVE|REJECT)\b", raw)
        if decision_match:
            approved = decision_match.group(1).upper() == "APPROVE"
        else:
            # Conservative fallback if format is off
            if re.search(r"(?i)\breject\b", raw):
                approved = False
            elif re.search(r"(?i)\bapprove\b", raw):
                approved = True
            else:
                approved = False

        analysis = self._extract_supervisor_block(raw, "ANALYSIS", "CONCERNS")
        concerns = self._extract_supervisor_block(raw, "CONCERNS")

        if not analysis:
            analysis = raw.strip() or "(no supervisor analysis returned)"

        normalized_concerns = (concerns or "").strip()
        if normalized_concerns.lower() in {"none", "(none)", "n/a", "no concerns"}:
            normalized_concerns = ""

        if not approved and not normalized_concerns:
            normalized_concerns = "Supervisor rejected the spec but did not provide explicit concerns."

        context["supervisor_approved"] = approved
        context["supervisor_analysis"] = analysis
        context["supervisor_concerns"] = normalized_concerns
        return context

    def _human_review_otf(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Human reviews the supervisor's analysis of the OTF agent spec.

        If supervisor rejected: Human can only acknowledge (no override)
        If supervisor approved: Human can approve or deny
        """
        print("\n" + "=" * 70)
        print("OTF AGENT REVIEW")
        print("=" * 70)

        # Show the original task
        print(f"\n📋 ORIGINAL TASK:")
        print(f"   {context.get('task', '(unknown)')}")

        # Show the generated agent spec from individual fields
        name = context.get("otf_name", "unnamed")
        system = context.get("otf_system", "(none)")
        user = context.get("otf_user", "(none)")
        temperature = context.get("otf_temperature", "N/A")

        print(f"\n🤖 GENERATED AGENT: {name}")
        print("-" * 50)
        print(f"Temperature: {temperature}")
        system_text = str(system) if system else "(none)"
        print(f"\nSystem Prompt:\n{system_text}")
        user_text = str(user) if user else "(none)"
        task_text = str(context.get("task", ""))
        user_rendered = user_text.replace("<<input.task>>", task_text).replace("{{ input.task }}", task_text)
        user_display = user_rendered if user_rendered else "(none)"
        print(f"\nUser Prompt Template:\n{user_display}")

        # Show supervisor's analysis
        print("\n" + "-" * 50)
        supervisor_approved = context.get("supervisor_approved", False)

        if supervisor_approved:
            print("✅ SUPERVISOR APPROVED")
        else:
            print("❌ SUPERVISOR REJECTED")
            self.metrics["supervisor_rejections"] += 1

        print(f"\n📊 ANALYSIS:\n{context.get('supervisor_analysis', '(none)')}")

        if context.get("supervisor_concerns"):
            print(f"\n⚠️  CONCERNS:\n{context.get('supervisor_concerns')}")

        print("-" * 50)

        # Different options based on supervisor decision
        if supervisor_approved:
            print("\nThe supervisor approved this agent.")
            response = input("Your decision: [a]pprove / [d]eny / [q]uit: ").strip().lower()

            if response in ("a", "approve", ""):
                context["human_approved"] = True
                context["human_acknowledged"] = True
                print("✓ Approved! Agent will be executed.")
            elif response in ("q", "quit"):
                print("Quitting...")
                raise UserQuit()
            else:
                context["human_approved"] = False
                context["human_acknowledged"] = True
                self.metrics["human_denials"] += 1
                print("✗ Denied. Will regenerate agent.")
        else:
            print("\nThe supervisor rejected this agent. You can only acknowledge.")
            response = input("Press Enter to acknowledge and regenerate, or 'q' to quit: ").strip().lower()

            if response in ("q", "quit"):
                print("Quitting...")
                raise UserQuit()

            context["human_approved"] = False
            context["human_acknowledged"] = True
            print("→ Acknowledged. Will regenerate agent with feedback.")

        print("=" * 70 + "\n")
        return context

    def _otf_execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create and execute the OTF agent from the approved spec fields."""
        name = context.get("otf_name", "otf-agent")
        system = context.get("otf_system", "You are a helpful creative writer.")
        user = context.get("otf_user", "{{ input.task }}")
        temperature = self._normalize_temperature(context.get("otf_temperature", 0.6), default=0.6)

        print("\n" + "=" * 70)
        print(f"🚀 EXECUTING OTF AGENT: {name}")
        print("=" * 70)

        profile_name = "creative" if temperature == 0.6 else "default"
        normalized_user = str(user).replace("<<input.task>>", "{{ input.task }}").strip()

        # IMPORTANT: Do not force output schema here.
        # Keeping this as plain-text output avoids JSON-mode coupling.
        agent_config = {
            "spec": "flatagent",
            "spec_version": "2.0.0",
            "data": {
                "name": name,
                "model": profile_name,
                "system": system,
                "user": normalized_user,
            },
        }

        try:
            profiles_dict = self._profiles_dict or context.get("_profiles")
            agent = FlatAgent(config_dict=agent_config, profiles_dict=profiles_dict)
            self.metrics["agents_generated"] += 1

            result = asyncio.run(agent.call(task=context.get("task", "")))

            if result.error:
                error_type = getattr(result.error, "error_type", "AgentError")
                message = getattr(result.error, "message", str(result.error))
                error_text = f"{error_type}: {message}"
                context["otf_result"] = {"error": error_text}
                print(f"\n❌ Error: {error_text}")
                print("=" * 70 + "\n")
                return context

            self.metrics["agents_executed"] += 1

            content = (result.content or "").strip()
            context["otf_result"] = {"content": content or "(empty response)"}

            print("\n📝 OUTPUT:")
            print("-" * 50)
            print(context["otf_result"]["content"])
            print("-" * 50)

        except Exception as e:
            logger.error(f"OTF agent execution failed: {e}")
            context["otf_result"] = {"error": str(e)}
            print(f"\n❌ Error: {e}")

        print("=" * 70 + "\n")
        return context

    def get_metrics(self) -> Dict[str, Any]:
        """Return collected metrics."""
        return self.metrics.copy()
