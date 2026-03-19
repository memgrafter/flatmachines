# FlatMachines (Python SDK) Reference

> **Target: ~1000 tokens.** LLM‑optimized. See `flatmachine.d.ts` + `flatagent.d.ts` for schemas.
>
> **Scope:** This file documents the **Python FlatMachines runtime** (orchestration). It is agent‑framework‑agnostic and uses adapters to execute agents.

## Concepts

**FlatAgent**: Single LLM call (flatagents or other frameworks).
**FlatMachine**: State machine orchestrating agents, actions, and peer machines.

| Need | Use |
|------|-----|
| Single LLM call | FlatAgent |
| Multi-step/branching/retry/errors | FlatMachine |
| Parallel execution | `machine: [a, b, c]` |
| Dynamic parallelism | `foreach` |
| Background tasks | `launch` |

## Machine Config (Envelope)

```yaml
spec: flatmachine
spec_version: "0.10.0"

data:
  name: writer-critic-loop
  expression_engine: simple    # simple | cel
  context: { ... }             # initial context (templated)
  agents: { ... }              # agent references
  machines: { ... }            # peer machine refs
  states: { ... }              # state definitions
  settings: { ... }            # adapter/runtime settings
  persistence: { enabled: true, backend: local | memory }
  hooks: { file/module, class, args }

metadata: { ... }
```

### Agent References (Adapter‑agnostic)

`data.agents` values can be:
- String path to a flatagent config (default adapter `flatagent`).
- Inline flatagent config (`spec: flatagent`).
- Typed adapter ref: `{ type: "flatagent" | "smolagents" | "pi-agent", ref?: "...", config?: {...} }`.

Examples:
```yaml
agents:
  reviewer: ./reviewer.yml
  smol: { type: smolagents, ref: ./smol_factory.py#build_agent }
  pi: { type: pi-agent, ref: "@pi-mono/agent#review" }
```

**Adapter registry:** FlatMachines uses `AgentAdapterRegistry` to build `AgentExecutor`s. Built‑in adapters are registered automatically if their deps are installed:
- **flatagent** (requires `flatagents`)
- **smolagents** (requires `smolagents`)
- **pi-agent** (Node bridge; uses `pi_agent_runner.mjs`)

Custom adapters can be registered via `agent_registry=` or `agent_adapters=[...]`.

### Settings (adapter/runtime)

`data.settings` is passed to adapters via `AgentAdapterContext`. The pi‑agent bridge reads:
```yaml
settings:
  agent_runners:
    pi_agent:
      runner: ./path/to/pi_agent_runner.mjs
      node: node
      timeout: 30
      cwd: .
      env: { PI_API_KEY: "..." }
```

## State Execution Order (Python runtime)

For each state, the runtime executes in this order:
1. **action** → calls hooks `on_action` (default `HookAction`).
2. **launch** → fire‑and‑forget machine(s) (outbox pattern + invoker).
3. **machine / foreach** → peer machine invocation (blocking).
4. **agent** → execute agent via adapter + execution strategy.
5. **final output** → render `output` if `type: final`.

### Template Variables

Jinja2 renders `input`, `context`, and `output` as dicts. Special behavior:
- If a template string has no Jinja2 syntax and looks like `context.foo`, it returns the **actual value** (not a string).
- The Jinja2 environment auto‑serializes lists/dicts to JSON and includes a `fromjson` filter.

Use in `input`/`output_to_context`/`context`:
```yaml
input:
  prompt: "{{ context.topic }}"
  raw_context: "context"      # literal string
  parsed: "{{ context.json | fromjson }}"
```

## Transitions & Expressions

`transitions` are evaluated in order; the last transition without a condition is default.

Expression engines:
- **simple** (default): basic comparisons/boolean logic.
- **cel**: CEL support via `flatmachines[cel]`.

`on_error` supports:
```yaml
on_error: retry_state
# or
on_error:
  RateLimitError: retry_state
  default: error_state
```

When errors occur, the runtime sets `context.last_error` and `context.last_error_type`.

## Execution Types (Agent Calls)

Execution types operate over an `AgentExecutor` and return `AgentResult`:
- `default` – single call
- `retry` – backoff + jitter
- `parallel` – N samples
- `mdap_voting` – consensus across samples

```yaml
execution:
  type: retry
  backoffs: [2, 8, 16]
  jitter: 0.1
```

Usage/cost metrics from `AgentResult` are accumulated into `FlatMachine.total_api_calls` and `total_cost`.

## Peer Machines, Parallelism, Foreach

- `machine: child` → invoke peer machine and block.
- `machine: [a, b, c]` → parallel invoke; `mode: settled | any`.
- `foreach: "{{ context.items }}"` → dynamic parallelism.
- `launch: child` → fire‑and‑forget launch; result written to backend.

For `mode: any`, the first completed result is returned; remaining tasks continue in background.

## Invokers & Result Backends

The runtime delegates machine launches to a **MachineInvoker**:
- **InlineInvoker** (default): same process; launches background tasks.
- **QueueInvoker**: abstract base for external queue dispatch.
- **SubprocessInvoker**: spawns `python -m flatmachines.run` subprocesses.

Results are written/read via a **ResultBackend** using URIs:
`flatagents://{execution_id}/result`. The default backend is in‑memory.

## Persistence & Resume

Persistence is enabled by default and uses a `MemoryBackend` unless configured.

```yaml
persistence:
  enabled: true
  backend: local   # local | memory
  checkpoint_on: [machine_start, state_enter, execute, state_exit, machine_end]
```

Checkpoints store `MachineSnapshot` (context, state, output, costs, pending launches). Resume with:
```python
await machine.execute(resume_from=execution_id)
```

## Hooks

Configure hooks in `data.hooks`:
- **file**: local file path (stateful OK)
- **module**: installed module (stateless required)

```yaml
hooks:
  file: ./hooks.py
  class: MyHooks
  args: { ... }
```

Built‑ins: `LoggingHooks`, `MetricsHooks`, `WebhookHooks`, `CompositeHooks`.

## CLI Runner

```bash
python -m flatmachines.run --config machine.yml --input '{"key": "value"}'
```

This is used by `SubprocessInvoker` for isolated execution.

## Signals & Dispatch

Machine pauses at `wait_for` → checkpoints → process exits. Signal resumes it.

**Send signals** (use `send_and_notify` to avoid forgetting the trigger):
```python
from flatmachines import send_and_notify
await send_and_notify(signal_backend, trigger_backend, "approval/task-001", {"approved": True})
```

**Dispatch** (process pending signals, resume waiting machines):
```bash
python -m flatmachines.dispatch_signals --once --resumer config-store
python -m flatmachines.dispatch_signals --listen --resumer config-store --socket-path /tmp/flatmachines/trigger.sock
# diagnostics only (no-op resume):
python -m flatmachines.dispatch_signals --once --allow-noop-resume
```

**Backends**: `SignalBackend` (memory, sqlite) × `TriggerBackend` (none, file, socket).

**OS activation** (zero processes while idle):
- **macOS**: launchd `WatchPaths` + `FileTrigger` + `--once`
- **Linux**: systemd `.path` + `FileTrigger` + `--once`, or `.socket` + `--listen`
- **Cloud**: `NoOpTrigger` — infra‑native activation (Streams/Lambda/queues)

## Distributed Worker Pattern

`DistributedWorkerHooks` + `RegistrationBackend` + `WorkBackend` (SQLite or in‑memory) power **checker/worker/reaper** topologies.

## Compatibility

Agent‑framework‑agnostic. Install `flatmachines[flatagents]` for FlatAgent configs. Schemas lockstep with repo versions.
