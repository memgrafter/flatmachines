---
id: ftj-0edu
status: closed
deps: []
links: []
created: 2026-06-01T04:18:09Z
type: chore
priority: 2
assignee: memgrafter
---
# JS SDK: add prune to PersistenceBackend interface and all backends

The Python SDK has `prune()` on all 3 backends (LocalFile, Memory, SQLite) and the `PersistenceBackend` ABC. The JS SDK has no `prune` method at all — neither on the `PersistenceBackend` interface in `types.ts` nor on any of the 3 backends in `persistence.ts` (MemoryBackend, LocalFileBackend) and `persistence_sqlite.ts` (SQLiteCheckpointBackend).

**Work needed:**

1. Add `prune?(opts: { max_age_seconds?: number; max_count?: number }): Promise<number>;` to `PersistenceBackend` interface in `sdk/js/packages/flatmachines/src/types.ts`
2. Implement `prune` on `MemoryBackend` in `sdk/js/packages/flatmachines/src/persistence.ts` — follows Python MemoryBackend.prune logic: iterate execution IDs via latest pointer, extract created_at from snapshots, apply age/count selection, delete pruned executions
3. Implement `prune` on `LocalFileBackend` in `sdk/js/packages/flatmachines/src/persistence.ts` — iterate directories, read latest checkpoint timestamp
4. Implement `prune` on `SQLiteCheckpointBackend` in `sdk/js/packages/flatmachines/src/persistence_sqlite.ts` — query machine_checkpoints, group by execution_id, apply selection, delete from both tables
5. Extract shared selection helper (`_select_executions_to_prune` equivalent) as a pure function
6. Wire tests
