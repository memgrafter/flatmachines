"""
RLM Hooks - Stateless action handlers.

All state lives in context. REPL is created on-demand for each execution.
This design works across distributed systems (checkpoint/restore, different Lambdas).
"""

import logging
from typing import Any

from flatmachines import MachineHooks

try:
    from .repl import REPLExecutor
except ImportError:
    from repl import REPLExecutor

logger = logging.getLogger(__name__)


class RLMHooks(MachineHooks):
    """
    Stateless hooks for RLM. No instance variables - all state in context.
    """

    def on_action(self, state_name: str, action_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Route actions to handlers."""
        handlers = {
            "init_repl": self._init_repl,
            "execute_repl": self._execute_repl,
            "extract_chunk": self._extract_chunk,
            "log_error": self._log_error,
            "log_chunk_error": self._log_chunk_error,
        }
        handler = handlers.get(action_name)
        if handler:
            return handler(context)
        logger.warning(f"Unknown action: {action_name}")
        return context

    def _init_repl(self, context: dict[str, Any]) -> dict[str, Any]:
        """Initialize context with content metadata. No REPL instance needed."""
        content = context.get("context_content", "")

        if not content:
            logger.warning("No context content provided")
            return context

        # Add metadata to context (pure computation, no state)
        context["content_type"] = _detect_content_type(content)
        context["structure_summary"] = _get_structure_summary(content)

        logger.info(f"RLM initialized with {len(content)} character context")
        return context

    def _execute_repl(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute code in a fresh REPL. State comes from context."""
        code = context.get("code", "")
        if not code:
            logger.warning("No code to execute")
            return context

        # Create REPL on-demand from context (stateless - works after restore)
        repl = REPLExecutor()
        repl.set_context(context.get("context_content", ""))

        logger.info(f"Executing REPL code:\n{code[:200]}...")
        result = repl.execute(code)

        # Update exploration history in context (this gets checkpointed)
        history = context.get("exploration_history", [])
        history.append({
            "code": code,
            "result": result.get("output") or result.get("return_value") or result.get("error"),
            "success": result.get("success", False)
        })
        context["exploration_history"] = history

        if result.get("success"):
            logger.info(f"REPL execution successful: {str(result.get('return_value', ''))[:100]}")
        else:
            logger.warning(f"REPL execution failed: {result.get('error', '')[:200]}")
            context["last_error"] = result.get("error", "Unknown error")

        return context

    def _extract_chunk(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract chunk from content. Pure function."""
        content = context.get("context_content", "")
        sub_task = context.get("sub_task", {})

        start = max(0, sub_task.get("chunk_start", 0))
        end = min(len(content), sub_task.get("chunk_end", len(content)))

        # Handle inverted bounds
        if start > end:
            start, end = end, start

        context["chunk_content"] = content[start:end]

        logger.info(f"Extracted chunk [{start}:{end}] ({end - start} chars)")
        return context

    def _log_error(self, context: dict[str, Any]) -> dict[str, Any]:
        """Log exploration error."""
        error = context.get("last_error", "Unknown error")
        round_num = context.get("exploration_round", 0)
        logger.error(f"Exploration error in round {round_num}: {error}")
        return context

    def _log_chunk_error(self, context: dict[str, Any]) -> dict[str, Any]:
        """Log chunk processing error."""
        error = context.get("last_error", "Unknown error")
        sub_task = context.get("sub_task", {})
        logger.error(f"Chunk error for {sub_task.get('id', 'unknown')}: {error}")
        return context


# Pure functions - no class needed

def _detect_content_type(content: str) -> str:
    """Detect content type from structure."""
    if content.strip().startswith(('{', '[')):
        return "json_data"
    if '```' in content or 'def ' in content or 'class ' in content:
        return "code"
    if content.count('\n') > 100 and any(c in content for c in ['#', '##', '###']):
        return "markdown_document"
    if '\t' in content and content.count('\n') > 50:
        return "tabular_data"
    if content.count('.') > content.count('\n') / 2:
        return "prose_document"
    return "mixed_content"


def _get_structure_summary(content: str) -> str:
    """Get brief structure summary."""
    lines = len(content.split('\n'))
    chars = len(content)
    preview = content[:100].replace('\n', ' ')
    return f"{lines} lines, {chars} chars. Starts: {preview}..."
