# FlatMachines (Python SDK)

State-machine orchestration for LLM agents. FlatMachines is **agent-framework agnostic** and uses adapters to execute agents from FlatAgents, smolagents, pi-mono, or other runtimes.

**For LLM/machine readers:** see [MACHINES.md](https://github.com/memgrafter/flatagents/blob/main/MACHINES.md).

## Install

```bash
pip install flatmachines[flatagents]
```

Optional extras:
- `flatmachines[cel]` – CEL expression engine
- `flatmachines[validation]` – JSON schema validation
- `flatmachines[metrics]` – OpenTelemetry metrics
- `flatmachines[smolagents]` – smolagents adapter

## Quick Start

```python
from flatmachines import FlatMachine

machine = FlatMachine(config_file="workflow.yml")
result = await machine.execute(input={"query": "..."})
print(result)
```

**workflow.yml**
```yaml
spec: flatmachine
spec_version: "0.10.0"

data:
  name: reviewer
  agents:
    reviewer: ./reviewer.yml
  states:
    start:
      type: initial
      agent: reviewer
      input:
        code: "{{ input.code }}"
      output_to_context:
        review: "{{ output }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        review: "{{ context.review }}"
```

## Agent Adapters

FlatMachines delegates agent execution to adapters. Built-ins are registered automatically if their dependencies are installed:
- **flatagent** – uses FlatAgents configs (`flatmachines[flatagents]`)
- **smolagents** – executes `MultiStepAgent` via `agent_ref.ref` factories
- **pi-agent** – Node bridge to pi-mono using `pi_agent_runner.mjs`

Agent refs in `data.agents` can be:
- string path to a flatagent config
- inline flatagent config (`spec: flatagent`)
- typed adapter ref: `{ type: "smolagents" | "pi-agent" | "flatagent", ref?: "...", config?: {...} }`

Custom adapters can be registered via `AgentAdapterRegistry`.

## State Execution Order

For each state, the Python runtime executes in this order:
1. `action` → `hooks.on_action`
2. `launch` → fire-and-forget machine(s)
3. `machine` / `foreach` → peer machines (blocking)
4. `agent` → adapter + execution strategy
5. `output` → render final output for `type: final`

Jinja2 templates render `input`, `context`, and `output`. A plain string like `context.foo` resolves to the actual value (not a string).

## Execution Types

```yaml
execution:
  type: retry
  backoffs: [2, 8, 16]
  jitter: 0.1
```

Supported: `default`, `retry`, `parallel`, `mdap_voting`.

## Parallelism & Launching

- `machine: child` → invoke peer machine (blocking)
- `machine: [a, b]` → parallel
- `foreach: "{{ context.items }}"` → dynamic parallelism
- `launch: child` → fire-and-forget; result is written to backend

## Persistence & Resume

```yaml
persistence:
  enabled: true
  backend: local  # local | memory | sqlite
  checkpoint_on: [machine_start, state_enter, execute, state_exit, machine_end]
```

### SQLite backend (recommended for durable single-file persistence)

```yaml
persistence:
  enabled: true
  backend: sqlite
  db_path: ./flatmachines.sqlite   # optional, defaults to flatmachines.sqlite
```

When `backend: sqlite` is declared, the SDK automatically selects:
- `SQLiteCheckpointBackend` for checkpoint storage
- `SQLiteLeaseLock` for concurrency control
- `SQLiteConfigStore` for content-addressed config storage (auto-wired when no explicit `config_store` is passed)

No imperative runner injection required — everything is driven from config.

`db_path` resolution order: config field → `FLATMACHINES_DB_PATH` env var → `flatmachines.sqlite`.

Resume with `machine.execute(resume_from=execution_id)`. Checkpoints store `MachineSnapshot` including pending launches.

## Hooks

Configure hooks via `data.hooks`:
```yaml
hooks:
  file: ./hooks.py
  class: MyHooks
  args: { ... }
```

Built-ins: `LoggingHooks`, `MetricsHooks`, `WebhookHooks`, `CompositeHooks`.

## Invokers & Result Backends

Invokers define how peer machines are launched:
- `InlineInvoker` (default)
- `QueueInvoker` (base class for external queues)
- `SubprocessInvoker` (`python -m flatmachines.run`)

Results are written/read via `ResultBackend` URIs: `flatagents://{execution_id}/result`.

## Logging & Metrics

```python
from flatmachines import setup_logging, get_logger
setup_logging(level="INFO")
logger = get_logger(__name__)
```

Env vars match FlatAgents: `FLATAGENTS_LOG_LEVEL`, `FLATAGENTS_LOG_FORMAT`, `FLATAGENTS_LOG_DIR`.

Metrics require `flatmachines[metrics]` and `FLATAGENTS_METRICS_ENABLED=true`.

## CLI Runner

```bash
python -m flatmachines.run --config machine.yml --input '{"key": "value"}'
```

## Examples (Repo)

- [character_card](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/character_card/python)
- [coding_agent_cli](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/coding_agent_cli/python)
- [custom_coding_workflow](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/custom_coding_workflow/python)
- [dfss_deepsleep](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/dfss_deepsleep/python)
- [distributed_worker](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/distributed_worker/python)
- [dynamic_agent](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/dynamic_agent/python)
- [error_handling](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/error_handling/python)
- [gepa_self_optimizer](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/gepa_self_optimizer/python)
- [helloworld](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/helloworld/python)
- [human-in-the-loop](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/human-in-the-loop/python)
- [mdap](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/mdap/python)
- [multi_paper_synthesizer](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/multi_paper_synthesizer/python)
- [parallelism](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/parallelism/python)
- [peering](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/peering/python)
- [research_paper_analysis](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/research_paper_analysis/python)
- [rlm](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/rlm/python)
- [story_writer](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/story_writer/python)
- [support_triage_json](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/support_triage_json/python)
- [writer_critic](https://github.com/memgrafter/flatagents/tree/main/sdk/examples/writer_critic/python)

## Specs

Source of truth:
- [`flatmachine.d.ts`](https://github.com/memgrafter/flatagents/blob/main/sdk/python/flatmachines/flatmachines/assets/flatmachine.d.ts)
- [`flatagent.d.ts`](https://github.com/memgrafter/flatagents/blob/main/sdk/python/flatmachines/flatmachines/assets/flatagent.d.ts)
- [`profiles.d.ts`](https://github.com/memgrafter/flatagents/blob/main/sdk/python/flatmachines/flatmachines/assets/profiles.d.ts)
