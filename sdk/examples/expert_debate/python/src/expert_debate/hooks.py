"""Hooks for the expert_debate FlatMachine example."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from flatmachines import MachineHooks


class ExpertDebateHooks(MachineHooks):
    """Implements interactive and non-LLM action states for expert_debate."""

    def __init__(self, output_dir: str | None = None):
        # .../expert_debate/python/src/expert_debate/hooks.py -> parents[3] == .../expert_debate
        base_dir = Path(__file__).resolve().parents[3]
        self.default_output_dir = Path(output_dir) if output_dir else base_dir / "output"

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "bootstrap_session":
            return self._bootstrap_session(context)
        if action_name == "collect_topic":
            return self._collect_topic(context)
        if action_name == "collect_quiz_response":
            return self._collect_quiz_response(context)
        if action_name == "build_master_prompts":
            return self._build_master_prompts(context)
        if action_name == "initialize_debate_state":
            return self._initialize_debate_state(context)
        if action_name == "set_round_focus":
            return self._set_round_focus(context)
        if action_name == "record_round":
            return self._record_round(context)
        if action_name == "render_markdown":
            return self._render_markdown(context)
        if action_name == "write_markdown_file":
            return self._write_markdown_file(context)
        return context

    def _bootstrap_session(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not context.get("session_id"):
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            context["session_id"] = f"{ts}-{uuid4().hex[:8]}"

        context["round_count"] = self._clamp_round_count(context.get("round_count", 2))
        context["must_cover"] = self._ensure_list(context.get("must_cover"))
        context["avoid"] = self._ensure_list(context.get("avoid"))
        context.setdefault("transcript", [])
        return context

    def _collect_topic(self, context: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(context.get("topic") or "").strip()
        while not topic:
            topic = input("Debate topic: ").strip()
        context["topic"] = topic
        return context

    def _collect_quiz_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        question = str(context.get("latest_quiz_question") or "").strip()
        if question:
            print("\n" + "=" * 72)
            print("DEBATE REFINEMENT QUESTION")
            print("=" * 72)
            print(question)
            print("=" * 72)

        response = input("Your answer: ").strip()
        ready = input("Satisfied and ready to run the debate? [y/N]: ").strip().lower()

        context["latest_user_response"] = response
        context["user_satisfied"] = ready in {"y", "yes"}
        return context

    def _build_master_prompts(self, context: Dict[str, Any]) -> Dict[str, Any]:
        topic = context.get("topic", "")
        start_with = context.get("start_with", "")

        a_name = context.get("master_a_name", "Master A")
        a_domain = context.get("master_a_domain", "")
        a_viewpoint = context.get("master_a_viewpoint", "")

        b_name = context.get("master_b_name", "Master B")
        b_domain = context.get("master_b_domain", "")
        b_viewpoint = context.get("master_b_viewpoint", "")

        context["master_a_prompt_template"] = (
            f"You are a master of {a_domain}. Engage in an educational debate on '{topic}' with {b_name}. "
            f"Your stable viewpoint: {a_viewpoint}. "
            f"Opening frame: {start_with}. "
            "You are teaching the reader by clarifying terms, tradeoffs, and implications. "
            "Do not concede your core stance or switch perspectives."
        )

        context["master_b_prompt_template"] = (
            f"You are a master of {b_domain}. Engage in an educational debate on '{topic}' with {a_name}. "
            f"Your stable viewpoint: {b_viewpoint}. "
            f"Opening frame: {start_with}. "
            "You are teaching the reader by clarifying terms, tradeoffs, and implications. "
            "Do not concede your core stance or switch perspectives."
        )
        return context

    def _initialize_debate_state(self, context: Dict[str, Any]) -> Dict[str, Any]:
        round_count = self._clamp_round_count(context.get("round_count", 2))
        context["round_count"] = round_count
        context["round_index"] = 1
        context["rounds_remaining"] = round_count
        context["topic_slices"] = self._ensure_list(context.get("topic_slices"))
        context["transcript"] = []
        context["last_master_a_statement"] = ""
        context["last_master_b_statement"] = ""
        context["debate_complete"] = round_count < 1
        return context

    def _set_round_focus(self, context: Dict[str, Any]) -> Dict[str, Any]:
        round_count = self._clamp_round_count(context.get("round_count", 2))
        round_index = self._as_int(context.get("round_index", 1), default=1)

        if round_index > round_count:
            context["debate_complete"] = True
            context["rounds_remaining"] = 0
            return context

        slices = self._ensure_list(context.get("topic_slices"))
        idx = round_index - 1
        if idx < len(slices):
            focus = slices[idx]
        else:
            focus = f"Round {round_index}: core tradeoffs and implications of {context.get('topic', 'the topic')}"

        context["current_round_focus"] = focus
        context["rounds_remaining"] = max(round_count - round_index + 1, 0)
        context["debate_complete"] = False
        return context

    def _record_round(self, context: Dict[str, Any]) -> Dict[str, Any]:
        transcript: List[Dict[str, Any]] = self._ensure_dict_list(context.get("transcript"))

        round_count = self._clamp_round_count(context.get("round_count", 2))
        round_index = self._as_int(context.get("round_index", 1), default=1)

        transcript.append(
            {
                "round": round_index,
                "focus": context.get("current_round_focus", ""),
                "master_a_name": context.get("master_a_name", "Master A"),
                "master_a_statement": context.get("current_master_a_statement", ""),
                "master_b_name": context.get("master_b_name", "Master B"),
                "master_b_statement": context.get("current_master_b_statement", ""),
            }
        )

        context["transcript"] = transcript
        context["last_master_a_statement"] = context.get("current_master_a_statement", "")
        context["last_master_b_statement"] = context.get("current_master_b_statement", "")

        next_round = round_index + 1
        context["round_index"] = next_round
        context["rounds_remaining"] = max(round_count - next_round + 1, 0)
        context["debate_complete"] = next_round > round_count
        return context

    def _render_markdown(self, context: Dict[str, Any]) -> Dict[str, Any]:
        transcript = self._ensure_dict_list(context.get("transcript"))

        lines: List[str] = []
        lines.append(f"# Expert Debate: {context.get('topic', '')}")
        lines.append("")
        lines.append(f"- Session ID: `{context.get('session_id', '')}`")
        lines.append(f"- Audience: {context.get('audience', '')}")
        lines.append(f"- Learning goal: {context.get('learning_goal', '')}")
        lines.append(f"- Opening frame: {context.get('start_with', '')}")
        lines.append("")

        lines.append("## Masters")
        lines.append("")
        lines.append(
            f"- **{context.get('master_a_name', 'Master A')}** "
            f"({context.get('master_a_domain', '')}) — {context.get('master_a_viewpoint', '')}"
        )
        lines.append(
            f"- **{context.get('master_b_name', 'Master B')}** "
            f"({context.get('master_b_domain', '')}) — {context.get('master_b_viewpoint', '')}"
        )
        lines.append("")

        lines.append("## Dialogue")
        lines.append("")

        for item in transcript:
            lines.append(f"### Round {item.get('round', '?')}: {item.get('focus', '')}")
            lines.append("")
            lines.append(f"**{item.get('master_a_name', 'Master A')}:**")
            lines.append("")
            lines.append(str(item.get("master_a_statement", "")).strip())
            lines.append("")
            lines.append(f"**{item.get('master_b_name', 'Master B')}:**")
            lines.append("")
            lines.append(str(item.get("master_b_statement", "")).strip())
            lines.append("")

        context["markdown"] = "\n".join(lines).strip() + "\n"
        return context

    def _write_markdown_file(self, context: Dict[str, Any]) -> Dict[str, Any]:
        output_dir = context.get("output_dir")
        out = Path(output_dir) if output_dir else self.default_output_dir
        out.mkdir(parents=True, exist_ok=True)

        topic = str(context.get("topic") or "debate")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.lower()).strip("-")[:60] or "topic"
        session_id = str(context.get("session_id") or uuid4().hex[:8])

        path = out / f"expert_debate_{session_id}_{slug}.md"
        path.write_text(str(context.get("markdown") or ""), encoding="utf-8")

        context["file_path"] = str(path)
        return context

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return int(value)
            return int(str(value).strip())
        except Exception:
            return default

    def _clamp_round_count(self, value: Any) -> int:
        n = self._as_int(value, default=2)
        return max(1, min(20, n))

    @staticmethod
    def _ensure_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, tuple):
            return [str(v).strip() for v in value if str(v).strip()]

        text = str(value).strip()
        if not text:
            return []

        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(v).strip() for v in decoded if str(v).strip()]
        except Exception:
            pass

        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]

        return [text]

    @staticmethod
    def _ensure_dict_list(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            out: List[Dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    out.append(item)
            return out

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    return [item for item in decoded if isinstance(item, dict)]
            except Exception:
                return []

        return []
