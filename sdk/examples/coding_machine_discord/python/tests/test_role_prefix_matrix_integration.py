from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from flatmachines import FlatMachine, MemoryBackend, MemorySignalBackend
from flatmachines.agents import AgentResult

from tool_use_discord import main


class _FakeAPI:
    channel_id = "chan-1"

    def __init__(self) -> None:
        self.posts: list[str] = []

    def post_channel_message(self, text: str) -> None:
        self.posts.append(text)


class _AdminBackend:
    def __init__(self, admin_ids: set[str]):
        self._admin_ids = admin_ids

    def is_discord_user_admin(self, user_id: str) -> bool:
        return str(user_id) in self._admin_ids


class _RecordingExecutor:
    def __init__(self, *, role: str, call_log: list[dict[str, Any]]):
        self.role = role
        self.call_log = call_log

    @property
    def metadata(self) -> dict[str, Any]:
        return {}

    async def execute(self, input_data, context=None, session_id=None):
        return await self.execute_with_tools(
            input_data=input_data,
            tools=[],
            messages=None,
            context=context,
            session_id=session_id,
        )

    async def execute_with_tools(self, input_data, tools, messages=None, context=None, session_id=None):
        self.call_log.append(
            {
                "role": self.role,
                "input_data": input_data,
                "messages": messages,
                "session_id": session_id,
            }
        )

        rendered_user_prompt = None
        if input_data:
            rendered_user_prompt = main.build_feedback_from_messages(input_data.get("batch_messages", []))

        return AgentResult(
            content=f"{self.role}-ok",
            finish_reason="stop",
            rendered_user_prompt=rendered_user_prompt,
            usage={"api_calls": 1},
            cost={"total": 0.0},
        )


@dataclass
class _Case:
    name: str
    rounds: list[list[dict[str, Any]]]
    expected_roles: list[str]
    feedback_round_for_call: list[int]


def _msg(author_id: str, author_name: str, content: str) -> dict[str, Any]:
    return {
        "author_id": author_id,
        "author_name": author_name,
        "content": content,
    }


def _machine_input_for_round(messages: list[dict[str, Any]], *, backend: _AdminBackend, conversation_key: str) -> dict[str, Any]:
    admin_batch_messages, everyone_batch_messages = main.split_batch_messages_by_admin(messages, backend=backend)
    latest_request = main.extract_latest_request(messages)
    return {
        "task": latest_request,
        "working_dir": ".",
        "latest_user_request": latest_request,
        "batch_messages": messages,
        "admin_batch_messages": admin_batch_messages,
        "everyone_batch_messages": everyone_batch_messages,
        "admin_message_count": len(admin_batch_messages),
        "everyone_message_count": len(everyone_batch_messages),
        "queued_message_count": len(messages),
        "conversation_key": conversation_key,
        "agents_md": "",
    }


def _user_contents(messages: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "user":
            out.append(str(msg.get("content", "")))
    return out


@pytest.mark.parametrize(
    "case",
    [
        _Case(
            name="admin_only",
            rounds=[
                [_msg("admin-1", "alice", "admin round 1")],
                [_msg("admin-1", "alice", "admin round 2")],
                [_msg("admin-1", "alice", "admin round 3")],
            ],
            expected_roles=["admin", "admin", "admin"],
            feedback_round_for_call=[0, 1, 2],
        ),
        _Case(
            name="everyone_only",
            rounds=[
                [_msg("user-1", "bob", "everyone round 1")],
                [_msg("user-1", "bob", "everyone round 2")],
                [_msg("user-1", "bob", "everyone round 3")],
            ],
            expected_roles=["everyone", "everyone", "everyone"],
            feedback_round_for_call=[0, 1, 2],
        ),
        _Case(
            name="admin_then_everyone",
            rounds=[
                [_msg("admin-1", "alice", "admin seed")],
                [_msg("user-1", "bob", "everyone followup 1")],
                [_msg("user-1", "bob", "everyone followup 2")],
            ],
            expected_roles=["admin", "everyone", "everyone"],
            feedback_round_for_call=[0, 1, 2],
        ),
        _Case(
            name="everyone_then_admin",
            rounds=[
                [_msg("user-1", "bob", "everyone seed")],
                [_msg("admin-1", "alice", "admin followup 1")],
                [_msg("admin-1", "alice", "admin followup 2")],
            ],
            expected_roles=["everyone", "admin", "admin"],
            feedback_round_for_call=[0, 1, 2],
        ),
        _Case(
            name="mixed_each_round",
            rounds=[
                [
                    _msg("admin-1", "alice", "admin mixed 1"),
                    _msg("user-1", "bob", "everyone mixed 1"),
                ],
                [
                    _msg("admin-1", "alice", "admin mixed 2"),
                    _msg("user-1", "bob", "everyone mixed 2"),
                ],
                [
                    _msg("admin-1", "alice", "admin mixed 3"),
                    _msg("user-1", "bob", "everyone mixed 3"),
                ],
            ],
            expected_roles=["admin", "everyone", "admin", "everyone", "admin", "everyone"],
            feedback_round_for_call=[0, 0, 1, 1, 2, 2],
        ),
    ],
    ids=lambda c: c.name,
)
def test_role_prefix_accrues_across_round_matrix(case: _Case) -> None:
    async def _run() -> None:
        backend = _AdminBackend(admin_ids={"admin-1"})
        api = _FakeAPI()
        hooks = main.DiscordMachineHooks(working_dir=".", api=api)

        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()

        conversation_key = f"matrix-{case.name}"
        execution_id = main._conversation_execution_id(conversation_key)
        wait_channel = f"discord/{conversation_key}"

        call_log: list[dict[str, Any]] = []
        admin_exec = _RecordingExecutor(role="admin", call_log=call_log)
        everyone_exec = _RecordingExecutor(role="everyone", call_log=call_log)

        machine = FlatMachine(
            config_file=main._config_path("discord_machine.yml"),
            profiles_file=main._config_path("profiles.yml"),
            hooks=hooks,
            persistence=persistence,
            signal_backend=signal_backend,
            _execution_id=execution_id,
        )
        machine._agents = {
            "coder": admin_exec,
            "everyone": everyone_exec,
        }

        first_input = _machine_input_for_round(case.rounds[0], backend=backend, conversation_key=conversation_key)
        await machine.execute(input=first_input, resume_from=execution_id)

        for round_messages in case.rounds[1:]:
            payload = _machine_input_for_round(round_messages, backend=backend, conversation_key=conversation_key)
            await signal_backend.send(wait_channel, payload)
            await machine.execute(input=payload, resume_from=execution_id)

        assert [c["role"] for c in call_log] == case.expected_roles
        assert len(case.feedback_round_for_call) == len(call_log)

        # Session identity is role-specific and stable across time.
        admin_sessions = {c["session_id"] for c in call_log if c["role"] == "admin"}
        everyone_sessions = {c["session_id"] for c in call_log if c["role"] == "everyone"}
        if admin_sessions:
            assert admin_sessions == {f"{conversation_key}::admin"}
        if everyone_sessions:
            assert everyone_sessions == {f"{conversation_key}::everyone"}

        # Prefix continuity: each call after the first sees continuation messages,
        # and includes latest feedback for its mapped round.
        for idx, call in enumerate(call_log):
            if idx == 0:
                continue

            messages = call.get("messages")
            assert isinstance(messages, list) and messages

            round_idx = case.feedback_round_for_call[idx]
            latest_feedback = main.build_feedback_from_messages(case.rounds[round_idx])
            user_text = "\n".join(_user_contents(messages))

            # For mixed rounds, the very first cross-role call may only include a
            # subset of latest lines; require at least one latest line.
            latest_lines = [ln for ln in latest_feedback.splitlines() if ln.strip()]
            assert latest_lines
            assert any(line in user_text for line in latest_lines)

            # Accretion: if this call maps to round N>0, round N-1 feedback should remain too.
            # The very first mixed-role bootstrap round can preserve only a subset
            # of lines, so require at least one previous line.
            if round_idx > 0:
                prev_feedback = main.build_feedback_from_messages(case.rounds[round_idx - 1])
                prev_lines = [ln for ln in prev_feedback.splitlines() if ln.strip()]
                assert prev_lines
                assert any(line in user_text for line in prev_lines)

    asyncio.run(_run())
