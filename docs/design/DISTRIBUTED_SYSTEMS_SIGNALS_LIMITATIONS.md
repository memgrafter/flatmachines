# Distributed Systems Signal Limitations

Status: Known limitations
Scope: Signal dispatch across heterogeneous backend configurations

## 1. Firestore `list_execution_ids` missing `waiting_channel` support

### Problem

The `SignalDispatcher` queries for machines waiting on a channel:

```python
execution_ids = await self.persistence_backend.list_execution_ids(
    waiting_channel=channel
)
```

The `PersistenceBackend` protocol in `persistence.py` defines `waiting_channel` as a required keyword argument. The `MemoryBackend`, `LocalFileBackend`, and `SQLiteCheckpointBackend` all implement it. The Firestore backend (`gcp/firestore.py`) does not:

```python
# Current Firestore signature — missing waiting_channel
async def list_execution_ids(self, *, event: str = None) -> list[str]:
```

This means the dispatcher **cannot find waiting machines when Firestore is the persistence backend**. In a heterogeneous deployment (e.g., Firestore persistence + SQLite signals), `dispatch()` will query Firestore, get no results, re-queue the signal, and the waiting machine is never resumed.

### Fix

Add `waiting_channel: Optional[str] = None` to `FirestoreBackend.list_execution_ids` and filter on the stored checkpoint's `waiting_channel` field. This brings Firestore into conformance with the protocol that the other three backends already satisfy.

### Priority

Must fix before any deployment uses Firestore persistence with `wait_for` states.

---

## 2. `SignalDispatcher` assumes a single persistence backend

### Problem

The dispatcher takes exactly one persistence backend:

```python
class SignalDispatcher:
    def __init__(self, signal_backend, persistence_backend, resume_fn):
```

It finds waiters by querying `persistence_backend.list_execution_ids(waiting_channel=channel)`. This works when all machines in a system use the same persistence backend. It breaks when machines in a heterogeneous cluster checkpoint to different backends — for example:

- Machine A checkpoints to Firestore (GCP)
- Machine B checkpoints to DynamoDB (AWS)
- Machine C checkpoints to SQLite (local edge node)
- A shared signal backend receives a broadcast signal on `"quota/openai"`

The dispatcher can only query one persistence backend, so it will only find waiters in that one backend. Machines checkpointed elsewhere are invisible.

### Current scope

This is **not a problem for the local OS backend work** described in `SIGNAL_TRIGGER_ACTIVATION_BACKENDS.md`. Local deployments use a single persistence backend (SQLite or memory). The limitation only surfaces in multi-provider distributed deployments.

### Possible future approaches

1. **Signal backend as waiter index.** When a machine enters a `wait_for` state, register the `(channel, execution_id, persistence_backend_id)` tuple in the signal backend itself. The dispatcher queries the signal backend for waiters instead of the persistence backend. This inverts the lookup — the signal backend becomes the coordination point rather than the persistence backend.

2. **Federated persistence query.** The dispatcher accepts a list of persistence backends and queries all of them. Simple but O(N) in backend count per dispatch, and requires the dispatcher to know about all backends upfront.

3. **Per-backend dispatchers.** Each persistence backend gets its own dispatcher instance. Signal backends that support fan-out (e.g., DynamoDB Streams, SNS) deliver to all dispatchers. Each dispatcher only resumes machines in its own persistence backend. This aligns with the existing design principle that activation is a deployment concern.

### Recommendation

Approach 3 (per-backend dispatchers) is most consistent with the current architecture — it keeps backends isolated, avoids coupling the signal backend to persistence topology, and maps naturally to infrastructure-native fan-out. Document this as the intended pattern for heterogeneous deployments when the need arises.

### Priority

No immediate action required. The local OS backend implementation does not make this worse. Track as a design constraint for future multi-provider support.
