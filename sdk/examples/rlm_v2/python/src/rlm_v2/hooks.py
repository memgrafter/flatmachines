"""Hooks and recursive invocation logic for the RLM v2 machine."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Protocol

from flatmachines import FlatMachine, MachineHooks, get_logger

try:
    from .repl import REPLRegistry, extract_repl_blocks, truncate_text
except ImportError:  # pragma: no cover
    from repl import REPLRegistry, extract_repl_blocks, truncate_text

logger = get_logger(__name__)


class TerminationStrategy(Protocol):
    """Strategy for determining final completion state."""

    def evaluate(self, session) -> tuple[bool, Any]:
        ...


class StrictFinalStrategy:
    """Stop only when REPL variable `Final` exists and is not None."""

    def __init__(self, final_var: str = "Final"):
        self.final_var = final_var

    def evaluate(self, session) -> tuple[bool, Any]:
        if session.has_variable(self.final_var):
            value = session.get_variable(self.final_var)
            if value is not None:
                return True, value
        return False, None


class RecursionInvoker:
    """Blocking recursive machine invocation helper for llm_query()."""

    @staticmethod
    def _as_int(value: Any, default: int, min_value: int | None = None) -> int:
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            ivalue = default

        if min_value is not None and ivalue < min_value:
            ivalue = min_value
        return ivalue

    def invoke(self, *, prompt: Any, parent_context: dict[str, Any], model: Any = None) -> str:
        sub_prompt = "" if prompt is None else str(prompt)

        machine_config_path = parent_context.get("machine_config_path")
        if not machine_config_path:
            return "SUBCALL_NOT_CONFIGURED"

        if not Path(str(machine_config_path)).exists():
            return "SUBCALL_CONFIG_NOT_FOUND"

        current_depth = self._as_int(parent_context.get("current_depth"), 0, min_value=0)
        max_depth = self._as_int(parent_context.get("max_depth"), 5, min_value=1)
        if current_depth + 1 > max_depth:
            return "SUBCALL_DEPTH_LIMIT"

        timeout_seconds = self._as_int(parent_context.get("timeout_seconds"), 300, min_value=1)
        max_iterations = self._as_int(parent_context.get("max_iterations"), 20, min_value=1)
        max_steps = self._as_int(parent_context.get("max_steps"), 80, min_value=1)

        sub_input: dict[str, Any] = {
            "task": "Answer the request encoded in REPL variable context. Set Final when complete.",
            "long_context": sub_prompt,
            "current_depth": current_depth + 1,
            "max_depth": max_depth,
            "timeout_seconds": timeout_seconds,
            "max_iterations": max_iterations,
            "max_steps": max_steps,
            "machine_config_path": str(machine_config_path),
            "sub_model_profile": parent_context.get("sub_model_profile"),
            "model_override": parent_context.get("model_override"),
        }

        if model is not None:
            sub_input["model_override"] = str(model)

        def _run_submachine() -> str:
            machine = FlatMachine(config_file=str(machine_config_path))
            result = machine.execute_sync(input=sub_input, max_steps=max_steps)
            answer = result.get("answer")
            if answer is None:
                return "SUBCALL_NO_ANSWER"
            return str(answer)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run_submachine)
                return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            logger.warning("Subcall timed out at depth=%s", current_depth + 1)
            return "SUBCALL_TIMEOUT"
        except Exception as exc:
            logger.warning("Subcall error at depth=%s: %s", current_depth + 1, exc)
            return f"SUBCALL_ERROR: {type(exc).__name__}: {exc}"


class RLMV2Hooks(MachineHooks):
    """Hook action handlers for RLM v2 machine."""

    HISTORY_MAX_ITEMS = 5

    def __init__(self):
        super().__init__()
        self._termination = StrictFinalStrategy()
        self._recursion_invoker = RecursionInvoker()

    def on_action(self, action_name: str, context: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "init_session": self._init_session,
            "execute_response_code": self._execute_response_code,
            "check_final": self._check_final,
        }
        handler = handlers.get(action_name)
        if handler is None:
            logger.warning("Unhandled action: %s", action_name)
            return context
        return handler(context)

    def on_machine_end(self, context: dict[str, Any], final_output: dict[str, Any]) -> dict[str, Any]:
        REPLRegistry.delete_session(context.get("session_id"))
        return final_output

    @staticmethod
    def _default_machine_config_path() -> str:
        # hooks.py -> rlm_v2 -> src -> python -> rlm_v2(example root)
        root = Path(__file__).resolve().parents[3]
        return str(root / "config" / "machine.yml")

    @staticmethod
    def _coerce_int(value: Any, default: int, min_value: int | None = None) -> int:
        try:
            out = int(value)
        except (TypeError, ValueError):
            out = default
        if min_value is not None and out < min_value:
            out = min_value
        return out

    def _normalize_context(self, context: dict[str, Any]) -> None:
        context["task"] = "" if context.get("task") is None else str(context.get("task"))

        long_context = context.get("long_context")
        if long_context is None:
            long_context = ""
        elif not isinstance(long_context, str):
            long_context = str(long_context)
        context["long_context"] = long_context

        context["current_depth"] = self._coerce_int(context.get("current_depth"), 0, min_value=0)
        context["max_depth"] = self._coerce_int(context.get("max_depth"), 5, min_value=1)
        context["timeout_seconds"] = self._coerce_int(context.get("timeout_seconds"), 300, min_value=1)
        context["max_iterations"] = self._coerce_int(context.get("max_iterations"), 20, min_value=1)
        context["max_steps"] = self._coerce_int(context.get("max_steps"), 80, min_value=1)

        if not context.get("machine_config_path"):
            context["machine_config_path"] = self._default_machine_config_path()

        history_meta = context.get("history_meta")
        if not isinstance(history_meta, list):
            history_meta = []
        context["history_meta"] = history_meta[-self.HISTORY_MAX_ITEMS :]
        context["history_meta_text"] = json.dumps(context["history_meta"], ensure_ascii=False)

        if context.get("best_partial") is None:
            context["best_partial"] = "No answer produced"

        context["iteration"] = self._coerce_int(context.get("iteration"), 0, min_value=0)

    def _init_session(self, context: dict[str, Any]) -> dict[str, Any]:
        self._normalize_context(context)

        def llm_query(prompt: Any, model: Any = None) -> str:
            return self._recursion_invoker.invoke(
                prompt=prompt,
                parent_context=context,
                model=model,
            )

        session_id = context.get("session_id")
        if not REPLRegistry.has_session(session_id):
            session_id = REPLRegistry.create_session(
                context_value=context.get("long_context", ""),
                llm_query_fn=llm_query,
                session_id=session_id,
            )
            context["session_id"] = session_id

        long_context = context.get("long_context", "")
        context["context_length"] = len(long_context)
        context["context_prefix"] = truncate_text(long_context, 240)

        return context

    def _require_session(self, context: dict[str, Any]):
        session_id = context.get("session_id")
        if not session_id:
            raise RuntimeError("Missing session_id in context")
        return REPLRegistry.get_session(session_id)

    def _execute_response_code(self, context: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session(context)

        raw_response = context.get("raw_response")
        if raw_response is None:
            raw_response = ""
        if not isinstance(raw_response, str):
            raw_response = str(raw_response)

        code_blocks = extract_repl_blocks(raw_response)

        all_stdout: list[str] = []
        all_stderr: list[str] = []
        changed_vars: set[str] = set()
        had_error = False

        for block in code_blocks:
            result = session.execute(block)
            if result.stdout:
                all_stdout.append(result.stdout)
            if result.stderr:
                all_stderr.append(result.stderr)
            changed_vars.update(result.changed_vars)
            had_error = had_error or result.had_error

        if not code_blocks:
            # No REPL action provided in this turn; treat as no-op.
            had_error = False

        stdout_text = "\n".join(s.strip("\n") for s in all_stdout if s)
        stderr_text = "\n".join(s.strip("\n") for s in all_stderr if s)

        context["iteration"] = self._coerce_int(context.get("iteration"), 0, min_value=0) + 1

        code_prefix_source = "\n\n".join(code_blocks) if code_blocks else raw_response
        meta_entry = {
            "iteration": context["iteration"],
            "code_prefix": truncate_text(code_prefix_source, 240),
            "stdout_prefix": truncate_text(stdout_text, 240),
            "stdout_length": len(stdout_text),
            "stderr_prefix": truncate_text(stderr_text, 120),
            "had_error": had_error,
            "changed_vars": sorted(list(changed_vars))[:10],
        }

        history_meta = context.get("history_meta")
        if not isinstance(history_meta, list):
            history_meta = []
        history_meta.append(meta_entry)
        history_meta = history_meta[-self.HISTORY_MAX_ITEMS :]

        context["history_meta"] = history_meta
        context["history_meta_text"] = json.dumps(history_meta, ensure_ascii=False)
        context["last_exec_metadata"] = meta_entry

        self._update_best_partial(context, session, stdout_text)

        return context

    @staticmethod
    def _update_best_partial(context: dict[str, Any], session, stdout_text: str) -> None:
        for key in ("Final", "final_answer", "answer", "result"):
            if session.has_variable(key):
                value = session.get_variable(key)
                if value is not None:
                    context["best_partial"] = truncate_text(value, 400)
                    return

        if stdout_text.strip():
            context["best_partial"] = truncate_text(stdout_text.strip(), 400)

    def _check_final(self, context: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session(context)
        is_final, final_value = self._termination.evaluate(session)

        context["is_final"] = is_final
        if is_final:
            context["final_answer"] = final_value
            context["best_partial"] = truncate_text(final_value, 400)

        return context


__all__ = [
    "RLMV2Hooks",
    "RecursionInvoker",
    "StrictFinalStrategy",
]
