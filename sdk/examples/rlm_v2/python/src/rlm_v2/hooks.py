"""Hooks and recursive invocation logic for the RLM v2 machine."""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Protocol

from flatmachines import FlatMachine, MachineHooks, get_logger

try:
    from .repl import REPLRegistry, extract_repl_blocks, truncate_text
    from .trace import TraceRecorder, normalize_inspect_level
except ImportError:  # pragma: no cover
    from repl import REPLRegistry, extract_repl_blocks, truncate_text
    from trace import TraceRecorder, normalize_inspect_level

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

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return default

    @staticmethod
    def _preview(value: Any, inspect_level: str, max_chars: int = 240) -> str:
        if value is None:
            return ""
        text = str(value)
        if inspect_level == "full":
            return text
        return truncate_text(text, max_chars)

    @staticmethod
    def _trace_recorder(parent_context: dict[str, Any]) -> TraceRecorder | None:
        inspect_enabled = RecursionInvoker._as_bool(parent_context.get("inspect"), False)
        if not inspect_enabled:
            return None

        run_id = parent_context.get("root_run_id")
        if not run_id:
            return None

        trace_dir = parent_context.get("trace_dir") or "./traces"
        return TraceRecorder(trace_dir=trace_dir, run_id=str(run_id))

    def invoke(self, *, prompt: Any, parent_context: dict[str, Any], model: Any = None) -> str:
        sub_prompt = "" if prompt is None else str(prompt)

        inspect_level = normalize_inspect_level(str(parent_context.get("inspect_level") or "summary"))
        trace_recorder = self._trace_recorder(parent_context)

        current_depth = self._as_int(parent_context.get("current_depth"), 0, min_value=0)
        next_depth = current_depth + 1
        max_depth = self._as_int(parent_context.get("max_depth"), 5, min_value=1)
        timeout_seconds = self._as_int(parent_context.get("timeout_seconds"), 300, min_value=1)
        max_iterations = self._as_int(parent_context.get("max_iterations"), 20, min_value=1)
        max_steps = self._as_int(parent_context.get("max_steps"), 80, min_value=1)

        call_id = str(uuid.uuid4())
        parent_call_id = parent_context.get("parent_call_id")

        start_time = time.perf_counter()

        def emit(event_type: str, **fields: Any) -> None:
            if trace_recorder is None:
                return
            trace_recorder.append_event(
                event_type,
                depth=current_depth,
                next_depth=next_depth,
                call_id=call_id,
                parent_call_id=parent_call_id,
                **fields,
            )

        emit(
            "subcall_start",
            prompt_length=len(sub_prompt),
            prompt_preview=self._preview(sub_prompt, inspect_level),
            model_override=(str(model) if model is not None else None),
        )

        machine_config_path = parent_context.get("machine_config_path")
        if not machine_config_path:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            emit("subcall_end", status="not_configured", duration_ms=duration_ms)
            return "SUBCALL_NOT_CONFIGURED"

        if not Path(str(machine_config_path)).exists():
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            emit("subcall_end", status="config_not_found", duration_ms=duration_ms)
            return "SUBCALL_CONFIG_NOT_FOUND"

        if next_depth > max_depth:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            emit("subcall_end", status="depth_limit", duration_ms=duration_ms)
            return "SUBCALL_DEPTH_LIMIT"

        sub_input: dict[str, Any] = {
            "task": "Answer the request encoded in REPL variable context. Set Final when complete.",
            "long_context": sub_prompt,
            "current_depth": next_depth,
            "max_depth": max_depth,
            "timeout_seconds": timeout_seconds,
            "max_iterations": max_iterations,
            "max_steps": max_steps,
            "machine_config_path": str(machine_config_path),
            "sub_model_profile": parent_context.get("sub_model_profile"),
            "model_override": parent_context.get("model_override"),
            "inspect": self._as_bool(parent_context.get("inspect"), False),
            "inspect_level": inspect_level,
            "trace_dir": parent_context.get("trace_dir") or "./traces",
            "root_run_id": parent_context.get("root_run_id"),
            "parent_call_id": call_id,
            "print_iterations": self._as_bool(parent_context.get("print_iterations"), False),
            "experiment": parent_context.get("experiment"),
            "tags": parent_context.get("tags"),
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
                answer = future.result(timeout=timeout_seconds)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            emit(
                "subcall_end",
                status="success",
                duration_ms=duration_ms,
                answer_length=len(answer),
                answer_preview=self._preview(answer, inspect_level),
            )
            return answer
        except FuturesTimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("Subcall timed out at depth=%s", next_depth)
            emit("subcall_end", status="timeout", duration_ms=duration_ms)
            return "SUBCALL_TIMEOUT"
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("Subcall error at depth=%s: %s", next_depth, exc)
            emit(
                "subcall_end",
                status="error",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
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

    def on_error(self, state_name: str, error: Exception, context: dict[str, Any]) -> str | None:
        self._trace_event(
            context,
            "error",
            state=state_name,
            depth=self._coerce_int(context.get("current_depth"), 0, min_value=0),
            iteration=self._coerce_int(context.get("iteration"), 0, min_value=0),
            error_type=type(error).__name__,
            error_message=str(error),
        )
        return None

    def on_machine_end(self, context: dict[str, Any], final_output: dict[str, Any]) -> dict[str, Any]:
        self._trace_event(
            context,
            "run_end",
            depth=self._coerce_int(context.get("current_depth"), 0, min_value=0),
            iteration=self._coerce_int(context.get("iteration"), 0, min_value=0),
            reason=final_output.get("reason"),
            answer_preview=self._preview(context, final_output.get("answer"), 400),
            answer_length=len(str(final_output.get("answer"))) if final_output.get("answer") is not None else 0,
            error=final_output.get("error"),
        )

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

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y", "on"}:
                return True
            if lowered in {"0", "false", "no", "n", "off"}:
                return False
        return default

    @staticmethod
    def _normalize_tags(value: Any) -> dict[str, str]:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _canonicalize_code_for_fingerprint(code_text: str) -> str:
        """Strip comments and normalize whitespace before repeat fingerprinting."""
        if not code_text:
            return ""

        cleaned_lines: list[str] = []
        for raw_line in str(code_text).splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cleaned_lines.append(stripped)

        return " ".join(cleaned_lines)

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

        context["last_code_fingerprint"] = str(context.get("last_code_fingerprint") or "")
        context["repeat_streak"] = self._coerce_int(context.get("repeat_streak"), 0, min_value=0)
        context["loop_hint"] = "" if context.get("loop_hint") is None else str(context.get("loop_hint"))

        if context.get("best_partial") is None:
            context["best_partial"] = "No answer produced"

        context["iteration"] = self._coerce_int(context.get("iteration"), 0, min_value=0)

        context["inspect"] = self._coerce_bool(context.get("inspect"), False)
        context["inspect_level"] = normalize_inspect_level(str(context.get("inspect_level") or "summary"))
        context["trace_dir"] = str(context.get("trace_dir") or "./traces")
        context["print_iterations"] = self._coerce_bool(context.get("print_iterations"), False)

        if context["inspect"] and not context.get("root_run_id"):
            context["root_run_id"] = str(uuid.uuid4())

        if context.get("parent_call_id") is not None:
            context["parent_call_id"] = str(context.get("parent_call_id"))

        context["experiment"] = None if context.get("experiment") is None else str(context.get("experiment"))
        context["tags"] = self._normalize_tags(context.get("tags"))

    def _trace_recorder(self, context: dict[str, Any]) -> TraceRecorder | None:
        if not self._coerce_bool(context.get("inspect"), False):
            return None

        run_id = context.get("root_run_id")
        if not run_id:
            return None

        trace_dir = context.get("trace_dir") or "./traces"
        return TraceRecorder(trace_dir=trace_dir, run_id=str(run_id))

    def _preview(self, context: dict[str, Any], value: Any, max_chars: int = 240) -> str:
        if value is None:
            return ""

        text = str(value)
        if context.get("inspect_level") == "full":
            return text
        return truncate_text(text, max_chars)

    def _trace_event(self, context: dict[str, Any], event_type: str, **fields: Any) -> None:
        recorder = self._trace_recorder(context)
        if recorder is None:
            return

        try:
            recorder.append_event(event_type, **fields)
        except Exception as exc:  # pragma: no cover - trace errors must never break execution
            logger.warning("Failed to write trace event %s: %s", event_type, exc)

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

        self._trace_event(
            context,
            "run_start",
            depth=context.get("current_depth"),
            parent_call_id=context.get("parent_call_id"),
            task_preview=self._preview(context, context.get("task"), 300),
            task_length=len(context.get("task", "")),
            context_length=context.get("context_length", 0),
            context_prefix=context.get("context_prefix", ""),
            max_iterations=context.get("max_iterations"),
            max_depth=context.get("max_depth"),
            timeout_seconds=context.get("timeout_seconds"),
            experiment=context.get("experiment"),
            tags=context.get("tags"),
        )

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

        next_iteration = self._coerce_int(context.get("iteration"), 0, min_value=0) + 1
        self._trace_event(
            context,
            "iteration_start",
            depth=context.get("current_depth"),
            iteration=next_iteration,
            max_iterations=context.get("max_iterations"),
        )

        self._trace_event(
            context,
            "llm_response",
            depth=context.get("current_depth"),
            iteration=next_iteration,
            response_length=len(raw_response),
            response_preview=self._preview(context, raw_response, 400),
        )

        code_blocks = extract_repl_blocks(raw_response)
        self._trace_event(
            context,
            "code_blocks_extracted",
            depth=context.get("current_depth"),
            iteration=next_iteration,
            block_count=len(code_blocks),
        )

        all_stdout: list[str] = []
        all_stderr: list[str] = []
        changed_vars: set[str] = set()
        had_error = False

        for idx, block in enumerate(code_blocks):
            start = time.perf_counter()
            result = session.execute(block)
            duration_ms = (time.perf_counter() - start) * 1000.0

            if result.stdout:
                all_stdout.append(result.stdout)
            if result.stderr:
                all_stderr.append(result.stderr)
            changed_vars.update(result.changed_vars)
            had_error = had_error or result.had_error

            self._trace_event(
                context,
                "repl_exec",
                depth=context.get("current_depth"),
                iteration=next_iteration,
                block_index=idx,
                block_count=len(code_blocks),
                duration_ms=duration_ms,
                code_preview=self._preview(context, block, 320),
                stdout_length=len(result.stdout),
                stdout_preview=self._preview(context, result.stdout, 320),
                stderr_length=len(result.stderr),
                stderr_preview=self._preview(context, result.stderr, 240),
                had_error=result.had_error,
                changed_vars=result.changed_vars,
            )

        if not code_blocks:
            had_error = False
            self._trace_event(
                context,
                "repl_exec",
                depth=context.get("current_depth"),
                iteration=next_iteration,
                block_count=0,
                no_code_blocks=True,
            )

        stdout_text = "\n".join(s.strip("\n") for s in all_stdout if s)
        stderr_text = "\n".join(s.strip("\n") for s in all_stderr if s)

        context["iteration"] = next_iteration

        code_prefix_source = "\n\n".join(code_blocks) if code_blocks else raw_response

        canonical = self._canonicalize_code_for_fingerprint(code_prefix_source)
        current_fp = str(hash(canonical))
        last_fp = str(context.get("last_code_fingerprint") or "")
        streak = self._coerce_int(context.get("repeat_streak"), 0, min_value=0)

        if current_fp == last_fp and canonical:
            streak += 1
        else:
            streak = 0

        context["last_code_fingerprint"] = current_fp
        context["repeat_streak"] = streak

        if streak >= 2:
            context["loop_hint"] = (
                "You are repeating near-identical REPL actions. "
                "Do not print full context again; switch strategy and use targeted chunking/llm_query."
            )
        else:
            context["loop_hint"] = ""

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

        final_exists = session.has_variable("Final") and session.get_variable("Final") is not None
        if context.get("print_iterations"):
            print(
                "[rlm_v2] "
                f"depth={context.get('current_depth')} "
                f"iter={context.get('iteration')}/{context.get('max_iterations')} "
                f"blocks={len(code_blocks)} "
                f"error={had_error} "
                f"final={final_exists}"
            )

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
            self._trace_event(
                context,
                "final_detected",
                depth=context.get("current_depth"),
                iteration=context.get("iteration"),
                final_length=len(str(final_value)),
                final_preview=self._preview(context, final_value, 400),
            )
            if context.get("print_iterations"):
                print(
                    "[rlm_v2] "
                    f"depth={context.get('current_depth')} "
                    f"iter={context.get('iteration')} "
                    "final=true"
                )

        return context


__all__ = [
    "RLMV2Hooks",
    "RecursionInvoker",
    "StrictFinalStrategy",
]
