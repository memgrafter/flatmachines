"""Unit tests for clone_machine tool providers."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clone_machine.tools import GeneratedToolProvider, ParentToolProvider


class _FakeProc:
    def __init__(self, *, returncode: int | None, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.terminated = False
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def terminate(self):
        self.terminated = True
        self.returncode = self.returncode if self.returncode is not None else -15

    def kill(self):
        self.killed = True
        self.returncode = self.returncode if self.returncode is not None else -9

    async def wait(self):
        if self.returncode is None:
            self.returncode = -15
        return self.returncode


def _bind(provider: ParentToolProvider) -> None:
    provider.bind_machine(SimpleNamespace())


@pytest.mark.asyncio
async def test_parent_provider_requires_bind_machine():
    provider = ParentToolProvider()

    result = await provider.execute_tool("generate_native_tool", "tc1", {})

    assert result.is_error is True
    assert "not bound" in result.content.lower()


@pytest.mark.asyncio
async def test_parent_provider_unknown_tool_returns_error():
    provider = ParentToolProvider()
    _bind(provider)

    result = await provider.execute_tool("does_not_exist", "tc1", {})

    assert result.is_error is True
    assert "unknown tool" in result.content.lower()


@pytest.mark.asyncio
async def test_generate_native_tool_writes_manifest_and_module():
    provider = ParentToolProvider()
    _bind(provider)

    result = await provider.execute_tool("generate_native_tool", "tc1", {})
    data = json.loads(result.content)

    assert result.is_error is False
    assert data["status"] == "generated"
    assert len(data["run_id"]) == 10
    assert data["tool_name"].startswith("generated_native_tool_")

    artifact_dir = Path(data["artifact_dir"])
    assert artifact_dir.exists()

    manifest_path = artifact_dir / "tool_manifest.json"
    module_path = artifact_dir / "generated_tool.py"
    assert manifest_path.exists()
    assert module_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["run_id"] == data["run_id"]
    assert manifest["tool_name"] == data["tool_name"]
    assert manifest["entrypoint"] == "run"
    assert Path(manifest["module_file"]) == module_path


@pytest.mark.asyncio
async def test_generated_tool_supports_durable_put_get_and_cross_run_reuse(monkeypatch, tmp_path):
    monkeypatch.setenv("CLONE_MACHINE_TOOL_STORE_DIR", str(tmp_path / "store"))

    provider = ParentToolProvider()
    _bind(provider)

    generated = await provider.execute_tool(
        "generate_native_tool",
        "tc0",
        {"namespace": "shared demo", "reuse_store": True},
    )
    generated_data = json.loads(generated.content)

    first_artifact = Path(generated_data["artifact_dir"])
    first_provider = GeneratedToolProvider(first_artifact)
    tool_name = generated_data["tool_name"]

    put = await first_provider.execute_tool(
        tool_name,
        "child1",
        {"operation": "put", "key": "latest_run", "value": "abc123"},
    )
    get = await first_provider.execute_tool(
        tool_name,
        "child2",
        {"operation": "get", "key": "latest_run"},
    )
    listing = await first_provider.execute_tool(tool_name, "child3", {"operation": "list", "limit": 5})

    put_payload = json.loads(put.content)
    get_payload = json.loads(get.content)
    list_payload = json.loads(listing.content)

    assert put_payload["status"] == "ok"
    assert put_payload["operation"] == "put"
    assert get_payload["status"] == "ok"
    assert get_payload["found"] is True
    assert get_payload["value"] == "abc123"
    assert "latest_run" in list_payload["keys"]

    generated_again = await provider.execute_tool(
        "generate_native_tool",
        "tc4",
        {"namespace": "shared demo", "reuse_store": True},
    )
    generated_again_data = json.loads(generated_again.content)

    second_artifact = Path(generated_again_data["artifact_dir"])
    second_provider = GeneratedToolProvider(second_artifact)

    reused_get = await second_provider.execute_tool(
        generated_again_data["tool_name"],
        "child4",
        {"operation": "get", "key": "latest_run"},
    )
    reused_payload = json.loads(reused_get.content)

    assert reused_payload["status"] == "ok"
    assert reused_payload["found"] is True
    assert reused_payload["value"] == "abc123"


@pytest.mark.asyncio
async def test_launch_generated_machine_requires_generation_first():
    provider = ParentToolProvider()
    _bind(provider)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})

    assert result.is_error is True
    assert "generate_native_tool" in result.content


@pytest.mark.asyncio
async def test_launch_generated_machine_handles_subprocess_failure(monkeypatch):
    provider = ParentToolProvider()
    _bind(provider)
    await provider.execute_tool("generate_native_tool", "tc0", {})

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(returncode=7, stdout=b"out", stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})
    data = json.loads(result.content)

    assert result.is_error is True
    assert data["status"] == "subprocess_failed"
    assert data["returncode"] == 7
    assert data["stderr"] == "boom"


@pytest.mark.asyncio
async def test_launch_generated_machine_handles_missing_result_file(monkeypatch):
    provider = ParentToolProvider()
    _bind(provider)
    await provider.execute_tool("generate_native_tool", "tc0", {})

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})
    data = json.loads(result.content)

    assert result.is_error is True
    assert data["status"] == "missing_child_result"


@pytest.mark.asyncio
async def test_launch_generated_machine_success(monkeypatch):
    provider = ParentToolProvider()
    _bind(provider)
    generated = await provider.execute_tool("generate_native_tool", "tc0", {})
    generated_data = json.loads(generated.content)
    artifact_dir = Path(generated_data["artifact_dir"])

    async def _fake_exec(*args, **kwargs):
        args = list(args)
        result_file = Path(args[args.index("--result-file") + 1])
        result_file.write_text(json.dumps({"execution_id": "child-1", "result": {"ok": True}}))
        return _FakeProc(returncode=0, stdout=b"child ok")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})
    data = json.loads(result.content)

    assert result.is_error is False
    assert data["status"] == "launched_subprocess"
    assert data["child_payload"]["execution_id"] == "child-1"
    assert data["child_payload"]["result"] == {"ok": True}
    assert data["artifacts_retained"] is False
    assert artifact_dir.exists() is False


@pytest.mark.asyncio
async def test_launch_generated_machine_timeout(monkeypatch):
    provider = ParentToolProvider(launch_timeout_seconds=0.01)
    _bind(provider)
    await provider.execute_tool("generate_native_tool", "tc0", {})

    proc = _FakeProc(returncode=None)

    async def _hang_communicate():
        await asyncio.sleep(1.0)
        return b"", b""

    proc.communicate = _hang_communicate

    async def _fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})
    data = json.loads(result.content)

    assert result.is_error is True
    assert data["status"] == "subprocess_timeout"
    assert proc.terminated is True


def test_generated_tool_provider_loads_manifest_and_definition(tmp_path):
    module_file = tmp_path / "generated_tool.py"
    module_file.write_text(
        "def run(arguments: dict) -> str:\n"
        "    return 'echo: ' + str(arguments.get('text', ''))\n"
    )

    manifest = {
        "tool_name": "generated_native_tool_test",
        "description": "test tool",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "module_file": str(module_file),
        "entrypoint": "run",
    }
    (tmp_path / "tool_manifest.json").write_text(json.dumps(manifest))

    provider = GeneratedToolProvider(tmp_path)
    defs = provider.get_tool_definitions()

    assert defs[0]["function"]["name"] == "generated_native_tool_test"


@pytest.mark.asyncio
async def test_generated_tool_provider_execute_and_unknown_tool(tmp_path):
    module_file = tmp_path / "generated_tool.py"
    module_file.write_text(
        "def run(arguments: dict) -> str:\n"
        "    return 'echo: ' + str(arguments.get('text', ''))\n"
    )

    manifest = {
        "tool_name": "generated_native_tool_test",
        "description": "test tool",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        "module_file": str(module_file),
        "entrypoint": "run",
    }
    (tmp_path / "tool_manifest.json").write_text(json.dumps(manifest))

    provider = GeneratedToolProvider(tmp_path)

    ok = await provider.execute_tool("generated_native_tool_test", "tc1", {"text": "hi"})
    bad = await provider.execute_tool("wrong_name", "tc2", {"text": "hi"})

    assert ok.is_error is False
    assert ok.content == "echo: hi"
    assert bad.is_error is True
    assert "unknown generated tool" in bad.content.lower()


@pytest.mark.asyncio
async def test_keep_artifacts_flag_retains_generated_artifacts(monkeypatch):
    provider = ParentToolProvider(keep_artifacts=True)
    _bind(provider)
    generated = await provider.execute_tool("generate_native_tool", "tc0", {})
    generated_data = json.loads(generated.content)
    artifact_dir = Path(generated_data["artifact_dir"])

    async def _fake_exec(*args, **kwargs):
        args = list(args)
        result_file = Path(args[args.index("--result-file") + 1])
        result_file.write_text(json.dumps({"execution_id": "child-1", "result": {"ok": True}}))
        return _FakeProc(returncode=0, stdout=b"child ok")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    result = await provider.execute_tool("launch_generated_machine", "tc1", {})
    data = json.loads(result.content)

    assert data["artifacts_retained"] is True
    assert artifact_dir.exists() is True


def test_generated_tool_provider_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        GeneratedToolProvider(tmp_path)


def test_generated_tool_provider_missing_entrypoint_raises(tmp_path):
    module_file = tmp_path / "generated_tool.py"
    module_file.write_text("def not_run(arguments: dict) -> str:\n    return 'x'\n")

    manifest = {
        "tool_name": "generated_native_tool_test",
        "description": "test tool",
        "parameters": {"type": "object", "properties": {}},
        "module_file": str(module_file),
        "entrypoint": "run",
    }
    (tmp_path / "tool_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="Entrypoint"):
        GeneratedToolProvider(tmp_path)
