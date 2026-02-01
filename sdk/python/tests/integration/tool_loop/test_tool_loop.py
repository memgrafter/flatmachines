"""
Integration tests for multi-round tool calling (tool_loop).

Uses a real HTTP stub server to simulate LLM responses with tool calls.
No mocks - actual HTTP requests are made to verify the full flow.
"""

import asyncio
import json
import os
import uuid
import pytest
from aiohttp import web
from typing import Dict, Any, List

# Set dummy API key for litellm/openai client before importing flatagents
os.environ["OPENAI_API_KEY"] = "sk-stub-test-key-not-real"

from flatagents.flatmachine import FlatMachine
from flatagents.hooks import MachineHooks


class StubLLMServer:
    """
    Stub HTTP server that simulates an OpenAI-compatible chat completions API.

    Supports configurable responses including tool calls for testing
    multi-round tool calling flows.
    """

    def __init__(self):
        self.app = web.Application()
        # Handle both /v1/chat/completions and /chat/completions (litellm uses the latter)
        self.app.router.add_post('/v1/chat/completions', self.handle_chat)
        self.app.router.add_post('/chat/completions', self.handle_chat)
        self.runner = None
        self.site = None
        self.port = None

        # Track requests for assertions
        self.requests: List[Dict[str, Any]] = []

        # Response queue - pop from front for each request
        self.responses: List[Dict[str, Any]] = []

    def add_tool_call_response(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        content: str = ""
    ):
        """Queue a response that includes a tool call."""
        tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
        self.responses.append({
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "stub-model",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments)
                        }
                    }]
                },
                "finish_reason": "tool_calls"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        })

    def add_final_response(self, content: str, output: Dict[str, Any] = None):
        """Queue a final response (no tool calls)."""
        # If output is provided, wrap content as JSON
        if output:
            content = json.dumps(output)

        self.responses.append({
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "stub-model",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        })

    async def handle_chat(self, request: web.Request) -> web.Response:
        """Handle chat completions requests."""
        body = await request.json()
        self.requests.append(body)

        if not self.responses:
            return web.json_response(
                {"error": "No more stubbed responses"},
                status=500
            )

        response = self.responses.pop(0)
        return web.json_response(response)

    async def start(self) -> str:
        """Start the server and return the base URL."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        # Find an available port
        self.site = web.TCPSite(self.runner, 'localhost', 0)
        await self.site.start()

        # Get the actual port
        self.port = self.site._server.sockets[0].getsockname()[1]
        return f"http://localhost:{self.port}"

    async def stop(self):
        """Stop the server."""
        if self.runner:
            await self.runner.cleanup()


class ToolExecutorHooks(MachineHooks):
    """
    Hooks that execute tools and track calls for testing.
    """

    def __init__(self):
        self.tool_calls: List[Dict[str, Any]] = []
        self.tool_results: Dict[str, Any] = {}

    def register_tool(self, name: str, result: Any):
        """Register a tool and its expected result."""
        self.tool_results[name] = result

    def on_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        """Execute a tool call and return the result."""
        self.tool_calls.append({
            "tool": tool_name,
            "arguments": arguments,
        })

        if tool_name in self.tool_results:
            result = self.tool_results[tool_name]
            # If result is callable, call it with arguments
            if callable(result):
                return result(arguments)
            return result

        raise ValueError(f"Unknown tool: {tool_name}")


def get_tool_loop_agent_config(base_url: str) -> Dict[str, Any]:
    """Create an agent config pointing to stub server."""
    return {
        "spec": "flatagent",
        "spec_version": "0.9.0",
        "data": {
            "name": "tool-agent",
            "model": {
                "provider": "openai",
                "name": "stub-model",
                "base_url": base_url
            },
            "system": "You are a helpful assistant that uses tools to answer questions.",
            "user": "Question: {{ input.question }}"
        }
    }


def get_tool_loop_machine_config(base_url: str) -> Dict[str, Any]:
    """Create a machine config with tool_loop enabled."""
    return {
        "spec": "flatmachine",
        "spec_version": "0.9.0",
        "data": {
            "name": "tool-loop-test",
            "context": {
                "question": "{{ input.question }}"
            },
            "agents": {
                "researcher": get_tool_loop_agent_config(base_url)
            },
            "states": {
                "research": {
                    "type": "initial",
                    "agent": "researcher",
                    "tool_loop": {
                        "max_rounds": 5
                    },
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "search",
                                "description": "Search for information",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string"}
                                    },
                                    "required": ["query"]
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "calculate",
                                "description": "Perform a calculation",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "expression": {"type": "string"}
                                    },
                                    "required": ["expression"]
                                }
                            }
                        }
                    ],
                    "input": {
                        "question": "{{ context.question }}"
                    },
                    "output_to_context": {
                        "answer": "{{ output.content }}"
                    },
                    "transitions": [
                        {"to": "done"}
                    ]
                },
                "done": {
                    "type": "final",
                    "output": {
                        "answer": "{{ context.answer }}"
                    }
                }
            }
        }
    }


@pytest.fixture
async def stub_server():
    """Fixture that provides a stub LLM server."""
    server = StubLLMServer()
    base_url = await server.start()
    yield server, base_url
    await server.stop()


class TestToolLoopIntegration:
    """Integration tests for tool_loop feature."""

    @pytest.mark.asyncio
    async def test_single_tool_call_then_response(self, stub_server):
        """Test a single tool call followed by final response."""
        server, base_url = stub_server

        # Setup: LLM calls search tool, then returns final answer
        server.add_tool_call_response(
            tool_name="search",
            arguments={"query": "weather in Paris"}
        )
        server.add_final_response(
            content="The weather in Paris is sunny and 22C."
        )

        # Setup hooks
        hooks = ToolExecutorHooks()
        hooks.register_tool("search", {"results": ["Paris: Sunny, 22C"]})

        # Create and run machine
        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "What's the weather in Paris?"})

        # Verify tool was called
        assert len(hooks.tool_calls) == 1
        assert hooks.tool_calls[0]["tool"] == "search"
        assert hooks.tool_calls[0]["arguments"]["query"] == "weather in Paris"

        # Verify final answer
        assert "sunny" in result["answer"].lower() or "22" in result["answer"]

        # Verify two requests were made to LLM (initial + after tool result)
        assert len(server.requests) == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_sequence(self, stub_server):
        """Test multiple sequential tool calls before final response."""
        server, base_url = stub_server

        # Setup: LLM calls search, then calculate, then returns answer
        server.add_tool_call_response(
            tool_name="search",
            arguments={"query": "population of France"}
        )
        server.add_tool_call_response(
            tool_name="calculate",
            arguments={"expression": "67000000 / 1000000"}
        )
        server.add_final_response(
            content="France has a population of 67 million."
        )

        # Setup hooks
        hooks = ToolExecutorHooks()
        hooks.register_tool("search", {"population": 67000000})
        hooks.register_tool("calculate", {"result": 67})

        # Create and run machine
        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "Population of France in millions?"})

        # Verify both tools were called
        assert len(hooks.tool_calls) == 2
        assert hooks.tool_calls[0]["tool"] == "search"
        assert hooks.tool_calls[1]["tool"] == "calculate"

        # Verify three requests were made to LLM
        assert len(server.requests) == 3

    @pytest.mark.asyncio
    async def test_tool_loop_max_rounds_limit(self, stub_server):
        """Test that tool_loop respects max_rounds limit."""
        server, base_url = stub_server

        # Setup: LLM keeps calling tools (more than max_rounds)
        for i in range(10):
            server.add_tool_call_response(
                tool_name="search",
                arguments={"query": f"query_{i}"}
            )
        # Final response (may not be reached due to max_rounds)
        server.add_final_response(content="Final answer")

        # Setup hooks
        hooks = ToolExecutorHooks()
        hooks.register_tool("search", {"result": "found"})

        # Create machine with max_rounds=3
        config = get_tool_loop_machine_config(base_url)
        config["data"]["states"]["research"]["tool_loop"]["max_rounds"] = 3
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "Test max rounds"})

        # Should have stopped at max_rounds (3 tool calls)
        assert len(hooks.tool_calls) == 3
        assert len(server.requests) == 3

    @pytest.mark.asyncio
    async def test_no_tool_calls_immediate_response(self, stub_server):
        """Test when LLM responds without any tool calls."""
        server, base_url = stub_server

        # Setup: LLM returns answer immediately without tools
        server.add_final_response(
            content="I already know the answer: 42"
        )

        # Setup hooks
        hooks = ToolExecutorHooks()
        hooks.register_tool("search", {"result": "unused"})

        # Create and run machine
        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "What is the answer?"})

        # No tool calls should have been made
        assert len(hooks.tool_calls) == 0

        # Only one request to LLM
        assert len(server.requests) == 1

        # Result should contain the answer
        assert "42" in result["answer"]

    @pytest.mark.asyncio
    async def test_tool_call_with_error_handling(self, stub_server):
        """Test that tool errors are handled gracefully."""
        server, base_url = stub_server

        # Setup: LLM calls tool, tool fails, LLM handles error
        server.add_tool_call_response(
            tool_name="search",
            arguments={"query": "something"}
        )
        server.add_final_response(
            content="I couldn't find the information due to an error."
        )

        # Setup hooks - tool will raise an error
        hooks = ToolExecutorHooks()
        def failing_search(args):
            raise RuntimeError("Search service unavailable")
        hooks.register_tool("search", failing_search)

        # Create and run machine
        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "Test error handling"})

        # Tool was attempted
        assert len(hooks.tool_calls) == 1

        # Machine should have continued and returned a result
        assert "answer" in result

    @pytest.mark.asyncio
    async def test_tool_results_passed_back_to_llm(self, stub_server):
        """Test that tool results are correctly passed back to the LLM."""
        server, base_url = stub_server

        # Setup
        server.add_tool_call_response(
            tool_name="calculate",
            arguments={"expression": "2 + 2"}
        )
        server.add_final_response(content="The answer is 4.")

        # Setup hooks with specific result
        hooks = ToolExecutorHooks()
        hooks.register_tool("calculate", {"result": 4, "expression": "2 + 2"})

        # Create and run machine
        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        await machine.execute(input={"question": "What is 2 + 2?"})

        # Verify second request includes tool result in messages
        assert len(server.requests) >= 2
        second_request = server.requests[1]

        # Should have tool message in messages
        messages = second_request.get("messages", [])
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1

        # Tool result should contain our data
        tool_content = json.loads(tool_messages[0]["content"])
        assert tool_content["result"] == 4

    @pytest.mark.asyncio
    async def test_tool_loop_disabled_no_tools(self, stub_server):
        """Test that without tool_loop, tools are not used."""
        server, base_url = stub_server

        # Setup
        server.add_final_response(content="Direct answer without tools")

        # Create config without tool_loop
        config = get_tool_loop_machine_config(base_url)
        del config["data"]["states"]["research"]["tool_loop"]
        del config["data"]["states"]["research"]["tools"]

        hooks = ToolExecutorHooks()
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "Test no tools"})

        # No tool calls
        assert len(hooks.tool_calls) == 0

        # Request should not include tools
        assert len(server.requests) == 1
        assert "tools" not in server.requests[0] or not server.requests[0].get("tools")


class TestToolLoopWithDynamicTools:
    """Test tool_loop with dynamic tool behavior."""

    @pytest.mark.asyncio
    async def test_tool_with_dynamic_result(self, stub_server):
        """Test tool that returns different results based on input."""
        server, base_url = stub_server

        # LLM will call search twice with different queries
        server.add_tool_call_response(
            tool_name="search",
            arguments={"query": "capital of France"}
        )
        server.add_tool_call_response(
            tool_name="search",
            arguments={"query": "population of Paris"}
        )
        server.add_final_response(
            content="Paris is the capital of France with a population of 2.1 million."
        )

        # Dynamic tool that returns different results
        hooks = ToolExecutorHooks()
        def dynamic_search(args):
            query = args.get("query", "")
            if "capital" in query:
                return {"answer": "Paris"}
            elif "population" in query:
                return {"answer": "2.1 million"}
            return {"answer": "Unknown"}
        hooks.register_tool("search", dynamic_search)

        config = get_tool_loop_machine_config(base_url)
        machine = FlatMachine(config_dict=config, hooks=hooks)

        result = await machine.execute(input={"question": "Tell me about Paris"})

        # Both searches should have been made
        assert len(hooks.tool_calls) == 2
        assert "capital" in hooks.tool_calls[0]["arguments"]["query"]
        assert "population" in hooks.tool_calls[1]["arguments"]["query"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
