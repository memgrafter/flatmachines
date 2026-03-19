"""
Unit tests for MachineResumer and ConfigStoreResumer.

Tests the resume abstraction, content-addressed config store resume,
hooks_registry passthrough, and subclassing for app-specific reconstruction.
"""

import json
import os
from typing import Any

import pytest

from flatmachines import (
    CheckpointManager,
    ConfigStoreResumer,
    ConfigFileResumer,
    FlatMachine,
    HooksRegistry,
    MachineHooks,
    MachineResumer,
    MachineSnapshot,
    MemoryBackend,
    MemoryConfigStore,
    SignalDispatcher,
    config_hash,
)
from flatmachines.dispatch_signals import run_once
from flatmachines.signals import MemorySignalBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WAIT_CONFIG = """\
spec: flatmachine
spec_version: "2.1.0"
data:
  name: resume-test
  context:
    val: null
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
"""

_HOOKS_CONFIG = """\
spec: flatmachine
spec_version: "2.1.0"
data:
  name: hooks-resume-test
  hooks: "tracking"
  context:
    val: null
    tracked: false
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
        tracked: "context.tracked"
"""

_PATH_REFS_CONFIG = """\
spec: flatmachine
spec_version: "2.1.0"
data:
  name: path-refs-resume-test
  agents:
    writer: ./agents/writer.yml
  machines:
    reviewer: ./machines/reviewer.yml
  context:
    val: null
  states:
    start:
      type: initial
      transitions:
        - to: wait
    wait:
      wait_for: "test/ch"
      output_to_context:
        val: "{{ output.v }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        val: "context.val"
"""


@pytest.fixture
def config_file(tmp_path):
    """Write a wait_for machine config to a temp file."""
    p = tmp_path / "machine.yml"
    p.write_text(_WAIT_CONFIG)
    return str(p)


@pytest.fixture
def hooks_config_file(tmp_path):
    """Write a wait_for machine config that references hooks by name."""
    p = tmp_path / "hooks_machine.yml"
    p.write_text(_HOOKS_CONFIG)
    return str(p)


@pytest.fixture
def path_refs_config_file(tmp_path):
    """Write a machine config that includes string/path refs."""
    p = tmp_path / "path_refs_machine.yml"
    p.write_text(_PATH_REFS_CONFIG)
    return str(p)


@pytest.fixture
def backends():
    return MemorySignalBackend(), MemoryBackend(), MemoryConfigStore()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _park(config_file, signal_backend, persistence, config_store):
    """Run a machine until it parks at wait_for. Returns execution_id."""
    m = FlatMachine(
        config_file=config_file,
        persistence=persistence,
        signal_backend=signal_backend,
        config_store=config_store,
    )
    result = await m.execute(input={})
    assert result.get("_waiting") is True
    return m.execution_id


class TrackingHooks(MachineHooks):
    """Simple hooks that mark context so we can verify they were active."""

    def on_state_enter(self, state_name, context):
        context["tracked"] = True
        return context


# ---------------------------------------------------------------------------
# config_hash function
# ---------------------------------------------------------------------------

class TestConfigHash:

    def test_deterministic(self):
        assert config_hash("hello") == config_hash("hello")

    def test_different_content_different_hash(self):
        assert config_hash("a") != config_hash("b")

    def test_returns_hex_string(self):
        h = config_hash("test")
        assert len(h) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# MemoryConfigStore
# ---------------------------------------------------------------------------

class TestMemoryConfigStore:

    @pytest.mark.asyncio
    async def test_put_and_get(self):
        store = MemoryConfigStore()
        h = await store.put("spec: flatmachine")
        raw = await store.get(h)
        assert raw == "spec: flatmachine"

    @pytest.mark.asyncio
    async def test_put_idempotent(self):
        store = MemoryConfigStore()
        h1 = await store.put("content")
        h2 = await store.put("content")
        assert h1 == h2
        assert len(store._store) == 1

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        store = MemoryConfigStore()
        assert await store.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete(self):
        store = MemoryConfigStore()
        h = await store.put("content")
        await store.delete(h)
        assert await store.get(h) is None


# ---------------------------------------------------------------------------
# MachineSnapshot.config_hash
# ---------------------------------------------------------------------------

class TestConfigHashInCheckpoint:

    @pytest.mark.asyncio
    async def test_config_hash_stored_in_snapshot(self, config_file, backends):
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)

        snapshot = await CheckpointManager(persistence, eid).load_latest()
        assert snapshot is not None
        assert snapshot.config_hash is not None
        assert len(snapshot.config_hash) == 64

    @pytest.mark.asyncio
    async def test_config_retrievable_from_store(self, config_file, backends):
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)

        snapshot = await CheckpointManager(persistence, eid).load_latest()
        raw = await config_store.get(snapshot.config_hash)
        assert raw is not None
        assert "resume-test" in raw

    @pytest.mark.asyncio
    async def test_no_config_store_means_no_hash(self, config_file):
        """Without config_store, config_hash is None (backwards compat)."""
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()
        m = FlatMachine(
            config_file=config_file,
            persistence=persistence,
            signal_backend=signal_backend,
            # no config_store
        )
        await m.execute(input={})
        snapshot = await CheckpointManager(persistence, m.execution_id).load_latest()
        assert snapshot.config_hash is None

    @pytest.mark.asyncio
    async def test_same_config_deduplicates(self, config_file, backends):
        """Two machines with the same config share one store entry."""
        signal_backend, persistence, config_store = backends
        await _park(config_file, signal_backend, persistence, config_store)
        await _park(config_file, signal_backend, persistence, config_store)
        assert len(config_store._store) == 1


# ---------------------------------------------------------------------------
# ConfigStoreResumer
# ---------------------------------------------------------------------------

class TestConfigStoreResumer:

    @pytest.mark.asyncio
    async def test_resume_simple(self, config_file, backends):
        """ConfigStoreResumer resumes a parked machine to completion."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)

        await signal_backend.send("test/ch", {"v": "hello"})

        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
        result = await resumer.resume(eid, {"v": "hello"})

        assert result["val"] == "hello"

    @pytest.mark.asyncio
    async def test_resume_with_hooks_registry(self, hooks_config_file, backends):
        """Hooks registry is passed through and hooks resolve on resume."""
        signal_backend, persistence, config_store = backends

        registry = HooksRegistry()
        registry.register("tracking", TrackingHooks)

        m = FlatMachine(
            config_file=hooks_config_file,
            persistence=persistence,
            signal_backend=signal_backend,
            config_store=config_store,
            hooks_registry=registry,
        )
        result = await m.execute(input={})
        assert result.get("_waiting") is True
        eid = m.execution_id

        await signal_backend.send("test/ch", {"v": "world"})

        resumer = ConfigStoreResumer(
            signal_backend, persistence, config_store,
            hooks_registry=registry,
        )
        result = await resumer.resume(eid, {"v": "world"})

        assert result["val"] == "world"
        # TrackingHooks sets context["tracked"] = True (bool);
        # final output resolves "context.tracked" preserving the bool type.
        assert result["tracked"] is True

    @pytest.mark.asyncio
    async def test_resume_with_explicit_hooks(self, config_file, backends):
        """Explicit hooks= are passed through to reconstructed machine."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)

        await signal_backend.send("test/ch", {"v": "hooks"})

        hooks = TrackingHooks()
        resumer = ConfigStoreResumer(
            signal_backend, persistence, config_store, hooks=hooks,
        )
        result = await resumer.resume(eid, {"v": "hooks"})

        assert result["val"] == "hooks"

    @pytest.mark.asyncio
    async def test_resume_no_checkpoint_raises(self, backends):
        """Resuming a nonexistent execution raises RuntimeError."""
        signal_backend, persistence, config_store = backends
        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)

        with pytest.raises(RuntimeError, match="No checkpoint found"):
            await resumer.resume("nonexistent-id", {})

    @pytest.mark.asyncio
    async def test_resume_no_config_hash_raises(self, config_file):
        """Resuming without config_hash in snapshot raises RuntimeError."""
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()
        config_store = MemoryConfigStore()

        # Park without config_store so no hash is stored
        m = FlatMachine(
            config_file=config_file,
            persistence=persistence,
            signal_backend=signal_backend,
        )
        await m.execute(input={})
        eid = m.execution_id

        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)

        with pytest.raises(RuntimeError, match="No config_hash"):
            await resumer.resume(eid, {})

    @pytest.mark.asyncio
    async def test_resume_missing_config_in_store_raises(self, config_file, backends):
        """If config was cleaned up from store, raises RuntimeError."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)

        # Wipe the store
        config_store._store.clear()

        await signal_backend.send("test/ch", {"v": "x"})
        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)

        with pytest.raises(RuntimeError, match="Config not found in store"):
            await resumer.resume(eid, {})


# ---------------------------------------------------------------------------
# Portable resume: string/path refs require resolver
# ---------------------------------------------------------------------------

class TestPortablePathRefs:

    @pytest.mark.asyncio
    async def test_path_refs_without_resolver_fails(
        self,
        path_refs_config_file,
        backends,
    ):
        signal_backend, persistence, config_store = backends
        eid = await _park(path_refs_config_file, signal_backend, persistence, config_store)

        await signal_backend.send("test/ch", {"v": "x"})
        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)

        with pytest.raises(RuntimeError, match="Portable resume does not support string/path refs"):
            await resumer.resume(eid, {"v": "x"})

    @pytest.mark.asyncio
    async def test_path_refs_with_resolver_succeeds(
        self,
        path_refs_config_file,
        backends,
    ):
        signal_backend, persistence, config_store = backends
        eid = await _park(path_refs_config_file, signal_backend, persistence, config_store)

        await signal_backend.send("test/ch", {"v": "ok"})

        async def resolver(*, machine_name, config_hash, ref_kind, ref_name, ref_value):
            # Return inline config dicts for any string ref
            if ref_kind == "machine":
                return {
                    "spec": "flatmachine",
                    "spec_version": "2.1.0",
                    "data": {
                        "name": f"resolved-{ref_name}",
                        "states": {
                            "start": {"type": "initial", "transitions": [{"to": "done"}]},
                            "done": {"type": "final", "output": {}},
                        },
                    },
                }
            return {"spec": "flatagent", "spec_version": "2.1.0", "data": {"model": "dummy"}}

        resumer = ConfigStoreResumer(
            signal_backend,
            persistence,
            config_store,
            ref_resolver=resolver,
        )
        result = await resumer.resume(eid, {"v": "ok"})
        assert result["val"] == "ok"


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

class TestBackwardCompatAlias:

    def test_config_file_resumer_is_config_store_resumer(self):
        assert ConfigFileResumer is ConfigStoreResumer


# ---------------------------------------------------------------------------
# Subclassing
# ---------------------------------------------------------------------------

class TestSubclassing:

    @pytest.mark.asyncio
    async def test_custom_resumer_via_build_machine(self, config_file, backends):
        """Subclass can override build_machine for custom reconstruction."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)
        await signal_backend.send("test/ch", {"v": "custom"})

        build_called = []

        class CustomResumer(ConfigStoreResumer):
            async def build_machine(self, execution_id, snapshot, config_dict):
                build_called.append(execution_id)
                return await super().build_machine(execution_id, snapshot, config_dict)

        resumer = CustomResumer(signal_backend, persistence, config_store)
        result = await resumer.resume(eid, {"v": "custom"})

        assert result["val"] == "custom"
        assert build_called == [eid]

    @pytest.mark.asyncio
    async def test_pure_abc_subclass(self, config_file, backends):
        """A pure MachineResumer subclass works with the dispatcher."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)
        await signal_backend.send("test/ch", {"v": "abc"})

        class PureResumer(MachineResumer):
            async def resume(self, execution_id, signal_data):
                m = FlatMachine(
                    config_file=config_file,
                    persistence=persistence,
                    signal_backend=signal_backend,
                )
                return await m.execute(resume_from=execution_id)

        resumer = PureResumer()
        dispatcher = SignalDispatcher(
            signal_backend, persistence, resumer=resumer,
        )
        results = await dispatcher.dispatch("test/ch")
        assert eid in results


# ---------------------------------------------------------------------------
# Integration with dispatcher / run_once
# ---------------------------------------------------------------------------

class TestDispatcherIntegration:

    @pytest.mark.asyncio
    async def test_dispatcher_accepts_resumer(self, config_file, backends):
        """SignalDispatcher accepts resumer= kwarg."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)
        await signal_backend.send("test/ch", {"v": "dispatch"})

        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
        dispatcher = SignalDispatcher(
            signal_backend, persistence, resumer=resumer,
        )
        results = await dispatcher.dispatch_all()

        assert "test/ch" in results
        assert eid in results["test/ch"]

    @pytest.mark.asyncio
    async def test_run_once_accepts_resumer(self, config_file, backends):
        """run_once() accepts resumer= keyword argument."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)
        await signal_backend.send("test/ch", {"v": "once"})

        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
        results = await run_once(
            signal_backend, persistence, resumer=resumer,
        )

        assert "test/ch" in results
        assert eid in results["test/ch"]

    @pytest.mark.asyncio
    async def test_resumer_takes_precedence_over_resume_fn(self, config_file, backends):
        """When both resumer= and resume_fn= are provided, resumer wins."""
        signal_backend, persistence, config_store = backends
        eid = await _park(config_file, signal_backend, persistence, config_store)
        await signal_backend.send("test/ch", {"v": "precedence"})

        fn_called = []

        async def should_not_be_called(eid, data):
            fn_called.append(eid)

        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
        results = await run_once(
            signal_backend,
            persistence,
            resume_fn=should_not_be_called,
            resumer=resumer,
        )

        assert "test/ch" in results
        assert len(fn_called) == 0

    @pytest.mark.asyncio
    async def test_legacy_resume_fn_still_works(self):
        """Bare resume_fn= without resumer= still works (backwards compat)."""
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()

        snapshot = MachineSnapshot(
            execution_id="legacy-001",
            machine_name="test",
            spec_version="2.1.0",
            current_state="wait",
            context={},
            step=1,
            event="waiting",
            waiting_channel="legacy/ch",
        )
        await CheckpointManager(persistence, "legacy-001").save_checkpoint(snapshot)
        await signal_backend.send("legacy/ch", {"ok": True})

        resumed = []

        async def legacy_fn(eid, data):
            resumed.append((eid, data))

        results = await run_once(
            signal_backend, persistence, resume_fn=legacy_fn,
        )

        assert "legacy/ch" in results
        assert len(resumed) == 1
        assert resumed[0][0] == "legacy-001"


# ---------------------------------------------------------------------------
# Cross-SDK portability: config_dict machines
# ---------------------------------------------------------------------------

class TestConfigDictResume:

    @pytest.mark.asyncio
    async def test_config_dict_with_store(self):
        """Machines created from config_dict also store their config hash."""
        import yaml
        signal_backend = MemorySignalBackend()
        persistence = MemoryBackend()
        config_store = MemoryConfigStore()

        config_dict = yaml.safe_load(_WAIT_CONFIG)

        m = FlatMachine(
            config_dict=config_dict,
            persistence=persistence,
            signal_backend=signal_backend,
            config_store=config_store,
        )
        await m.execute(input={})
        eid = m.execution_id

        snapshot = await CheckpointManager(persistence, eid).load_latest()
        assert snapshot.config_hash is not None

        # Can resume from config store
        await signal_backend.send("test/ch", {"v": "dict-resume"})
        resumer = ConfigStoreResumer(signal_backend, persistence, config_store)
        result = await resumer.resume(eid, {"v": "dict-resume"})
        assert result["val"] == "dict-resume"
