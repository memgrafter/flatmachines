# FlatAgents + FlatMachines Reference

> **Target: <1000 tokens.** LLM-optimized. See `flatagent.d.ts`, `flatmachine.d.ts`, `profiles.d.ts` for schemas.
>
> **Versioning:** All specs and SDKs use lockstep versioning.

## Concepts

**FlatAgent**: Single LLM call. Model + prompts + output schema. No orchestration.
**FlatMachine**: State machine orchestrating agents. States, transitions, conditions, loops, error handling.

| Need | Use |
|------|-----|
| Single LLM call | FlatAgent |
| Multi-step/branching/retry/errors | FlatMachine |
| Parallel execution | `machine: [a, b, c]` |
| Dynamic parallelism | `foreach` |
| Background tasks | `launch` |

## Model Profiles

```yaml
# profiles.yml — agents reference by name
spec: flatprofiles
spec_version: "1.1.1"
data:
  model_profiles:
    fast: { provider: cerebras, name: zai-glm-4.6, temperature: 0.6 }
    smart: { provider: anthropic, name: claude-3-opus-20240229 }
  default: fast        # Fallback
  # override: smart    # Force all
```

Agent model field: `"fast"` | `{ profile: "fast", temperature: 0.9 }` | `{ provider: x, name: y }`
Resolution: default → profile → overrides → override

## Agent References

`data.agents` values may be:
- String path to a flatagent config
- Inline flatagent config (`spec: flatagent`)
- Typed adapter ref: `{ type: "flatagent" | "smolagents" | "pi-agent", ref?: "...", config?: {...} }`

## State Fields

| Field | Purpose |
|-------|---------|
| `type` | `initial` (entry) / `final` (exit+output) |
| `agent` | Agent to call |
| `machine` | Machine(s) — string or `[array]` for parallel |
| `foreach` | Array expr for dynamic parallelism (`as`: item var, `key`: result key) |
| `launch` / `launch_input` | Fire-and-forget machine(s) |
| `input` | Map input to agent/machine |
| `output_to_context` | Map `output.*` to `context.*` |
| `execution` | `{ type: retry, backoffs: [2,8,16], jitter: 0.1 }` |
| `on_error` | State name or `{ default: x, ErrorType: y }` |
| `transitions` | `[{ condition: "expr", to: state }, { to: default }]` |
| `mode` | `settled` (all) / `any` (first) for parallel |
| `wait_for` | Channel to wait for external signal (Jinja2 template) |
| `timeout` | Seconds (0=forever) |

## Patterns

**Execution types**: `default` | `retry` (backoffs, jitter) | `parallel` (n_samples) | `mdap_voting` (k_margin, max_candidates)

**Transitions**: `condition: "context.score >= 8"` with `to: state`. Last without condition = default.

**Loops**: Transition `to: same_state`. Machine has `max_steps` safety.

**Errors**: `on_error: state` or per-type. Context gets `last_error`, `last_error_type`.

**Parallel machines**:
```yaml
machine: [review_a, review_b]  # Results keyed by name
mode: settled  # or "any"
```

**Foreach**:
```yaml
foreach: "{{ context.items }}"
as: item
machine: processor
```

**Launch** (fire-and-forget):
```yaml
launch: background_task
launch_input: { data: "{{ context.data }}" }
```

**Wait for signal** (checkpoint, exit, resume on signal):
```yaml
wait_for_approval:
  wait_for: "approval/{{ context.task_id }}"
  timeout: 86400
  output_to_context:
    approved: "{{ output.approved }}"
  transitions:
    - condition: "context.approved"
      to: continue
    - to: rejected
```

## Distributed Worker Pattern

Use hook actions (e.g., `DistributedWorkerHooks`) with a `RegistrationBackend` + `WorkBackend` to build worker pools.

**Core machines**
- **Checker**: `get_pool_state` → `calculate_spawn` → `spawn_workers`
- **Worker**: `register_worker` → `claim_job` → process → `complete_job`/`fail_job` → `deregister_worker`
- **Reaper**: `list_stale_workers` → `reap_stale_workers`

`spawn_workers` expects `worker_config_path` in context (or override hooks to resolve it). Custom queues can compose the base hooks and add actions.

```yaml
context:
  worker_config_path: "./job_worker.yml"
states:
  check_state: { action: get_pool_state }
  calculate_spawn: { action: calculate_spawn }
  spawn_workers: { action: spawn_workers }
```

See `sdk/examples/distributed_worker/` for a full example.

## Signals & Triggers

Machine pauses at `wait_for` state → checkpoints with `waiting_channel` → process exits. Nothing running.

**Signal delivery**: External process writes signal → trigger fires → dispatcher resumes matching machines.

```
send("approval/task-001", {approved: true})
  → SQLite INSERT + touch trigger file
  → launchd/systemd starts dispatcher
  → dispatcher queries checkpoints WHERE waiting_channel = "approval/task-001"
  → resumes machine from checkpoint, signal data as output.*
```

**Channel semantics**:
- Addressed: `"approval/{{ context.task_id }}"` → one waiter
- Broadcast: `"quota/openai"` → N waiters (dispatcher controls limit)

**10,000 waiting machines** = 10,000 rows in SQLite. Zero processes, zero memory.

**Trigger backends**: `none` (polling), `file` (launchd/systemd — nothing running), `socket` (UDS, in-process).
DynamoDB Streams is implicit (no trigger code needed).

**Signal backends**: `memory` (testing), `sqlite` (local durable), `dynamodb` (AWS).

## Context Variables

`context.*` (all states), `input.*` (initial), `output.*` (in output_to_context), `item`/`as` (foreach)

## Hooks

`on_machine_start`, `on_machine_end`, `on_state_enter`, `on_state_exit`, `on_transition`, `on_error`, `on_action`

```python
class MyHooks(MachineHooks):
    def on_action(self, action: str, context: dict) -> dict:
        if action == "fetch": context["data"] = api_call()
        return context
```

## Persistence

```yaml
persistence: { enabled: true, backend: local }  # local | memory
```
Resume: `machine.execute(resume_from=execution_id)`

## SDKs

### Python SDKs
- **flatagents** (agents): `pip install flatagents[litellm]`
- **flatmachines** (orchestration): `pip install flatmachines[flatagents]`

### JavaScript SDK
A single JS SDK lives under [`sdk/js`](./sdk/js). It follows the same specs but is not yet split into separate FlatAgents/FlatMachines packages.
