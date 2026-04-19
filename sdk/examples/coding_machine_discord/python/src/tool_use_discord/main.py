"""
Coding Machine Discord — copied from coding_machine_cli and adapted.

Two modes:
- CLI mode (original coding_machine_cli behavior)
- Discord queue mode (ingress + debounce + respond)

Usage:
    python -m tool_use_discord.main cli
    python -m tool_use_discord.main all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
import warnings
from pathlib import Path
from typing import Any, Optional

from flatmachines import (
    CheckpointManager,
    FlatMachine,
    SQLiteCheckpointBackend,
    SQLiteLeaseLock,
    SQLiteSignalBackend,
)

from .debounce import DebounceService
from .discord_api import DiscordAPI
from .discord_ingress import DiscordIngressService
from .hooks import CLIToolHooks
from .messages_backend import SQLiteMessageBackend
from .paths import default_history_dir as _default_history_dir, mk42_home as _mk42_home
from .responder import BatchResponder, DiscordResponderService, EchoBatchResponder
from .tools import EveryoneTimestampToolProvider

# Suppress validation warnings until schemas are regenerated
warnings.filterwarnings("ignore", message=".*validation.*")
warnings.filterwarnings("ignore", message=".*Flatmachine.*")
warnings.filterwarnings("ignore", message=".*Flatagent.*")

# Quiet by default — set LOG_LEVEL=INFO or LOG_LEVEL=DEBUG to see logs
_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines", "LiteLLM"):
    logging.getLogger(_name).setLevel(_log_level)


def _chat_rollover_token_limit() -> int:
    raw = str(os.environ.get("MK42_CHAT_ROLLOVER_TOKEN_LIMIT", "50000")).strip()
    try:
        value = int(raw)
    except ValueError:
        return 50000
    return max(0, value)


def _approx_token_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, (len(value) + 3) // 4)
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return max(1, len(str(value)))
    if isinstance(value, list):
        return sum(_approx_token_count(item) + 2 for item in value)
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            total += _approx_token_count(str(key)) + _approx_token_count(item) + 2
        return total
    return _approx_token_count(str(value))


class DiscordMachineHooks(CLIToolHooks):
    """Tool hooks for Discord machine execution.

    - provides read/write/bash/edit tools (from CLIToolHooks)
    - posts model result when machine enters `post_result` action state
    """

    _SHARED_TOOL_LOOP_AGENT_BY_STATE = {
        "admin_work": "coder",
        "everyone_work": "everyone",
    }

    _HISTORY_ROLE_BY_STATE = {
        "admin_work": "admin",
        "everyone_work": "everyone",
    }

    _HISTORY_ROLE_BY_AGENT = {
        "coder": "admin",
        "everyone": "everyone",
    }

    def __init__(self, *, working_dir: str, api: DiscordAPI):
        super().__init__(working_dir=working_dir, auto_approve=True)
        self.api = api
        self._chat_rollover_token_limit = _chat_rollover_token_limit()
        self._everyone_provider = EveryoneTimestampToolProvider(history_dir=str(self._history_dir))

    def on_state_enter(self, state_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Allow admin/everyone states to share one full tool-loop chain.

        FlatMachine's default tool-loop continuation chain is scoped to
        (state_name, agent_name). We deliberately re-tag the existing chain for
        whichever role state is entering so both roles continue the same full
        history, including assistant tool calls and tool results.
        """
        context = super().on_state_enter(state_name, context)
        context.setdefault("history_dir", str(self._history_dir))
        context.setdefault("chat_rollover_token_limit", self._chat_rollover_token_limit)
        context.setdefault("chat_context_rollover_generation", 0)
        context.setdefault("chat_context_rollover_count", 0)
        context.setdefault("chat_context_rolled_over", False)
        context.setdefault("chat_context_needs_history_lookup", False)

        agent_name = self._SHARED_TOOL_LOOP_AGENT_BY_STATE.get(state_name)
        if agent_name:
            chain = context.get("_tool_loop_chain")
            if isinstance(chain, list) and chain:
                context["_tool_loop_chain_state"] = state_name
                context["_tool_loop_chain_agent"] = agent_name

        if state_name == "everyone_work":
            self._everyone_provider.set_runtime_scope(conversation_key=context.get("conversation_key"))

        return self._maybe_rollover_chat_context(state_name, context)

    def get_tool_provider(self, state_name: str):
        if state_name == "everyone_work":
            return self._everyone_provider
        return super().get_tool_provider(state_name)

    def _history_role(self, state_name: str, context: dict[str, Any]) -> str:
        mapped = self._HISTORY_ROLE_BY_STATE.get(state_name)
        if mapped:
            return mapped

        agent_name = str(context.get("_tool_loop_chain_agent") or "").strip()
        mapped_agent = self._HISTORY_ROLE_BY_AGENT.get(agent_name)
        if mapped_agent:
            return mapped_agent

        return super()._history_role(state_name, context)

    def _maybe_rollover_chat_context(self, state_name: str, context: dict[str, Any]) -> dict[str, Any]:
        limit_raw = context.get("chat_rollover_token_limit")
        limit = self._chat_rollover_token_limit if limit_raw is None else int(limit_raw)
        chain = context.get("_tool_loop_chain")
        if limit <= 0 or not isinstance(chain, list) or not chain:
            return context

        estimated_tokens = _approx_token_count(chain)
        context["chat_context_estimated_tokens"] = estimated_tokens
        if estimated_tokens < limit:
            return context

        generation = int(context.get("chat_context_rollover_generation") or 0) + 1
        count = int(context.get("chat_context_rollover_count") or 0) + 1
        context["chat_context_rollover_generation"] = generation
        context["chat_context_rollover_count"] = count
        context["chat_context_rolled_over"] = True
        context["chat_context_needs_history_lookup"] = True
        context["chat_context_last_rollover_ts"] = int(time.time())
        context["chat_context_last_rollover_state"] = state_name
        context["chat_context_last_rollover_estimated_tokens"] = estimated_tokens
        context["_tool_loop_chain"] = []
        context["_tool_loop_content"] = ""
        context["_tool_loop_usage"] = {}
        context["_tool_loop_cost"] = 0
        context["_history_chain_cursors"] = {}
        context["_history_file_ts"] = {}

        print(
            f"[chat] rolled over context at ~{estimated_tokens} tokens (limit={limit}, generation={generation})",
            flush=True,
        )
        return context

    async def on_action(self, action_name: str, context: dict[str, Any]) -> dict[str, Any]:
        state_name = str(context.get("_history_last_state") or "unknown")

        if action_name == "queue_feedback":
            messages = context.get("batch_messages")
            if not isinstance(messages, list):
                messages = []

            if not messages:
                admin_messages = context.get("admin_batch_messages")
                everyone_messages = context.get("everyone_batch_messages")
                if isinstance(admin_messages, list):
                    messages.extend(admin_messages)
                if isinstance(everyone_messages, list):
                    messages.extend(everyone_messages)

            if messages:
                feedback = build_feedback_from_messages(messages).strip()
                if feedback and feedback != "(no new user text)":
                    chain = context.get("_tool_loop_chain")
                    if not isinstance(chain, list):
                        chain = []

                    should_append = True
                    if chain:
                        last = chain[-1]
                        if (
                            isinstance(last, dict)
                            and str(last.get("role", "")) == "user"
                            and str(last.get("content", "")).strip() == feedback
                        ):
                            should_append = False

                    if should_append:
                        chain.append({"role": "user", "content": feedback})
                        context["_tool_loop_chain"] = chain

            context = self._sync_history_from_chain(state_name, context)
            return self._maybe_rollover_chat_context(state_name, context)

        if action_name != "post_result":
            context = self._sync_history_from_chain(state_name, context)
            return self._maybe_rollover_chat_context(state_name, context)

        result_text = str(context.get("result", "")).strip()
        if result_text:
            for chunk in _split_discord_message(result_text, max_chars=2000):
                await asyncio.to_thread(self.api.post_channel_message, chunk)

        context = self._sync_history_from_chain(state_name, context)
        return self._maybe_rollover_chat_context(state_name, context)


def _split_discord_message(content: str, max_chars: int = 2000) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    if len(content) <= max_chars:
        return [content]

    parts: list[str] = []
    start = 0
    while start < len(content):
        end = min(len(content), start + max_chars)
        if end < len(content):
            newline = content.rfind("\n", start, end)
            if newline > start:
                end = newline + 1
        parts.append(content[start:end])
        start = end
    return parts


def _conversation_execution_id(conversation_key: str) -> str:
    return f"discord-machine-{conversation_key}"


class CodingMachineBatchResponder(BatchResponder):
    """Responder that resumes one FlatMachine execution per Discord conversation."""

    def __init__(
        self,
        *,
        working_dir: str,
        api: DiscordAPI,
        backend: Optional[SQLiteMessageBackend],
        db_path: str,
        input_queue: str,
        queue_wait_seconds: float,
        conversation_idle_timeout_seconds: float,
        queue_poll_seconds: float,
    ):
        self.working_dir = os.path.abspath(working_dir)
        self.api = api
        self.backend = backend
        self.db_path = str(Path(db_path).expanduser().resolve())

        # Retained for CLI compatibility / future tuning knobs.
        self.input_queue = input_queue
        self.queue_wait_seconds = queue_wait_seconds
        self.conversation_idle_timeout_seconds = conversation_idle_timeout_seconds
        self.queue_poll_seconds = queue_poll_seconds

        self.checkpoint_backend = SQLiteCheckpointBackend(db_path=self.db_path)
        self.signal_backend = SQLiteSignalBackend(db_path=self.db_path)
        self.machine_lock = SQLiteLeaseLock(
            db_path=self.db_path,
            owner_id=f"discord-responder-{os.getpid()}-{id(self)}",
            phase="machine",
        )

    async def _has_live_execution(self, execution_id: str) -> bool:
        manager = CheckpointManager(self.checkpoint_backend, execution_id)
        status = await manager.load_status()
        if status is None:
            return False

        event, _state = status
        if event == "machine_end":
            await self.checkpoint_backend.delete_execution(execution_id)
            return False

        return True

    async def compose_reply(self, batch: dict[str, Any]) -> Optional[str]:
        conversation_key = str(batch.get("conversation_key") or self.api.channel_id)
        execution_id = _conversation_execution_id(conversation_key)
        wait_channel = f"discord/{conversation_key}"

        batch_messages_raw = batch.get("messages")
        if not isinstance(batch_messages_raw, list):
            batch_messages_raw = []

        admin_batch_messages, everyone_batch_messages = split_batch_messages_by_admin(
            batch_messages_raw,
            backend=self.backend,
        )

        latest_request = extract_latest_request(batch_messages_raw)

        machine_input = {
            "task": latest_request,
            "working_dir": self.working_dir,
            "latest_user_request": latest_request,
            "batch_messages": batch_messages_raw,
            "admin_batch_messages": admin_batch_messages,
            "everyone_batch_messages": everyone_batch_messages,
            "admin_message_count": len(admin_batch_messages),
            "everyone_message_count": len(everyone_batch_messages),
            "queued_message_count": int(batch.get("message_count", 0) or 0),
            "conversation_key": conversation_key,
            "history_dir": _default_history_dir(),
            "chat_rollover_token_limit": _chat_rollover_token_limit(),
        }

        has_live_execution = await self._has_live_execution(execution_id)
        if not has_live_execution:
            machine_input["agents_md"] = _read_agents_md(self.working_dir)

        print(
            "[respond] "
            f"conversation={conversation_key} "
            f"admin_messages={len(admin_batch_messages)} "
            f"everyone_messages={len(everyone_batch_messages)} "
            f"live_execution={has_live_execution}",
            flush=True,
        )

        if has_live_execution:
            await self.signal_backend.send(wait_channel, machine_input)

        hooks = DiscordMachineHooks(working_dir=self.working_dir, api=self.api)
        machine = FlatMachine(
            config_file=_config_path("discord_machine.yml"),
            profiles_file=_config_path("profiles.yml"),
            hooks=hooks,
            persistence=self.checkpoint_backend,
            lock=self.machine_lock,
            signal_backend=self.signal_backend,
            _execution_id=execution_id,
        )

        result = await machine.execute(
            input=machine_input,
            resume_from=execution_id,
        )

        # Discord responses are posted in `post_result` action hook.
        # If machine is parked waiting for next user batch, avoid duplicate post.
        if isinstance(result, dict) and result.get("_waiting"):
            return None

        if isinstance(result, dict):
            if "result" in result:
                return str(result["result"])
            if "content" in result:
                return str(result["content"])
        return str(result)


def extract_latest_request(messages: list[Any]) -> str:
    latest_request = ""
    for message in messages:
        if isinstance(message, dict):
            content = str(message.get("content", "")).strip()
            if content:
                latest_request = content
    return latest_request


def split_batch_messages_by_admin(
    messages: list[Any],
    *,
    backend: Optional[SQLiteMessageBackend],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized = [message for message in messages if isinstance(message, dict)]

    # Backward-compatible fallback for tests / standalone use.
    if backend is None:
        return normalized, []

    admin_messages: list[dict[str, Any]] = []
    everyone_messages: list[dict[str, Any]] = []

    for message in normalized:
        author_id = str(message.get("author_id", "")).strip()
        is_admin = backend.is_discord_user_admin(author_id)
        if is_admin:
            admin_messages.append(message)
        else:
            everyone_messages.append(message)

    return admin_messages, everyone_messages


def build_feedback_from_messages(messages: list[Any]) -> str:
    rows: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            rows.append(str(message))
            continue

        author = str(message.get("author_name") or message.get("author_id") or "user")
        content = str(message.get("content", "")).strip()
        if content:
            rows.append(f"{author}: {content}")

    if not rows:
        return "(no new user text)"
    return "\n".join(rows)


def _read_agents_md(working_dir: str) -> str:
    agents_path = Path(working_dir).resolve() / "AGENTS.md"
    try:
        return agents_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as exc:
        print(f"[respond] warning: failed to read {agents_path}: {exc}", flush=True)
        return ""


def _parse_kv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    except Exception as exc:
        print(f"[mk42] warning: failed to read {path}: {exc}", flush=True)
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        if value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1]

        values[key] = value

    return values


def _load_runtime_env_from_conf() -> None:
    mk42_home = _mk42_home()
    conf_path = Path(os.environ.get("MK42_CONF", str(mk42_home / "conf"))).expanduser().resolve()

    for key, value in _parse_kv_file(conf_path).items():
        os.environ.setdefault(key, value)

    env_path = Path(
        os.environ.get(
            "MK42_ENV_FILE",
            str(Path("~/.agents/flatmachines/mk42.env").expanduser()),
        )
    ).expanduser().resolve()

    for key, value in _parse_kv_file(env_path).items():
        os.environ.setdefault(key, value)

    codex_auth = Path(
        os.environ.get(
            "MK42_CODEX_AUTH_FILE",
            str(Path("~/.agents/flatmachines/auth.json").expanduser()),
        )
    ).expanduser()

    os.environ.setdefault("MK42_CODEX_AUTH_FILE", str(codex_auth))
    os.environ.setdefault("FLATAGENTS_CODEX_AUTH_FILE", str(codex_auth))
    os.environ.setdefault("TOOL_USE_DISCORD_HISTORY_DIR", _default_history_dir())


def _config_path(name: str) -> str:
    override = os.environ.get("TOOL_USE_DISCORD_CONFIG_DIR", "").strip()
    if override:
        return str((Path(override).expanduser().resolve() / name))

    return str(Path(__file__).parent.parent.parent.parent / "config" / name)


def _default_db_path() -> str:
    override = os.environ.get("TOOL_USE_DISCORD_DB_PATH", "").strip()
    if override:
        return str(Path(override).expanduser().resolve())

    mk42_home = _mk42_home()
    mk42_db = mk42_home / "current" / "data" / "coding_machine_discord.sqlite"
    if mk42_db.exists() or mk42_home.exists():
        return str(mk42_db)

    root = Path(__file__).resolve().parents[3]
    return str((root / "data" / "coding_machine_discord.sqlite").resolve())


def _default_working_dir() -> str:
    override = os.environ.get("TOOL_USE_DISCORD_WORKING_DIR", "").strip()
    if override:
        return str(Path(override).expanduser().resolve())

    mk42_home = _mk42_home()
    mk42_workspace = mk42_home / "current"
    if mk42_workspace.exists() or mk42_home.exists():
        return str(mk42_workspace)

    return os.getcwd()


def _require_discord_config(args: argparse.Namespace) -> tuple[str, str]:
    token = (args.discord_bot_token or "").strip()
    channel_id = (args.discord_channel_id or "").strip()
    if not token:
        raise SystemExit("error: DISCORD_BOT_TOKEN (or --discord-bot-token) is required")
    if not channel_id:
        raise SystemExit("error: DISCORD_CHANNEL_ID (or --discord-channel-id) is required")
    return token, channel_id


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except (NotImplementedError, RuntimeError):
            pass


async def run_machine(
    task: str,
    working_dir: str,
    human_review: bool = True,
    hooks: Optional[CLIToolHooks] = None,
    latest_user_request: str = "",
    batch_messages: Optional[list[Any]] = None,
    queued_message_count: int = 0,
    conversation_key: str = "",
    tool_loop_chain: Optional[list[Any]] = None,
    tool_loop_chain_state: Optional[str] = None,
    tool_loop_chain_agent: Optional[str] = None,
    history_dir: Optional[str] = None,
    chat_rollover_token_limit: Optional[int] = None,
):
    """Run a single task via FlatMachine machine-driven tool loop."""
    resolved_hooks = hooks or CLIToolHooks(working_dir=working_dir, auto_approve=not human_review)
    machine = FlatMachine(
        config_file=_config_path("machine.yml"),
        hooks=resolved_hooks,
    )

    result = await machine.execute(input={
        "task": task,
        "working_dir": working_dir,
        "latest_user_request": latest_user_request,
        "batch_messages": batch_messages or [],
        "queued_message_count": queued_message_count,
        "conversation_key": conversation_key,
        "_tool_loop_chain": tool_loop_chain,
        "_tool_loop_chain_state": tool_loop_chain_state,
        "_tool_loop_chain_agent": tool_loop_chain_agent,
        "history_dir": history_dir or _default_history_dir(),
        "chat_rollover_token_limit": _chat_rollover_token_limit() if chat_rollover_token_limit is None else chat_rollover_token_limit,
    })

    return result


async def run_standalone(task: str, working_dir: str):
    """Run a single task via FlatMachine without interactive review."""
    result = await run_machine(task, working_dir, human_review=False)

    print("=" * 60)
    print("DONE")
    print("=" * 60)
    content = result.get("result") if isinstance(result, dict) else result
    if content:
        print(content)

    return result


async def repl(working_dir: str):
    """Interactive REPL — original coding_machine_cli mode."""
    print(f"Tool Use Discord (CLI mode) — {working_dir}")
    print()

    _interrupt_count = 0

    while True:
        try:
            task = input("> ").strip()
            _interrupt_count = 0
        except KeyboardInterrupt:
            _interrupt_count += 1
            if _interrupt_count >= 2:
                print()
                break
            print()
            continue
        except EOFError:
            print()
            break

        if not task:
            continue

        _interrupt_count = 0

        try:
            await run_machine(task, working_dir)
        except KeyboardInterrupt:
            print("\nInterrupted.")
        except Exception as e:
            print(f"Error: {e}")

        print()


async def _run_ingress(args: argparse.Namespace) -> int:
    token, channel_id = _require_discord_config(args)
    backend = SQLiteMessageBackend(args.db_path)
    api = DiscordAPI(bot_token=token, channel_id=channel_id)

    service = DiscordIngressService(
        backend=backend,
        api=api,
        input_queue=args.input_queue,
        poll_seconds=args.poll_seconds,
        fetch_limit=args.fetch_limit,
        backfill_on_first_run=args.backfill_on_first_run,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    print("Starting ingress worker", flush=True)
    await service.run(stop_event)
    return 0


async def _run_debounce(args: argparse.Namespace) -> int:
    backend = SQLiteMessageBackend(args.db_path)
    service = DebounceService(
        backend=backend,
        input_queue=args.input_queue,
        output_queue=args.output_queue,
        debounce_seconds=args.debounce_seconds,
        poll_seconds=args.poll_seconds,
        lease_seconds=args.lease_seconds,
        lease_limit=args.lease_limit,
        worker_id=args.worker_id,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    print("Starting debounce worker", flush=True)
    await service.run(stop_event)
    return 0


async def _run_responder(args: argparse.Namespace) -> int:
    token, channel_id = _require_discord_config(args)
    backend = SQLiteMessageBackend(args.db_path)
    api = DiscordAPI(bot_token=token, channel_id=channel_id)

    if args.echo_only:
        responder: BatchResponder = EchoBatchResponder()
    else:
        responder = CodingMachineBatchResponder(
            working_dir=args.working_dir,
            api=api,
            backend=backend,
            db_path=args.db_path,
            input_queue=args.input_queue,
            queue_wait_seconds=args.queue_wait_seconds,
            conversation_idle_timeout_seconds=args.conversation_idle_timeout_seconds,
            queue_poll_seconds=args.queue_poll_seconds,
        )

    service = DiscordResponderService(
        backend=backend,
        api=api,
        responder=responder,
        input_queue=args.input_queue,
        worker_id=args.worker_id,
        lease_seconds=args.lease_seconds,
        lease_limit=args.lease_limit,
        poll_seconds=args.poll_seconds,
        retry_delay_seconds=args.retry_delay_seconds,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    print("Starting responder worker", flush=True)
    await service.run(stop_event)
    return 0


async def _run_all(args: argparse.Namespace) -> int:
    token, channel_id = _require_discord_config(args)
    backend = SQLiteMessageBackend(args.db_path)
    api = DiscordAPI(bot_token=token, channel_id=channel_id)

    ingress = DiscordIngressService(
        backend=backend,
        api=api,
        input_queue=args.ingress_input_queue,
        poll_seconds=args.ingress_poll_seconds,
        fetch_limit=args.ingress_fetch_limit,
        backfill_on_first_run=args.backfill_on_first_run,
    )

    debounce = DebounceService(
        backend=backend,
        input_queue=args.ingress_input_queue,
        output_queue=args.debounce_output_queue,
        debounce_seconds=args.debounce_seconds,
        poll_seconds=args.debounce_poll_seconds,
        lease_seconds=args.debounce_lease_seconds,
        lease_limit=args.debounce_lease_limit,
        worker_id="debouncer",
    )

    if args.echo_only:
        responder_impl: BatchResponder = EchoBatchResponder()
    else:
        responder_impl = CodingMachineBatchResponder(
            working_dir=args.working_dir,
            api=api,
            backend=backend,
            db_path=args.db_path,
            input_queue=args.debounce_output_queue,
            queue_wait_seconds=args.queue_wait_seconds,
            conversation_idle_timeout_seconds=args.conversation_idle_timeout_seconds,
            queue_poll_seconds=args.queue_poll_seconds,
        )

    responder = DiscordResponderService(
        backend=backend,
        api=api,
        responder=responder_impl,
        input_queue=args.debounce_output_queue,
        worker_id="responder",
        lease_seconds=args.responder_lease_seconds,
        lease_limit=args.responder_lease_limit,
        poll_seconds=args.responder_poll_seconds,
        retry_delay_seconds=args.responder_retry_delay_seconds,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    print("Starting all workers: ingress + debounce + respond", flush=True)
    tasks = [
        asyncio.create_task(ingress.run(stop_event), name="ingress"),
        asyncio.create_task(debounce.run(stop_event), name="debounce"),
        asyncio.create_task(responder.run(stop_event), name="respond"),
    ]

    try:
        await stop_event.wait()
    finally:
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    return 0


def _run_status(args: argparse.Namespace) -> int:
    backend = SQLiteMessageBackend(args.db_path)
    print("Queue counts:", backend.queue_counts(), flush=True)
    print(
        "State:",
        {
            "discord:last_seen_message_id": backend.get_state("discord:last_seen_message_id"),
        },
        flush=True,
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Coding machine copied from coding_machine_cli with Discord queue workers"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Original CLI mode
    cli = sub.add_parser("cli", help="run original coding_machine_cli REPL/single-shot")
    cli.add_argument("-p", "--print", metavar="TASK", dest="task")
    cli.add_argument("--working-dir", "-w", default=_default_working_dir())
    cli.add_argument("--standalone", "-s", metavar="TASK", nargs="?", const=True)

    # Discord workers
    ingress = sub.add_parser("ingress", help="poll Discord and enqueue inbound messages")
    ingress.add_argument("--db-path", default=_default_db_path())
    ingress.add_argument("--discord-bot-token", default=os.environ.get("DISCORD_BOT_TOKEN", ""))
    ingress.add_argument("--discord-channel-id", default=os.environ.get("DISCORD_CHANNEL_ID", ""))
    ingress.add_argument("--input-queue", default="discord_incoming")
    ingress.add_argument("--poll-seconds", type=float, default=2.0)
    ingress.add_argument("--fetch-limit", type=int, default=50)
    ingress.add_argument("--backfill-on-first-run", action="store_true")

    debounce = sub.add_parser("debounce", help="debounce inbound queue into batch queue")
    debounce.add_argument("--db-path", default=_default_db_path())
    debounce.add_argument("--input-queue", default="discord_incoming")
    debounce.add_argument("--output-queue", default="discord_debounced")
    debounce.add_argument("--debounce-seconds", type=float, default=15.0)
    debounce.add_argument("--poll-seconds", type=float, default=0.5)
    debounce.add_argument("--lease-seconds", type=float, default=60.0)
    debounce.add_argument("--lease-limit", type=int, default=100)
    debounce.add_argument("--worker-id", default="debouncer")

    respond = sub.add_parser("respond", help="consume debounced queue and post reply")
    respond.add_argument("--db-path", default=_default_db_path())
    respond.add_argument("--discord-bot-token", default=os.environ.get("DISCORD_BOT_TOKEN", ""))
    respond.add_argument("--discord-channel-id", default=os.environ.get("DISCORD_CHANNEL_ID", ""))
    respond.add_argument("--input-queue", default="discord_debounced")
    respond.add_argument("--poll-seconds", type=float, default=1.0)
    respond.add_argument("--lease-seconds", type=float, default=120.0)
    respond.add_argument("--lease-limit", type=int, default=1)
    respond.add_argument("--retry-delay-seconds", type=float, default=3.0)
    respond.add_argument("--queue-wait-seconds", type=float, default=15.0)
    respond.add_argument("--conversation-idle-timeout-seconds", type=float, default=300.0)
    respond.add_argument("--queue-poll-seconds", type=float, default=1.0)
    respond.add_argument("--worker-id", default="responder")
    respond.add_argument("--working-dir", default=_default_working_dir())
    respond.add_argument("--echo-only", action="store_true")

    all_workers = sub.add_parser("all", help="run ingress + debounce + respond together")
    all_workers.add_argument("--db-path", default=_default_db_path())
    all_workers.add_argument("--discord-bot-token", default=os.environ.get("DISCORD_BOT_TOKEN", ""))
    all_workers.add_argument("--discord-channel-id", default=os.environ.get("DISCORD_CHANNEL_ID", ""))
    all_workers.add_argument("--ingress-input-queue", default="discord_incoming")
    all_workers.add_argument("--debounce-output-queue", default="discord_debounced")
    all_workers.add_argument("--ingress-poll-seconds", type=float, default=2.0)
    all_workers.add_argument("--ingress-fetch-limit", type=int, default=50)
    all_workers.add_argument("--backfill-on-first-run", action="store_true")
    all_workers.add_argument("--debounce-seconds", type=float, default=15.0)
    all_workers.add_argument("--debounce-poll-seconds", type=float, default=0.5)
    all_workers.add_argument("--debounce-lease-seconds", type=float, default=60.0)
    all_workers.add_argument("--debounce-lease-limit", type=int, default=100)
    all_workers.add_argument("--responder-poll-seconds", type=float, default=1.0)
    all_workers.add_argument("--responder-lease-seconds", type=float, default=120.0)
    all_workers.add_argument("--responder-lease-limit", type=int, default=1)
    all_workers.add_argument("--responder-retry-delay-seconds", type=float, default=3.0)
    all_workers.add_argument("--queue-wait-seconds", type=float, default=15.0)
    all_workers.add_argument("--conversation-idle-timeout-seconds", type=float, default=300.0)
    all_workers.add_argument("--queue-poll-seconds", type=float, default=1.0)
    all_workers.add_argument("--working-dir", default=_default_working_dir())
    all_workers.add_argument("--echo-only", action="store_true")

    status = sub.add_parser("status", help="show queue stats and cursor state")
    status.add_argument("--db-path", default=_default_db_path())

    return parser


async def _async_main(args: argparse.Namespace) -> int:
    if args.command == "cli":
        working_dir = os.path.abspath(args.working_dir)
        if args.standalone:
            task = args.standalone if isinstance(args.standalone, str) and args.standalone is not True else args.task
            if not task:
                raise SystemExit("--standalone requires a task (--standalone 'task' or -p 'task' --standalone)")
            await run_standalone(task, working_dir)
            return 0
        if args.task:
            await run_machine(args.task, working_dir)
            return 0
        await repl(working_dir)
        return 0

    if args.command == "ingress":
        return await _run_ingress(args)
    if args.command == "debounce":
        return await _run_debounce(args)
    if args.command == "respond":
        return await _run_responder(args)
    if args.command == "all":
        return await _run_all(args)
    if args.command == "status":
        return _run_status(args)

    raise SystemExit(f"unknown command: {args.command}")


def main() -> None:
    _load_runtime_env_from_conf()
    parser = _build_parser()
    args = parser.parse_args()
    code = asyncio.run(_async_main(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
