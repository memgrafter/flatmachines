from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml
from jinja2 import Template

from flatmachines import MachineHooks


class IPDPlayerHooks(MachineHooks):
    """Hooks for player-machine routing/actions and optional debug output."""

    def __init__(self, debug_messages: Optional[bool] = None, debug_prompts: Optional[bool] = None):
        if debug_messages is None:
            debug_messages = self._is_truthy(os.getenv("IPD_DEBUG_MESSAGES", "false"))
        self.debug_messages = bool(debug_messages)

        if debug_prompts is None:
            env_val = os.getenv("IPD_DEBUG_PROMPTS")
            debug_prompts = self._is_truthy(env_val) if env_val is not None else self.debug_messages
        self.debug_prompts = bool(debug_prompts)

        self._agent_system_template = ""
        self._agent_user_template = ""
        self._load_agent_templates()

    def on_state_enter(self, state_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.debug_messages and state_name == "llm_decision":
            role = context.get("role", "Unknown")
            round_no = context.get("round", "?")
            rounds_total = context.get("rounds_total", "?")
            own_history = context.get("own_history", [])
            opp_history = context.get("opponent_history", [])
            opp_last = context.get("opponent_last_move")
            print(
                f"\n[DEBUG][AGENT INPUT] {role} round {round_no}/{rounds_total} "
                f"own={own_history} opp={opp_history} opp_last={opp_last}"
            )

            if self.debug_prompts:
                system_prompt, user_prompt = self._render_prompts_for_context(context)
                print(f"[DEBUG][PROMPT SYSTEM] {role}\n{system_prompt}")
                print(f"[DEBUG][PROMPT USER] {role}\n{user_prompt}")
        return context

    def on_state_exit(
        self,
        state_name: str,
        context: Dict[str, Any],
        output: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if self.debug_messages and state_name == "llm_decision":
            role = context.get("role", "Unknown")
            raw = context.get("decision_raw")
            content = output.get("content") if isinstance(output, dict) else output
            print(f"[DEBUG][AGENT OUTPUT] {role} content={content!r} mapped={raw!r}")
            print(f"[DEBUG][AGENT OUTPUT RAW] {role} output_obj={output!r}")
        return output

    def on_action(self, state_name: str, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "route_decision":
            return self._route_decision(context)
        if action_name == "choose_cooperate":
            return self._choose_cooperate(context)
        if action_name == "choose_defect":
            return self._choose_defect(context)
        return context

    def _route_decision(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raw = str(context.get("decision_raw") or "").strip()
        lowered = raw.lower()

        # Robust parsing for common outputs: "COOPERATE", "defect", "C", "D", etc.
        tokens = re.findall(r"[a-zA-Z]+", lowered)
        first = tokens[0] if tokens else ""
        next_state = "cooperate"  # safe default

        if first.startswith("d"):
            next_state = "defect"
        elif first.startswith("c"):
            next_state = "cooperate"
        elif "defect" in lowered or "betray" in lowered or " d " in f" {lowered} ":
            next_state = "defect"
        elif "cooperate" in lowered or "coop" in lowered or " c " in f" {lowered} ":
            next_state = "cooperate"

        context["next_state"] = next_state
        context["decision_normalized"] = next_state
        if self.debug_messages:
            print(f"[DEBUG][ROUTER] raw={raw!r} -> next_state={next_state!r}")
        return context

    @staticmethod
    def _choose_cooperate(context: Dict[str, Any]) -> Dict[str, Any]:
        context["move"] = "C"
        context["move_label"] = "cooperate"
        context["rationale"] = f"routed_from={context.get('decision_raw', '')}"
        return context

    @staticmethod
    def _choose_defect(context: Dict[str, Any]) -> Dict[str, Any]:
        context["move"] = "D"
        context["move_label"] = "defect"
        context["rationale"] = f"routed_from={context.get('decision_raw', '')}"
        return context

    def _load_agent_templates(self) -> None:
        """Load system/user templates from config/agent.yml for debug rendering."""
        try:
            agent_path = Path(__file__).resolve().parents[3] / "config" / "agent.yml"
            data = yaml.safe_load(agent_path.read_text(encoding="utf-8")) or {}
            agent_data = data.get("data", {}) if isinstance(data, dict) else {}
            self._agent_system_template = str(agent_data.get("system") or "")
            self._agent_user_template = str(agent_data.get("user") or "")
        except Exception:
            # Debug-only feature; keep runtime robust if file can't be read.
            self._agent_system_template = ""
            self._agent_user_template = ""

    def _render_prompts_for_context(self, context: Dict[str, Any]) -> Tuple[str, str]:
        input_data = {
            "role": context.get("role"),
            "round": context.get("round"),
            "rounds_total": context.get("rounds_total"),
            "own_history": context.get("own_history"),
            "opponent_history": context.get("opponent_history"),
            "opponent_last_move": context.get("opponent_last_move"),
        }

        if self._agent_system_template:
            system_prompt = Template(self._agent_system_template).render(input=input_data)
        else:
            system_prompt = "<system template unavailable>"

        if self._agent_user_template:
            user_prompt = Template(self._agent_user_template).render(input=input_data)
        else:
            user_prompt = "<user template unavailable>"

        return system_prompt, user_prompt

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}


class IPDMatchHooks(MachineHooks):
    """Hooks for match-level setup/scoring actions."""

    def on_action(self, state_name: str, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "init_match":
            return self._init_match(context)
        if action_name == "score_round":
            return self._score_round(context)
        return context

    def _init_match(self, context: Dict[str, Any]) -> Dict[str, Any]:
        rounds_total = self._to_int(context.get("rounds_total"), default=10)
        context["rounds_total"] = rounds_total
        context["round"] = 1
        context["done"] = False

        context["moves_a"] = []
        context["moves_b"] = []
        context["history"] = []
        context["totals"] = {"A": 0, "B": 0}
        context["cooperation_count"] = {"A": 0, "B": 0}
        context["defection_count"] = {"A": 0, "B": 0}
        context["cooperation_rate"] = {"A": 0.0, "B": 0.0}
        context["defection_rate"] = {"A": 0.0, "B": 0.0}
        context["last_move_a"] = None
        context["last_move_b"] = None
        context["last_round"] = None
        return context

    def _score_round(self, context: Dict[str, Any]) -> Dict[str, Any]:
        round_idx = self._to_int(context.get("round"), default=1)
        rounds_total = self._to_int(context.get("rounds_total"), default=10)

        move_a = self._canonical_move(context.get("move_a"))
        move_b = self._canonical_move(context.get("move_b"))

        score_a, score_b = self._payoff(move_a, move_b)

        moves_a = list(context.get("moves_a") or [])
        moves_b = list(context.get("moves_b") or [])
        moves_a.append(move_a)
        moves_b.append(move_b)
        context["moves_a"] = moves_a
        context["moves_b"] = moves_b

        totals = dict(context.get("totals") or {"A": 0, "B": 0})
        totals["A"] = self._to_int(totals.get("A"), default=0) + score_a
        totals["B"] = self._to_int(totals.get("B"), default=0) + score_b
        context["totals"] = totals

        cooperation_count = dict(context.get("cooperation_count") or {"A": 0, "B": 0})
        defection_count = dict(context.get("defection_count") or {"A": 0, "B": 0})

        if move_a == "C":
            cooperation_count["A"] = self._to_int(cooperation_count.get("A"), 0) + 1
        else:
            defection_count["A"] = self._to_int(defection_count.get("A"), 0) + 1

        if move_b == "C":
            cooperation_count["B"] = self._to_int(cooperation_count.get("B"), 0) + 1
        else:
            defection_count["B"] = self._to_int(defection_count.get("B"), 0) + 1

        context["cooperation_count"] = cooperation_count
        context["defection_count"] = defection_count

        history = list(context.get("history") or [])
        entry = {
            "round": round_idx,
            "move_a": move_a,
            "move_b": move_b,
            "score_a": score_a,
            "score_b": score_b,
            "total_a": totals["A"],
            "total_b": totals["B"],
            "decision_raw_a": context.get("decision_raw_a"),
            "decision_raw_b": context.get("decision_raw_b"),
        }
        history.append(entry)
        context["history"] = history
        context["last_round"] = entry
        context["last_move_a"] = move_a
        context["last_move_b"] = move_b

        rounds_played = max(1, len(history))
        context["cooperation_rate"] = {
            "A": round(cooperation_count["A"] / rounds_played, 3),
            "B": round(cooperation_count["B"] / rounds_played, 3),
        }
        context["defection_rate"] = {
            "A": round(defection_count["A"] / rounds_played, 3),
            "B": round(defection_count["B"] / rounds_played, 3),
        }

        done = round_idx >= rounds_total
        context["done"] = done
        if not done:
            context["round"] = round_idx + 1

        return context

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _canonical_move(value: Any) -> str:
        raw = str(value or "").strip().upper()
        if raw.startswith("D") or "DEFECT" in raw:
            return "D"
        return "C"

    @staticmethod
    def _payoff(move_a: str, move_b: str) -> Tuple[int, int]:
        # T=5, R=3, P=1, S=0
        if move_a == "C" and move_b == "C":
            return 3, 3
        if move_a == "D" and move_b == "C":
            return 5, 0
        if move_a == "C" and move_b == "D":
            return 0, 5
        return 1, 1
