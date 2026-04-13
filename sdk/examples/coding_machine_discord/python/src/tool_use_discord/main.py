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

from flatmachines import FlatMachine

from .debounce import DebounceService
from .discord_api import DiscordAPI
from .discord_ingress import DiscordIngressService
from .hooks import CLIToolHooks
from .messages_backend import SQLiteMessageBackend
from .responder import BatchResponder, DiscordResponderService, EchoBatchResponder

# Suppress validation warnings until schemas are regenerated
warnings.filterwarnings("ignore", message=".*validation.*")
warnings.filterwarnings("ignore", message=".*Flatmachine.*")
warnings.filterwarnings("ignore", message=".*Flatagent.*")

# Quiet by default — set LOG_LEVEL=INFO or LOG_LEVEL=DEBUG to see logs
_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines", "LiteLLM"):
    logging.getLogger(_name).setLevel(_log_level)


class DiscordQueueHumanHooks(CLIToolHooks):
    """Human-review hook backed by the debounced Discord queue.

    Behavior:
    - post model response to Discord
    - wait for queue window baseline (minus model latency)
    - drain queued user batches for this conversation
    - if messages exist: append to tool-loop chain and continue
    - otherwise: approve and end machine execution
    """

    def __init__(
        self,
        *,
        working_dir: str,
        api: DiscordAPI,
        backend: SQLiteMessageBackend,
        conversation_key: str,
        input_queue: str,
        queue_wait_seconds: float,
        conversation_idle_timeout_seconds: float,
        queue_poll_seconds: float,
        queue_worker_id: str,
    ):
        super().__init__(working_dir=working_dir, auto_approve=False)
        self.api = api
        self.backend = backend
        self.conversation_key = conversation_key
        self.input_queue = input_queue
        self.queue_wait_seconds = queue_wait_seconds
        self.conversation_idle_timeout_seconds = conversation_idle_timeout_seconds
        self.queue_poll_seconds = queue_poll_seconds
        self.queue_worker_id = queue_worker_id
        self._work_started_at: Optional[float] = None
        self.post_count = 0

    def on_state_enter(self, state_name: str, context: dict[str, Any]) -> dict[str, Any]:
        if state_name == "work":
            self._work_started_at = time.monotonic()
        return context

    async def on_action(self, action_name: str, context: dict[str, Any]) -> dict[str, Any]:
        if action_name == "human_review":
            return await self._human_review_async(context)
        return context

    async def _human_review_async(self, context: dict[str, Any]) -> dict[str, Any]:
        result_text = str(context.get("result", "")).strip()
        if result_text:
            await asyncio.to_thread(self.api.post_channel_message, result_text)
            self.post_count += 1

        elapsed = 0.0
        if self._work_started_at is not None:
            elapsed = max(0.0, time.monotonic() - self._work_started_at)

        extra_wait = max(0.0, self.queue_wait_seconds - elapsed)
        if extra_wait > 0:
            await asyncio.sleep(extra_wait)

        queued_batches = await asyncio.to_thread(self._drain_conversation_batches)

        if not queued_batches and self.conversation_idle_timeout_seconds > 0:
            queued_batches = await self._wait_for_conversation_batches(
                timeout_seconds=self.conversation_idle_timeout_seconds,
            )

        if queued_batches:
            feedback = build_feedback_from_batches(queued_batches)
            chain = context.get("_tool_loop_chain", [])
            chain.append({"role": "user", "content": feedback})
            context["_tool_loop_chain"] = chain
            context["human_approved"] = False
            print(
                f"[discord-loop] conversation={self.conversation_key} queued_batches={len(queued_batches)} continue",
                flush=True,
            )
        else:
            context["human_approved"] = True
            print(
                f"[discord-loop] conversation={self.conversation_key} no queued feedback within idle timeout; finishing",
                flush=True,
            )

        return context

    async def _wait_for_conversation_batches(self, timeout_seconds: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + max(0.0, timeout_seconds)

        while True:
            batches = await asyncio.to_thread(self._drain_conversation_batches)
            if batches:
                return batches

            if time.monotonic() >= deadline:
                return []

            await asyncio.sleep(max(0.1, self.queue_poll_seconds))

    def _drain_conversation_batches(self) -> list[dict[str, Any]]:
        relevant: list[dict[str, Any]] = []

        while True:
            leased = self.backend.lease(
                queue=self.input_queue,
                worker_id=self.queue_worker_id,
                limit=100,
                lease_seconds=300.0,
            )
            if not leased:
                break

            ack_ids: list[int] = []
            return_ids: list[int] = []

            for message in leased:
                if message.conversation_key == self.conversation_key:
                    relevant.append(message.payload)
                    ack_ids.append(message.id)
                else:
                    return_ids.append(message.id)

            if ack_ids:
                self.backend.ack(ack_ids)

            for message_id in return_ids:
                self.backend.nack(message_id, delay_seconds=0.0)

            # Avoid hot-looping on unrelated leased messages.
            if not ack_ids:
                break

        return relevant


class CodingMachineBatchResponder(BatchResponder):
    """Responder that routes debounced Discord batches through the copied coding machine."""

    def __init__(
        self,
        *,
        working_dir: str,
        api: DiscordAPI,
        backend: SQLiteMessageBackend,
        input_queue: str,
        queue_wait_seconds: float,
        conversation_idle_timeout_seconds: float,
        queue_poll_seconds: float,
    ):
        self.working_dir = os.path.abspath(working_dir)
        self.api = api
        self.backend = backend
        self.input_queue = input_queue
        self.queue_wait_seconds = queue_wait_seconds
        self.conversation_idle_timeout_seconds = conversation_idle_timeout_seconds
        self.queue_poll_seconds = queue_poll_seconds

    async def compose_reply(self, batch: dict[str, Any]) -> Optional[str]:
        conversation_key = str(batch.get("conversation_key") or self.api.channel_id)
        batch_messages = batch.get("messages")
        if not isinstance(batch_messages, list):
            batch_messages = []
        latest_request = extract_latest_request(batch_messages)

        hooks = DiscordQueueHumanHooks(
            working_dir=self.working_dir,
            api=self.api,
            backend=self.backend,
            conversation_key=conversation_key,
            input_queue=self.input_queue,
            queue_wait_seconds=self.queue_wait_seconds,
            conversation_idle_timeout_seconds=self.conversation_idle_timeout_seconds,
            queue_poll_seconds=self.queue_poll_seconds,
            queue_worker_id=f"responder-loop:{conversation_key}",
        )

        result = await run_machine(
            latest_request,
            self.working_dir,
            human_review=True,
            hooks=hooks,
            latest_user_request=latest_request,
            batch_messages=batch_messages,
            queued_message_count=int(batch.get("message_count", 0) or 0),
            conversation_key=conversation_key,
        )

        # Responses are posted turn-by-turn inside the hook.
        # Return None to avoid duplicate posting by DiscordResponderService.
        if hooks.post_count > 0:
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


def build_feedback_from_batches(batches: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for batch in batches:
        messages = batch.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                lines.append(str(message))
                continue
            author = str(message.get("author_name") or message.get("author_id") or "user")
            content = str(message.get("content", "")).strip()
            if content:
                lines.append(f"{author}: {content}")
    if not lines:
        return "(no new user text)"
    return "\n".join(lines)


def _config_path(name: str) -> str:
    return str(Path(__file__).parent.parent.parent.parent / "config" / name)


def _default_db_path() -> str:
    root = Path(__file__).resolve().parents[3]
    return str((root / "data" / "coding_machine_discord.sqlite").resolve())


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
    cli.add_argument("--working-dir", "-w", default=os.getcwd())
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
    respond.add_argument("--working-dir", default=os.getcwd())
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
    all_workers.add_argument("--working-dir", default=os.getcwd())
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
    parser = _build_parser()
    args = parser.parse_args()
    code = asyncio.run(_async_main(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
