# SIGNAL_TRIGGER_ACTIVATION_BACKENDS

Status: Implemented  
Scope: FlatMachines local/non-distributed runtime foundations for OS-level signal wake and dispatch

## Problem

We want robust OS-level wake for `wait_for`/signal-driven machines using Unix sockets and OS service managers, without forcing an always-on Python bridge process.

Current design has good primitives (`SignalBackend`, `TriggerBackend`, `SignalDispatcher`) but an integration gap:
- producers can write signals without notifying triggers,
- dispatcher lifecycle is not standardized as a runtime entrypoint,
- responsibility boundaries between wake signaling and process activation are blurry.

## Goals

1. Keep backend boundaries clean and consistent with FlatMachines patterns.
2. Support low-latency local wake via Unix socket trigger (`SOCK_DGRAM`).
3. Support OS-managed activation equivalents on Linux/macOS.
4. Keep distributed/cloud runtimes unaffected (`NoOpTrigger` + infra-native triggers).
5. Avoid embedding process supervision logic inside trigger implementations.

## Non-goals

- No review-bridge/work-pool domain logic in core FlatMachines.
- No in-SDK replacement for systemd/launchd service management.
- No mandatory long-running listener requirement for all deployments.

## Existing primitives (kept)

- **Signal durability**: `SignalBackend` (`MemorySignalBackend`, `SQLiteSignalBackend`)
- **Wake hint transport**: `TriggerBackend` (`NoOpTrigger`, `FileTrigger`, `SocketTrigger`)
- **Resume engine**: `SignalDispatcher` (`dispatch`, `dispatch_all`, `listen`)

These abstractions are correct and should remain the core separation.

## Design principles

1. **Durability first**: trigger loss must not lose work; signals remain durable in `SignalBackend`.
2. **Trigger purity**: trigger backends emit wake hints only; they do not spawn/supervise processes.
3. **Activation is deployment concern**: process start/stop belongs to OS service manager integration.
4. **Composable runtime**: sender path and dispatcher path are explicit, testable, and swappable.

## Proposed architecture

### A) Keep `TriggerBackend` pure (no subprocess autostart in `SocketTrigger`)

`SocketTrigger` behavior remains:
- send datagram to UDS path,
- if listener absent, fail silently (debug log) because signal is durable.

Rationale:
- avoids hidden process-management side effects,
- avoids multi-process spawn storms,
- keeps behavior deterministic and backend-scoped.

### B) Add producer-side composite helper

Add a new `signals_helpers.py` module (separate from `signals.py` which defines protocols and implementations):

```python
# signals_helpers.py — composition helpers over signal/trigger backends

async def send_and_notify(
    signal_backend: SignalBackend,
    trigger_backend: TriggerBackend,
    channel: str,
    data: Any,
) -> str:
    signal_id = await signal_backend.send(channel, data)
    await trigger_backend.notify(channel)
    return signal_id
```

**Why a separate module**: `signals.py` defines the `SignalBackend` and `TriggerBackend` protocols alongside their implementations (`MemorySignalBackend`, `SQLiteSignalBackend`, `NoOpTrigger`, `FileTrigger`, `SocketTrigger`). Adding composition logic there mixes concerns — protocol definitions should not depend on how backends are combined. `signals_helpers.py` keeps protocols pure and composition explicit, following the same pattern as the rest of the codebase (e.g., `work.py` for storage, `distributed_hooks.py` for composition over it).

Purpose:
- eliminate footgun where callers send but forget notify,
- preserve explicit backend composition,
- keep `signals.py` focused on protocol + implementation boundaries.

### C) Add dispatcher runtime entrypoint

Add a first-class runner (module/CLI), e.g.:
- `python -m flatmachines.dispatch_signals --once ...`
- `python -m flatmachines.dispatch_signals --listen ...`

Responsibilities:
- initialize signal + persistence backends,
- initialize `SignalDispatcher`,
- execute one-shot drain or long-running listen loop,
- exit with clear status and logs.

This is the process target for systemd/launchd.

### D) Activation treatment (OS-level)

Activation is not a trigger backend. It is deployment wiring to start the dispatcher runtime entrypoint.

#### Linux
- Preferred low-latency mode: systemd `.socket` + `.service` for UDS datagram listener.
- Durable/idle mode: systemd `.path` + oneshot `.service` with `FileTrigger`.

#### macOS
- Practical equivalent: launchd `WatchPaths` + oneshot program using `FileTrigger`.
- UDS activation via launchd sockets is possible but can be deferred to later phase due API/packaging complexity.

## Runtime mode matrix

| Runtime | Signal backend | Trigger backend | Activation |
|---|---|---|---|
| Local dev (simple) | memory/sqlite | none/socket | manual process |
| Local durable idle | sqlite | file | launchd/systemd file watch |
| Local low-latency | sqlite | socket | systemd socket activation or long-running listener |
| Distributed/cloud | sqlite/dynamodb/etc | none | infra-native (streams/queues/lambda) |

## Configuration direction (backward compatible)

Keep existing backend config fields. Add optional dispatcher runtime config for runner tools/docs, not required for machine configs.

Example conceptual split:

```yaml
settings:
  backends:
    signals: { backend: sqlite, db_path: ./flatmachines.sqlite }
    trigger: { backend: socket, socket_path: /tmp/flatmachines/trigger.sock }
  runtime:
    dispatcher:
      mode: once   # once | listen
      activation: systemd_socket  # manual | systemd_socket | systemd_path | launchd_watchpaths
```

This section can be introduced incrementally; direct constructor injection remains valid.

## Failure semantics

- `send_and_notify` success criterion: signal persisted.
- `notify` best effort: failure to notify does not fail signal durability.
- dispatcher `--once` should process all pending channels it can and exit cleanly.
- orphan signal behavior stays unchanged (requeue/no waiter handling in dispatcher).

## Observability requirements

- Structured logs for: signal persisted, notify attempted, channel dispatched, resumes attempted/succeeded/failed.
- Dispatcher runtime should expose summary counts on exit in `--once` mode.
- No swallowed process-start failures inside trigger backend (because trigger does not spawn).

## Security considerations

- UDS path ownership/permissions must be OS-managed.
- Avoid shell-based process spawn paths in trigger backends.
- Service-manager units/plists define executable allowlist and environment.

## Migration plan

1. Add `signals_helpers.py` with `send_and_notify`; keep existing APIs in `signals.py` unchanged.
2. Add dispatcher runtime entrypoint (`--once`, `--listen`).
3. Publish Linux/macOS activation recipes.
4. Update examples to use composite send path.
5. (Optional) later: explicit activation adapter interface if we need programmatic install/validate tooling.

## Why this is the proper backend treatment

- Preserves `SignalBackend`/`TriggerBackend` separation already used across repo.
- Keeps non-distributed local runtime concerns local.
- Avoids mixing deployment orchestration into transport backends.
- Aligns with existing flatmachines pattern: durable state in backends, execution policy in runtime/invoker/OS.
