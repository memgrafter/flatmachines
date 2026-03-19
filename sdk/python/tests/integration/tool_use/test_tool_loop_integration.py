"""
Integration tests for tool use — end-to-end flows.

Tests the full stack: FlatMachine + mock executor + real ToolProvider with
filesystem side effects + real persistence + hooks with real logic.

Coverage:
- Complete tool-loop workflow with file I/O tools
- Multi-state machine: tool loop → review → done
- Hook-driven file tracking across tool calls
- Mid-loop conditional transition based on tool output
- Crash and resume mid-tool-loop with checkpoint
- Guardrails stopping a runaway loop
- Tool loop with denied tools and policy skip
- Standalone ToolLoopAgent end-to-end with real tools
- Chain preservation for same-state continuation (prefix cache pattern)
- Cross-state tool-loop chain isolation
"""

import asyncio
import json
import os
import shutil
import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional

from flatmachines import FlatMachine, MachineHooks, MemoryBackend
from flatmachines.agents import AgentResult
from flatmachines.persistence import CheckpointManager, MachineSnapshot
from flatagents.tools import ToolResult, ToolProvider
from flatagents.tool_loop import ToolLoopAgent, Guardrails, StopReason


# ---------------------------------------------------------------------------
# Real ToolProvider: filesystem tools
# ---------------------------------------------------------------------------

class FilesystemToolProvider:
    """ToolProvider that reads/writes real files in a temp directory."""

    def __init__(self, working_dir: str):
        self.working_dir = working_dir
        self.call_log: List[Dict[str, Any]] = []

    def get_tool_definitions(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files in a directory",
                    "parameters": {
                        "type": "object",
                        "properties": {"dir": {"type": "string"}},
                    },
                },
            },
        ]

    async def execute_tool(self, name, tool_call_id, arguments):
        self.call_log.append({"name": name, "id": tool_call_id, "args": arguments})

        if name == "read_file":
            path = Path(self.working_dir) / arguments.get("path", "")
            try:
                return ToolResult(content=path.read_text())
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)

        elif name == "write_file":
            path = Path(self.working_dir) / arguments.get("path", "")
            content = arguments.get("content", "")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                return ToolResult(content=f"Wrote {len(content)} bytes to {path.name}")
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)

        elif name == "list_files":
            target = Path(self.working_dir) / arguments.get("dir", ".")
            try:
                files = sorted(p.name for p in target.iterdir() if p.is_file())
                return ToolResult(content="\n".join(files) if files else "(empty)")
            except Exception as e:
                return ToolResult(content=str(e), is_error=True)

        return ToolResult(content=f"Unknown tool: {name}", is_error=True)


# ---------------------------------------------------------------------------
# Mock executor that simulates an LLM with scripted responses
# ---------------------------------------------------------------------------

class ScriptedExecutor:
    """Executor with scripted AgentResult responses.

    Simulates an LLM that follows a predetermined script of tool calls
    and text responses. Used for deterministic integration tests.
    """

    def __init__(self, script: List[AgentResult]):
        self._script = list(script)
        self._idx = 0
        self.calls: List[Dict] = []

    @property
    def metadata(self):
        return {}

    async def execute(self, input_data, context=None):
        return self._next("execute", input_data=input_data)

    async def execute_with_tools(self, input_data, tools, messages=None, context=None):
        return self._next("execute_with_tools", input_data=input_data, tools=tools, messages=messages)

    def _next(self, method, **kwargs):
        self.calls.append({"method": method, **kwargs})
        if self._idx < len(self._script):
            r = self._script[self._idx]
            self._idx += 1
            return r
        return AgentResult(content="(script exhausted)", finish_reason="stop")


def _tr(tool_calls, content=None, cost=0.001):
    """Tool response: AgentResult with tool_calls and finish_reason=tool_use."""
    return AgentResult(
        content=content,
        finish_reason="tool_use",
        tool_calls=tool_calls,
        cost={"total": cost},
        usage={"api_calls": 1, "input_tokens": 100, "output_tokens": 50},
        rendered_user_prompt="rendered: the task",
    )


def _fr(content="Done.", cost=0.001):
    """Final response: AgentResult with content and finish_reason=stop."""
    return AgentResult(
        content=content,
        finish_reason="stop",
        cost={"total": cost},
        usage={"api_calls": 1, "input_tokens": 100, "output_tokens": 50},
        rendered_user_prompt="rendered: the task",
    )


# ---------------------------------------------------------------------------
# Machine config helpers
# ---------------------------------------------------------------------------

def _tool_loop_machine_config(
    tool_loop=True,
    extra_states=None,
    work_transitions=None,
    output_to_context=None,
):
    states = {
        "start": {"type": "initial", "transitions": [{"to": "work"}]},
        "work": {
            "agent": "coder",
            "tool_loop": tool_loop,
            "input": {"task": "{{ context.task }}"},
            "output_to_context": output_to_context or {
                "result": "{{ output.content }}",
                "tool_count": "{{ output._tool_calls_count }}",
                "stop_reason": "{{ output._tool_loop_stop }}",
            },
            "transitions": work_transitions or [{"to": "done"}],
        },
        "done": {
            "type": "final",
            "output": {
                "result": "{{ context.result }}",
                "tool_count": "{{ context.tool_count }}",
                "stop_reason": "{{ context.stop_reason }}",
            },
        },
    }
    if extra_states:
        states.update(extra_states)

    return {
        "spec": "flatmachine",
        "spec_version": "1.1.1",
        "data": {
            "name": "tool-loop-integration",
            "context": {"task": "{{ input.task }}"},
            "agents": {"coder": "./agent.yml"},
            "states": states,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_work_dir(tmp_path):
    """Provide a clean temp working directory."""
    d = tmp_path / "workspace"
    d.mkdir()
    return str(d)


@pytest.fixture(autouse=True)
def cleanup():
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    yield
    for d in [".checkpoints", ".locks"]:
        if os.path.exists(d):
            shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Test: Complete tool loop with file I/O
# ---------------------------------------------------------------------------

class TestCompleteToolLoopWithFileIO:
    """End-to-end: agent reads a file, writes a summary, loop completes."""

    @pytest.mark.asyncio
    async def test_read_then_write(self, tmp_work_dir):
        """Agent reads a file, writes a summary, completes."""
        # Seed the workspace
        Path(tmp_work_dir, "input.txt").write_text("Hello world from integration test")

        provider = FilesystemToolProvider(tmp_work_dir)
        executor = ScriptedExecutor([
            # Turn 1: read the file
            _tr([{"id": "c1", "name": "read_file", "arguments": {"path": "input.txt"}}]),
            # Turn 2: write a summary
            _tr([{"id": "c2", "name": "write_file", "arguments": {
                "path": "summary.txt",
                "content": "Summary: Hello world from integration test",
            }}]),
            # Turn 3: done
            _fr("I read the file and wrote a summary."),
        ])

        machine = FlatMachine(
            config_dict=_tool_loop_machine_config(),
            tool_provider=provider,
            persistence=MemoryBackend(),
        )
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "summarize input.txt"})

        # Verify file was actually written
        summary = Path(tmp_work_dir, "summary.txt").read_text()
        assert "Hello world" in summary

        # Verify machine output
        assert str(result["tool_count"]) == "2"
        assert result["stop_reason"] == "complete"
        assert "summary" in result["result"].lower()

        # Verify provider was called correctly
        assert len(provider.call_log) == 2
        assert provider.call_log[0]["name"] == "read_file"
        assert provider.call_log[1]["name"] == "write_file"


# ---------------------------------------------------------------------------
# Test: Hook-driven file tracking
# ---------------------------------------------------------------------------

class TestHookDrivenFileTracking:
    """Hooks track files modified by tools and expose in context."""

    @pytest.mark.asyncio
    async def test_hooks_track_modified_files(self, tmp_work_dir):
        files_tracked = []

        class FileTrackingHooks(MachineHooks):
            def get_tool_provider(self, state_name):
                return FilesystemToolProvider(tmp_work_dir)

            def on_tool_result(self, state_name, tool_result, context):
                if tool_result["name"] == "write_file" and not tool_result["is_error"]:
                    path = tool_result["arguments"].get("path", "")
                    context.setdefault("files_modified", [])
                    if path not in context["files_modified"]:
                        context["files_modified"].append(path)
                    files_tracked.append(path)
                return context

        executor = ScriptedExecutor([
            _tr([{"id": "c1", "name": "write_file", "arguments": {"path": "a.txt", "content": "aaa"}}]),
            _tr([{"id": "c2", "name": "write_file", "arguments": {"path": "b.txt", "content": "bbb"}}]),
            _tr([{"id": "c3", "name": "write_file", "arguments": {"path": "a.txt", "content": "aaa v2"}}]),
            _fr("Wrote three files."),
        ])

        cfg = _tool_loop_machine_config(output_to_context={
            "result": "{{ output.content }}",
            "tool_count": "{{ output._tool_calls_count }}",
            "stop_reason": "{{ output._tool_loop_stop }}",
            "files": "{{ context.files_modified }}",
        })
        machine = FlatMachine(config_dict=cfg, hooks=FileTrackingHooks(), persistence=MemoryBackend())
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "write files"})

        # Files actually exist
        assert Path(tmp_work_dir, "a.txt").read_text() == "aaa v2"
        assert Path(tmp_work_dir, "b.txt").read_text() == "bbb"

        # Hook saw all 3 writes, but deduped to 2 unique paths
        assert files_tracked == ["a.txt", "b.txt", "a.txt"]

        # Result should report 3 tool calls
        assert str(result["tool_count"]) == "3"


# ---------------------------------------------------------------------------
# Test: Mid-loop conditional transition
# ---------------------------------------------------------------------------

class TestMidLoopConditionalTransition:
    """Hook detects dangerous operation → transition fires mid-loop."""

    @pytest.mark.asyncio
    async def test_write_to_sensitive_path_triggers_review(self, tmp_work_dir):
        class SafetyHooks(MachineHooks):
            def get_tool_provider(self, state_name):
                return FilesystemToolProvider(tmp_work_dir)

            def on_tool_result(self, state_name, tool_result, context):
                if tool_result["name"] == "write_file":
                    path = tool_result["arguments"].get("path", "")
                    if "sensitive" in path:
                        context["needs_review"] = True
                        context["sensitive_path"] = path
                return context

        executor = ScriptedExecutor([
            # Batch: safe write + sensitive write + another write
            _tr([
                {"id": "c1", "name": "write_file", "arguments": {"path": "safe.txt", "content": "ok"}},
                {"id": "c2", "name": "write_file", "arguments": {"path": "sensitive/config.yml", "content": "secret"}},
                {"id": "c3", "name": "write_file", "arguments": {"path": "other.txt", "content": "more"}},
            ]),
            _fr("unreachable"),
        ])

        cfg = _tool_loop_machine_config(
            work_transitions=[
                {"condition": "context.needs_review", "to": "review"},
                {"to": "done"},
            ],
            extra_states={
                "review": {
                    "type": "final",
                    "output": {
                        "result": "blocked",
                        "sensitive_path": "{{ context.sensitive_path }}",
                    },
                },
            },
        )

        machine = FlatMachine(config_dict=cfg, hooks=SafetyHooks(), persistence=MemoryBackend())
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "write stuff"})

        # Transition should have fired after sensitive write, before other.txt
        assert result["result"] == "blocked"
        assert result["sensitive_path"] == "sensitive/config.yml"

        # safe.txt and sensitive file should exist
        assert Path(tmp_work_dir, "safe.txt").exists()
        assert Path(tmp_work_dir, "sensitive/config.yml").exists()

        # other.txt should NOT exist — loop exited before it
        assert not Path(tmp_work_dir, "other.txt").exists()


# ---------------------------------------------------------------------------
# Test: Guardrails stopping a runaway loop
# ---------------------------------------------------------------------------

class TestGuardrailsStopRunaway:

    @pytest.mark.asyncio
    async def test_max_turns_stops_loop(self, tmp_work_dir):
        """max_turns guardrail stops an agent that keeps calling tools."""
        provider = FilesystemToolProvider(tmp_work_dir)

        # Script: agent keeps calling list_files forever
        script = [
            _tr([{"id": f"c{i}", "name": "list_files", "arguments": {"dir": "."}}])
            for i in range(20)
        ]
        executor = ScriptedExecutor(script)

        cfg = _tool_loop_machine_config(
            tool_loop={"max_turns": 3, "total_timeout": 600},
        )

        machine = FlatMachine(config_dict=cfg, tool_provider=provider, persistence=MemoryBackend())
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "keep listing"})

        assert result["stop_reason"] == "max_turns"
        assert int(result["tool_count"]) == 3  # one tool call per turn


# ---------------------------------------------------------------------------
# Test: Denied tools at machine level
# ---------------------------------------------------------------------------

class TestDeniedToolsIntegration:

    @pytest.mark.asyncio
    async def test_denied_tool_not_executed(self, tmp_work_dir):
        """Denied tools produce error messages but don't execute."""
        provider = FilesystemToolProvider(tmp_work_dir)

        executor = ScriptedExecutor([
            _tr([
                {"id": "c1", "name": "read_file", "arguments": {"path": "x.txt"}},
                {"id": "c2", "name": "write_file", "arguments": {"path": "danger.txt", "content": "bad"}},
            ]),
            _fr("I tried to write but was denied."),
        ])

        cfg = _tool_loop_machine_config(
            tool_loop={"denied_tools": ["write_file"], "total_timeout": 600},
        )

        machine = FlatMachine(config_dict=cfg, tool_provider=provider, persistence=MemoryBackend())
        machine._agents = {"coder": executor}

        await machine.execute(input={"task": "test"})

        # read_file was called, write_file was not
        executed_tools = [c["name"] for c in provider.call_log]
        assert "read_file" in executed_tools
        assert "write_file" not in executed_tools

        # danger.txt should not exist
        assert not Path(tmp_work_dir, "danger.txt").exists()


# ---------------------------------------------------------------------------
# Test: Crash and resume mid-tool-loop
# ---------------------------------------------------------------------------

class TestCrashResumeMidToolLoop:
    """Crash during hook execution, resume from checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_after_crash_in_hook(self, tmp_work_dir):
        """Machine crashes in on_tool_result hook, checkpoint exists for resume."""
        provider = FilesystemToolProvider(tmp_work_dir)

        class CrashingHooks(MachineHooks):
            """Hook that crashes after the second tool result."""
            def __init__(self):
                self.result_count = 0

            def get_tool_provider(self, state_name):
                return provider

            def on_tool_result(self, state_name, tool_result, context):
                self.result_count += 1
                if self.result_count == 2:
                    raise RuntimeError("Simulated crash in hook!")
                return context

        executor = ScriptedExecutor([
            _tr([
                {"id": "c1", "name": "write_file", "arguments": {"path": "file1.txt", "content": "one"}},
                {"id": "c2", "name": "write_file", "arguments": {"path": "file2.txt", "content": "two"}},
            ]),
            _fr("done"),
        ])

        cfg = _tool_loop_machine_config()
        cfg["data"]["persistence"] = {"enabled": True, "backend": "local"}

        machine1 = FlatMachine(config_dict=cfg, hooks=CrashingHooks())
        machine1._agents = {"coder": executor}
        execution_id = machine1.execution_id

        with pytest.raises(RuntimeError, match="Simulated crash in hook"):
            await machine1.execute(input={"task": "write files"})

        # file1.txt should exist (written before crash, first tool call succeeded)
        assert Path(tmp_work_dir, "file1.txt").read_text() == "one"

        # file2.txt should also exist (tool executed, but hook crashed after)
        assert Path(tmp_work_dir, "file2.txt").read_text() == "two"

        # Checkpoint should exist with tool_loop_state from first tool call
        machine2 = FlatMachine(config_dict=cfg, tool_provider=provider)
        snapshot = await CheckpointManager(
            machine2.persistence, execution_id
        ).load_latest()

        assert snapshot is not None
        # The checkpoint from the first successful tool call should have been saved
        assert snapshot.tool_loop_state is not None
        assert snapshot.tool_loop_state["tool_calls_count"] >= 1
        assert len(snapshot.tool_loop_state["chain"]) >= 2


# ---------------------------------------------------------------------------
# Test: Checkpoint contains full tool loop state
# ---------------------------------------------------------------------------

class TestCheckpointToolLoopState:

    @pytest.mark.asyncio
    async def test_checkpoint_has_chain_and_metrics(self, tmp_work_dir):
        """Checkpoint after tool call has chain, turns, cost."""
        backend = MemoryBackend()
        provider = FilesystemToolProvider(tmp_work_dir)

        Path(tmp_work_dir, "data.txt").write_text("test data")

        executor = ScriptedExecutor([
            _tr([{"id": "c1", "name": "read_file", "arguments": {"path": "data.txt"}}],
                cost=0.005),
            _tr([{"id": "c2", "name": "list_files", "arguments": {"dir": "."}}],
                cost=0.003),
            _fr("Analysis complete.", cost=0.002),
        ])

        machine = FlatMachine(
            config_dict=_tool_loop_machine_config(),
            tool_provider=provider,
            persistence=backend,
        )
        machine._agents = {"coder": executor}

        await machine.execute(input={"task": "analyze"})

        # Find tool_call checkpoints
        prefix = f"{machine.execution_id}/"
        snapshots = []
        for key, data in backend._store.items():
            if key.startswith(prefix) and key.endswith(".json"):
                snap = MachineSnapshot(**json.loads(data.decode("utf-8")))
                if snap.event == "tool_call":
                    snapshots.append(snap)

        assert len(snapshots) >= 1

        # Last checkpoint should have cumulative state
        last = max(snapshots, key=lambda s: s.tool_loop_state["tool_calls_count"])
        tls = last.tool_loop_state
        assert tls["tool_calls_count"] == 2
        assert tls["turns"] == 2
        assert tls["loop_cost"] == pytest.approx(0.008)
        # Chain should have user, assistant, tool messages
        roles = [m["role"] for m in tls["chain"]]
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles


# ---------------------------------------------------------------------------
# Test: Standalone ToolLoopAgent with real tools
# ---------------------------------------------------------------------------

class TestStandaloneToolLoopAgent:
    """ToolLoopAgent (no machine) with real filesystem tools."""

    @pytest.mark.asyncio
    async def test_standalone_read_write_cycle(self, tmp_work_dir):
        """ToolLoopAgent reads a file, writes output, completes."""
        from unittest.mock import AsyncMock, MagicMock
        from flatagents.baseagent import FinishReason

        # Seed workspace
        Path(tmp_work_dir, "readme.md").write_text("# Project\nA test project.")

        provider = FilesystemToolProvider(tmp_work_dir)

        # Mock agent that follows a script
        call_idx = 0

        def make_resp(content=None, finish_reason=FinishReason.STOP, tool_calls=None):
            resp = MagicMock()
            resp.content = content
            resp.finish_reason = finish_reason
            resp.tool_calls = tool_calls
            resp.error = None
            resp.usage = MagicMock(
                input_tokens=50, output_tokens=25, total_tokens=75,
                cost=MagicMock(total=0.001),
                cache_read_tokens=0, cache_write_tokens=0,
            )
            resp.rendered_user_prompt = "summarize readme.md"
            return resp

        def make_tc(id, tool, arguments):
            tc = MagicMock()
            tc.id = id
            tc.tool = tool
            tc.arguments = arguments
            return tc

        responses = [
            make_resp(
                finish_reason=FinishReason.TOOL_USE,
                tool_calls=[make_tc("c1", "read_file", {"path": "readme.md"})],
            ),
            make_resp(
                finish_reason=FinishReason.TOOL_USE,
                tool_calls=[make_tc("c2", "write_file", {
                    "path": "summary.txt",
                    "content": "This is a test project.",
                })],
            ),
            make_resp(content="I summarized the readme.", finish_reason=FinishReason.STOP),
        ]

        agent = AsyncMock()
        resp_iter = iter(responses)
        agent.call = AsyncMock(side_effect=lambda **kwargs: next(resp_iter))

        loop_agent = ToolLoopAgent(
            agent=agent,
            tool_provider=provider,
            guardrails=Guardrails(max_turns=10, tool_timeout=5.0),
        )

        result = await loop_agent.run(task="summarize readme.md")

        assert result.stop_reason == StopReason.COMPLETE
        assert result.tool_calls_count == 2
        assert result.turns == 3

        # File was actually created
        assert Path(tmp_work_dir, "summary.txt").read_text() == "This is a test project."


# ---------------------------------------------------------------------------
# Test: Multi-state machine with tool loop feeding review
# ---------------------------------------------------------------------------

class TestMultiStateMachineWithToolLoop:
    """Tool loop → action state → conditional → done."""

    @pytest.mark.asyncio
    async def test_tool_loop_then_review_action(self, tmp_work_dir):
        """Work state → review action checks output → done."""
        provider = FilesystemToolProvider(tmp_work_dir)

        executor = ScriptedExecutor([
            _tr([{"id": "c1", "name": "write_file", "arguments": {
                "path": "output.txt", "content": "generated content",
            }}]),
            _fr("I wrote the output file."),
        ])

        class ReviewHooks(MachineHooks):
            def __init__(self, wd):
                self._wd = wd
            def get_tool_provider(self, state_name):
                return provider
            def on_action(self, action_name, context):
                if action_name == "verify_output":
                    path = Path(self._wd) / "output.txt"
                    context["output_exists"] = path.exists()
                    if path.exists():
                        context["output_size"] = len(path.read_text())
                return context

        cfg = {
            "spec": "flatmachine",
            "spec_version": "1.1.1",
            "data": {
                "name": "multi-state",
                "context": {"task": "{{ input.task }}"},
                "agents": {"coder": "./agent.yml"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "work"}]},
                    "work": {
                        "agent": "coder",
                        "tool_loop": True,
                        "input": {"task": "{{ context.task }}"},
                        "output_to_context": {"result": "{{ output.content }}"},
                        "transitions": [{"to": "verify"}],
                    },
                    "verify": {
                        "action": "verify_output",
                        "transitions": [
                            {"condition": "context.output_exists", "to": "done"},
                            {"to": "fail"},
                        ],
                    },
                    "done": {
                        "type": "final",
                        "output": {
                            "result": "{{ context.result }}",
                            "output_size": "{{ context.output_size }}",
                        },
                    },
                    "fail": {
                        "type": "final",
                        "output": {"result": "verification failed"},
                    },
                },
            },
        }

        machine = FlatMachine(
            config_dict=cfg,
            hooks=ReviewHooks(tmp_work_dir),
            persistence=MemoryBackend(),
        )
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "generate output"})

        assert "I wrote the output" in result["result"]
        assert int(result["output_size"]) == len("generated content")


# ---------------------------------------------------------------------------
# Test: Chain preservation across re-entry (prefix cache pattern)
# ---------------------------------------------------------------------------

class TestChainPreservation:
    """Tool loop saves chain to context for potential continuation."""

    @pytest.mark.asyncio
    async def test_chain_saved_to_context(self, tmp_work_dir):
        """After tool loop completes, _tool_loop_chain is in context."""
        provider = FilesystemToolProvider(tmp_work_dir)

        executor = ScriptedExecutor([
            _tr([{"id": "c1", "name": "list_files", "arguments": {"dir": "."}}]),
            _fr("Listed the files."),
        ])

        saved_context = {}

        class ChainCheckHooks(MachineHooks):
            def get_tool_provider(self, state_name):
                return provider
            def on_state_exit(self, state_name, context, output):
                if state_name == "work":
                    saved_context.update(context)
                return output

        machine = FlatMachine(
            config_dict=_tool_loop_machine_config(),
            hooks=ChainCheckHooks(),
            persistence=MemoryBackend(),
        )
        machine._agents = {"coder": executor}

        await machine.execute(input={"task": "list"})

        chain = saved_context.get("_tool_loop_chain")
        assert chain is not None
        assert len(chain) >= 3  # user + assistant(tool_use) + tool + assistant(final)
        roles = [m["role"] for m in chain]
        assert "user" in roles
        assert "tool" in roles


# ---------------------------------------------------------------------------
# Test: Cross-state isolation for tool-loop chain
# ---------------------------------------------------------------------------

class TestCrossStateChainIsolation:
    """A tool-loop state must not reuse another state's chain."""

    @pytest.mark.asyncio
    async def test_second_tool_loop_state_starts_fresh(self, tmp_work_dir):
        provider = FilesystemToolProvider(tmp_work_dir)

        cfg = {
            "spec": "flatmachine",
            "spec_version": "1.1.1",
            "data": {
                "name": "cross-state-chain-isolation",
                "context": {"task": "{{ input.task }}"},
                "agents": {"coder": "./agent.yml"},
                "states": {
                    "start": {"type": "initial", "transitions": [{"to": "work_a"}]},
                    "work_a": {
                        "agent": "coder",
                        "tool_loop": True,
                        "input": {
                            "task": "{{ context.task }}",
                            "phase": "A",
                        },
                        "output_to_context": {"result_a": "{{ output.content }}"},
                        "transitions": [{"to": "work_b"}],
                    },
                    "work_b": {
                        "agent": "coder",
                        "tool_loop": True,
                        "input": {
                            "task": "{{ context.task }}",
                            "phase": "B",
                        },
                        "output_to_context": {"result_b": "{{ output.content }}"},
                        "transitions": [{"to": "done"}],
                    },
                    "done": {
                        "type": "final",
                        "output": {
                            "result_a": "{{ context.result_a }}",
                            "result_b": "{{ context.result_b }}",
                        },
                    },
                },
            },
        }

        executor = ScriptedExecutor([
            AgentResult(content="phase A done", finish_reason="stop", rendered_user_prompt="rendered-a"),
            AgentResult(content="phase B done", finish_reason="stop", rendered_user_prompt="rendered-b"),
        ])

        machine = FlatMachine(
            config_dict=cfg,
            tool_provider=provider,
            persistence=MemoryBackend(),
        )
        machine._agents = {"coder": executor}

        result = await machine.execute(input={"task": "integration task"})

        assert result["result_a"] == "phase A done"
        assert result["result_b"] == "phase B done"
        assert len(executor.calls) == 2

        first = executor.calls[0]
        second = executor.calls[1]

        assert first["method"] == "execute_with_tools"
        assert first["input_data"] == {"task": "integration task", "phase": "A"}
        assert first["messages"] is None

        assert second["method"] == "execute_with_tools"
        assert second["input_data"] == {"task": "integration task", "phase": "B"}
        assert second["messages"] is None
