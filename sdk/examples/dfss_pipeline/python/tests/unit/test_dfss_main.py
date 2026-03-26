from __future__ import annotations

import pytest

from flatmachines import SQLiteWorkBackend

from _dfss_test_helpers import load_dfss_module



def _main_module():
    return load_dfss_module("main.py", "dfss_main")


@pytest.mark.asyncio
async def test_seed_creates_designed_and_random_roots(tmp_path):
    mod = _main_module()
    db_path = str(tmp_path / "dfss.sqlite")

    backend = SQLiteWorkBackend(db_path=db_path)
    pool = backend.pool("tasks")

    root_ids = await mod._seed_roots(
        pool,
        roots=4,
        max_depth=3,
        seed=7,
        max_attempts=3,
    )
    candidates = mod._load_pending_candidates(db_path)
    task_ids = {c["task_id"] for c in candidates}

    assert root_ids[:2] == ["root-000", "root-001"]
    assert "root-000/0" in task_ids
    assert "root-001/0" in task_ids
    assert "root-002/0" in task_ids
    assert "root-003/0" in task_ids


@pytest.mark.asyncio
async def test_rebuild_candidates_from_sqlite_pending_rows(tmp_path):
    mod = _main_module()
    db_path = str(tmp_path / "dfss.sqlite")

    backend = SQLiteWorkBackend(db_path=db_path)
    pool = backend.pool("tasks")
    await pool.push({"task_id": "root-010/0", "root_id": "root-010", "depth": 0, "resource_class": "fast"})
    await pool.push({"task_id": "root-011/0", "root_id": "root-011", "depth": 0, "resource_class": "slow"})

    pending = mod._load_pending_candidates(db_path)
    assert len(pending) == 2
    assert all("work_id" in p for p in pending)


@pytest.mark.asyncio
async def test_resume_releases_stale_claims(tmp_path):
    mod = _main_module()
    db_path = str(tmp_path / "dfss.sqlite")

    backend = SQLiteWorkBackend(db_path=db_path)
    pool = backend.pool("tasks")
    await pool.push({"task_id": "root-020/0", "root_id": "root-020", "depth": 0, "resource_class": "fast"})

    claimed = await pool.claim("scheduler")
    assert claimed is not None

    released = await pool.release_by_worker("scheduler")
    assert released == 1

    pending = mod._load_pending_candidates(db_path)
    assert len(pending) == 1
    assert pending[0]["task_id"] == "root-020/0"


@pytest.mark.asyncio
async def test_complete_removes_item_from_pool_and_candidates(tmp_path):
    mod = _main_module()
    db_path = str(tmp_path / "dfss.sqlite")

    backend = SQLiteWorkBackend(db_path=db_path)
    pool = backend.pool("tasks")
    work_id = await pool.push({"task_id": "root-030/0", "root_id": "root-030", "depth": 0, "resource_class": "fast"})

    pending = mod._load_pending_candidates(db_path)
    item = pending[0]

    claimed = mod._claim_selected_candidate(db_path, work_id=item["work_id"])
    assert claimed is not None
    await pool.complete(work_id)

    pending_after = mod._load_pending_candidates(db_path)
    assert pending_after == []
