"""Unit tests for DeepSleepHooks — pure logic, no FlatMachine."""
from __future__ import annotations

import pytest
from _helpers import load_module

hooks_mod = load_module("hooks.py", "deepsleep_hooks")
DeepSleepHooks = hooks_mod.DeepSleepHooks


@pytest.fixture
def hooks():
    return DeepSleepHooks(max_depth=3, fail_rate=0.0, seed=42)


# Helper to call on_action and await if needed
async def call_action(hooks, action_name, context):
    result = hooks.on_action(action_name, context)
    if hasattr(result, "__await__"):
        return await result
    return result


# ── pick_batch (sync action, but dispatched via async on_action) ───

class TestPickBatch:

    @pytest.mark.asyncio
    async def test_selects_up_to_batch_size(self, hooks):
        candidates = [
            {"task_id": f"r/0.{i}", "root_id": "r", "depth": 1, "resource_class": "fast"}
            for i in range(10)
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 3,
            "max_active_roots": 2,
            "roots": {},
        })
        assert len(ctx["batch"]) == 3

    @pytest.mark.asyncio
    async def test_empty_candidates_sets_all_done(self, hooks):
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": [],
            "batch_size": 4,
            "max_active_roots": 2,
            "roots": {},
        })
        assert ctx["batch"] == []
        assert ctx["all_done"] is True

    @pytest.mark.asyncio
    async def test_respects_max_active_roots(self, hooks):
        candidates = [
            {"task_id": "a/0", "root_id": "a", "depth": 0, "resource_class": "fast"},
            {"task_id": "b/0", "root_id": "b", "depth": 0, "resource_class": "fast"},
            {"task_id": "c/0", "root_id": "c", "depth": 0, "resource_class": "fast"},
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 10,
            "max_active_roots": 2,
            "roots": {},
        })
        root_ids = {c["root_id"] for c in ctx["batch"]}
        assert len(root_ids) <= 2

    @pytest.mark.asyncio
    async def test_prefers_active_roots(self, hooks):
        candidates = [
            {"task_id": "a/0", "root_id": "a", "depth": 0, "resource_class": "fast"},
            {"task_id": "b/0", "root_id": "b", "depth": 0, "resource_class": "fast"},
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 1,
            "max_active_roots": 1,
            "roots": {"a": {"admitted": True, "completed": 0, "terminal_failures": 0}},
        })
        assert ctx["batch"][0]["root_id"] == "a"

    @pytest.mark.asyncio
    async def test_prefers_deeper_tasks(self, hooks):
        candidates = [
            {"task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast"},
            {"task_id": "r/0.0", "root_id": "r", "depth": 2, "resource_class": "fast"},
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 1,
            "max_active_roots": 1,
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
        })
        assert ctx["batch"][0]["task_id"] == "r/0.0"

    @pytest.mark.asyncio
    async def test_respects_resource_gate(self, hooks):
        """When slow gate is closed, only fast tasks are selectable."""
        candidates = [
            {"task_id": "r/0", "root_id": "r", "depth": 2, "resource_class": "slow"},
            {"task_id": "r/1", "root_id": "r", "depth": 0, "resource_class": "fast"},
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 2,
            "max_active_roots": 1,
            "roots": {"r": {"admitted": True}},
            "resources": {
                "fast": {"capacity": 4, "in_flight": 0, "gate_open": True},
                "slow": {"capacity": 2, "in_flight": 0, "gate_open": False},
            },
        })
        assert len(ctx["batch"]) == 1
        assert ctx["batch"][0]["resource_class"] == "fast"

    @pytest.mark.asyncio
    async def test_respects_resource_capacity(self, hooks):
        """When fast capacity is full, fast tasks are not selectable."""
        candidates = [
            {"task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast"},
            {"task_id": "r/1", "root_id": "r", "depth": 0, "resource_class": "slow"},
        ]
        ctx = await call_action(hooks, "pick_batch", {
            "_candidates": candidates,
            "batch_size": 2,
            "max_active_roots": 1,
            "roots": {"r": {"admitted": True}},
            "resources": {
                "fast": {"capacity": 4, "in_flight": 4, "gate_open": True},
                "slow": {"capacity": 2, "in_flight": 0, "gate_open": True},
            },
        })
        assert len(ctx["batch"]) == 1
        assert ctx["batch"][0]["resource_class"] == "slow"


class TestScoringParity:

    def test_score_boosts_slow_work(self, hooks):
        root = {"pending": 4, "has_pending_expensive": False}
        fast = {"depth": 2, "resource_class": "fast", "has_expensive_descendant": False}
        slow = {"depth": 2, "resource_class": "slow", "has_expensive_descendant": False}
        assert hooks._score(slow, root, is_active=True) > hooks._score(fast, root, is_active=True)

    def test_score_boosts_expensive_predecessor_hint(self, hooks):
        root = {"pending": 4, "has_pending_expensive": False}
        plain = {
            "depth": 1,
            "resource_class": "fast",
            "has_expensive_descendant": False,
            "distance_to_nearest_slow_descendant": 10_000,
        }
        drill = {
            "depth": 1,
            "resource_class": "fast",
            "has_expensive_descendant": True,
            "distance_to_nearest_slow_descendant": 1,
        }
        assert hooks._score(drill, root, is_active=True) > hooks._score(plain, root, is_active=True)

    def test_score_prefers_near_complete_roots(self, hooks):
        item = {"depth": 1, "resource_class": "fast", "has_expensive_descendant": False}
        near_done = {"pending": 1, "has_pending_expensive": False}
        very_pending = {"pending": 8, "has_pending_expensive": False}
        assert hooks._score(item, near_done, is_active=True) > hooks._score(item, very_pending, is_active=True)

    def test_score_boosts_pending_expensive_root(self, hooks):
        item = {"depth": 1, "resource_class": "fast", "has_expensive_descendant": False}
        with_expensive = {"pending": 4, "has_pending_expensive": True}
        without = {"pending": 4, "has_pending_expensive": False}
        assert hooks._score(item, with_expensive, is_active=True) > hooks._score(item, without, is_active=True)


# ── settle_results ─────────────────────────────────────────

class TestSettleResults:

    @pytest.mark.asyncio
    async def test_counts_completions(self, hooks):
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": [
                {"task_id": "r/0", "root_id": "r", "result": "ok", "children": [], "resource_class": "fast"},
                {"task_id": "r/1", "root_id": "r", "result": "ok", "children": [], "resource_class": "fast"},
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 2, "gate_open": True}},
        })
        assert ctx["roots"]["r"]["completed"] == 2

    @pytest.mark.asyncio
    async def test_collects_children(self, hooks):
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": [
                {
                    "task_id": "r/0", "root_id": "r", "result": "ok",
                    "resource_class": "fast",
                    "children": [
                        {"task_id": "r/0.0", "root_id": "r", "depth": 1, "resource_class": "fast"},
                    ],
                },
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 1, "gate_open": True}},
        })
        assert len(ctx["_new_children"]) == 1
        assert ctx["_new_children"][0]["task_id"] == "r/0.0"

    @pytest.mark.asyncio
    async def test_counts_terminal_errors(self, hooks):
        hooks.max_attempts = 3
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": [
                {"task_id": "r/0", "root_id": "r", "error": "boom",
                 "resource_class": "fast", "attempts": 3},
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 1, "gate_open": True}},
        })
        assert ctx["roots"]["r"]["terminal_failures"] == 1

    @pytest.mark.asyncio
    async def test_retry_does_not_count_terminal(self, hooks):
        hooks.max_attempts = 3
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": [
                {"task_id": "r/0", "root_id": "r", "error": "boom",
                 "resource_class": "fast", "attempts": 1},
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 1, "gate_open": True}},
        })
        assert ctx["roots"]["r"]["terminal_failures"] == 0

    @pytest.mark.asyncio
    async def test_handles_dict_results(self, hooks):
        """foreach with key returns dict, not list."""
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": {
                0: {"task_id": "r/0", "root_id": "r", "result": "ok",
                    "children": [], "resource_class": "fast"},
            },
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 1, "gate_open": True}},
        })
        assert ctx["roots"]["r"]["completed"] == 1

    @pytest.mark.asyncio
    async def test_releases_resource_slots(self, hooks):
        ctx = await call_action(hooks, "settle_results", {
            "batch_results": [
                {"task_id": "r/0", "root_id": "r", "result": "ok",
                 "children": [], "resource_class": "fast"},
                {"task_id": "r/1", "root_id": "r", "result": "ok",
                 "children": [], "resource_class": "slow"},
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0, "in_flight": 2}},
            "resources": {
                "fast": {"capacity": 4, "in_flight": 1, "gate_open": True},
                "slow": {"capacity": 2, "in_flight": 1, "gate_open": True},
            },
        })
        assert ctx["resources"]["fast"]["in_flight"] == 0
        assert ctx["resources"]["slow"]["in_flight"] == 0


# ── run_task ───────────────────────────────────────────────

class TestRunTask:

    @pytest.mark.asyncio
    async def test_produces_result(self, hooks):
        ctx = await call_action(hooks, "run_task", {
            "task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast",
        })
        assert ctx["result"] == "ok:r/0"

    @pytest.mark.asyncio
    async def test_leaf_at_max_depth(self, hooks):
        ctx = await call_action(hooks, "run_task", {
            "task_id": "r/0", "root_id": "r", "depth": 3, "resource_class": "fast",
        })
        assert ctx["children"] == []

    @pytest.mark.asyncio
    async def test_fail_rate(self):
        hooks = DeepSleepHooks(max_depth=3, fail_rate=1.0, seed=1)
        with pytest.raises(RuntimeError, match="transient failure"):
            await call_action(hooks, "run_task", {
                "task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast",
            })

    @pytest.mark.asyncio
    async def test_children_carry_metadata(self, hooks):
        ctx = await call_action(hooks, "run_task", {
            "task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast",
        })
        for child in ctx.get("children", []):
            assert "has_expensive_descendant" in child
            assert "distance_to_nearest_slow_descendant" in child
            assert "resource_class" in child


# ── Durable actions (with MemoryWorkBackend) ───────────────

class TestDurableActions:

    @pytest.fixture
    def durable_hooks(self):
        from flatmachines import MemoryWorkBackend, MemorySignalBackend
        wb = MemoryWorkBackend()
        sb = MemorySignalBackend()
        h = DeepSleepHooks(
            max_depth=3, fail_rate=0.0, seed=7, max_attempts=3,
            work_backend=wb, signal_backend=sb,
        )
        return h

    @pytest.mark.asyncio
    async def test_seed_work(self, durable_hooks):
        ctx = await call_action(durable_hooks, "seed_work", {
            "n_roots": 2,
            "max_depth": 3,
        })
        assert len(ctx["root_ids"]) == 2
        assert "root-000" in ctx["root_ids"]
        assert "root-001" in ctx["root_ids"]
        assert "resources" in ctx

    @pytest.mark.asyncio
    async def test_signal_ready(self, durable_hooks):
        ctx = await call_action(durable_hooks, "signal_ready", {
            "task_id": "r/0",
        })
        # Should have sent a signal
        signals = await durable_hooks.signal_backend.peek("dfss/ready")
        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_settle_results_pushes_children(self, durable_hooks):
        """settle_results should push children to the work pool."""
        pool = durable_hooks.work_backend.pool("tasks")
        # Push a parent first
        work_id = await pool.push(
            {"task_id": "r/0", "root_id": "r", "depth": 0, "resource_class": "fast"},
            options={"max_retries": 3},
        )
        # Claim it
        claimed = await pool.claim("scheduler")
        assert claimed is not None

        ctx = await call_action(durable_hooks, "settle_results", {
            "batch_results": [
                {
                    "task_id": "r/0", "root_id": "r", "result": "ok",
                    "resource_class": "fast",
                    "work_id": claimed.id,
                    "children": [
                        {"task_id": "r/0.0", "root_id": "r", "depth": 1, "resource_class": "fast"},
                    ],
                },
            ],
            "roots": {"r": {"admitted": True, "completed": 0, "terminal_failures": 0}},
            "resources": {"fast": {"capacity": 4, "in_flight": 1, "gate_open": True}},
        })
        # Child should be in pool
        child_item = await pool.claim("test")
        assert child_item is not None
        assert child_item.data["task_id"] == "r/0.0"
