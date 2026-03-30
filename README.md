# FlatMachines

Orchestrate agents with a peer network of state machines. Supports checkpoint/restore, persistence, and more. Batteries included.

BYO cli, or agent, or use flatagents with API.

Warning: this repo is a product of its times. Caveat emptor. Prefer the Python SDK for now, not yet JS or Rust. Use [./sdk/examples/](./sdk/examples/) to get started.

**For LLM/machine readers:** see [AGENTS.md](./AGENTS.md) for a compact reference.

## TL;DR

You write YAML that describes states, transitions, and agents. The runtime handles retries, parallelism, checkpointing, error recovery, and distributed workers. Your Python code stays small.

```bash
pip install flatmachines[flatagents] flatagents[litellm]
export OPENAI_API_KEY="sk-..."  # or CEREBRAS_API_KEY, etc.
```

```python
import asyncio
from flatmachines import FlatMachine

async def main():
    machine = FlatMachine(config_file="config/machine.yml")
    result = await machine.execute(input={"target": "Hello, World!"})
    print(result)

asyncio.run(main())
```

## What This Solves

Building multi-step LLM workflows in plain Python gets painful fast:

```python
# What starts as this...
result = await agent.call("Review this code")

# ...turns into this:
async def run_pipeline(input):
    for attempt in range(4):
        try:
            draft = await writer.call(topic=input["topic"])
            review = await critic.call(draft=draft)
            if review["score"] >= 8:
                return draft
            # else loop with feedback...
        except RateLimitError:
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            draft = await cleanup.call(error=str(e))
            # ...save checkpoint, handle partial state,
            # manage parallel branches, resume on crash...
```

You end up reimplementing retries, state tracking, error routing, checkpointing, and parallelism in every project. The orchestration logic drowns the business logic.

**FlatMachines replaces that with declarative config:**

```yaml
# Same pipeline, declarative
states:
  write:
    agent: writer
    execution: { type: retry, backoffs: [2, 8, 16] }
    output_to_context:
      draft: "{{ output.draft }}"
    transitions:
      - to: review

  review:
    agent: critic
    on_error: cleanup
    output_to_context:
      score: "{{ output.score }}"
    transitions:
      - condition: "context.score >= 8"
        to: done
      - to: write              # loop back with feedback

  cleanup:
    agent: cleanup_agent
    transitions:
      - to: failed
```

The runtime handles retries, error routing, and state. You change behavior by editing YAML, not refactoring Python.

## Minimal Example

A complete workflow in two files:

**agent.yml** — a single LLM call
```yaml
spec: flatagent
spec_version: "2.5.0"
data:
  name: reviewer
  model: "fast"
  system: "You are a senior code reviewer."
  user: |
    Review this code:
    {{ input.code }}
  output:
    issues:  { type: list, items: { type: str } }
    rating:  { type: str, enum: ["good", "needs_work", "critical"] }
```

**workflow.yml** — the state machine
```yaml
spec: flatmachine
spec_version: "2.5.0"
data:
  name: review-pipeline
  agents:
    reviewer: ./agent.yml
  states:
    start:
      type: initial
      agent: reviewer
      input: { code: "{{ input.code }}" }
      output_to_context:
        review: "{{ output }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        review: "{{ context.review }}"
```

Run it:
```python
from flatmachines import FlatMachine

machine = FlatMachine(config_file="workflow.yml")
result = await machine.execute(input={"code": "def add(a, b): return a + b"})
print(result["review"])
```

## Production Example: Writer-Critic Loop

A writer generates content, a critic scores it, and the loop continues until the score is high enough or max rounds are hit. All orchestration is in YAML — the Python is 4 lines:

```yaml
spec: flatmachine
spec_version: "2.5.0"
data:
  name: writer-critic-loop
  context:
    product: "{{ input.product }}"
    tagline: null
    feedback: null
    score: 0
    round: 0

  agents:
    writer: ./writer.yml
    critic: ./critic.yml

  states:
    start:
      type: initial
      transitions:
        - to: write

    write:
      agent: writer
      execution: { type: retry, backoffs: [2, 8, 16, 35], jitter: 0.1 }
      input:
        product: "{{ context.product }}"
        tagline: "{{ context.tagline }}"
        feedback: "{{ context.feedback }}"
      output_to_context:
        tagline: "{{ output.tagline }}"
      transitions:
        - to: review

    review:
      agent: critic
      execution: { type: retry, backoffs: [2, 8, 16, 35], jitter: 0.1 }
      input:
        product: "{{ context.product }}"
        tagline: "{{ context.tagline }}"
      output_to_context:
        score: "{{ output.score }}"
        feedback: "{{ output.feedback }}"
        round: "{{ (context.round | int) + 1 }}"
      transitions:
        - condition: "context.score >= 8"
          to: done
        - condition: "context.round >= 4"
          to: done
        - to: write                    # loop with feedback

    done:
      type: final
      output:
        tagline: "{{ context.tagline }}"
        score: "{{ context.score }}"
        rounds: "{{ context.round }}"
```

```python
machine = FlatMachine(config_file="writer_critic.yml")
result = await machine.execute(input={"product": "a CLI tool for AI agents"})
print(f'"{result["tagline"]}" — scored {result["score"]}/10 in {result["rounds"]} rounds')
```

## Key Features

### Parallel Execution

Run multiple machines simultaneously, or fan out over dynamic data:

```yaml
# Static: run three review machines in parallel
parallel_review:
  machine: [technical_review, legal_review, financial_review]
  mode: settled          # wait for all (or "any" for first)
  output_to_context:
    reviews: "{{ output }}"

# Dynamic: process each item in a list
process_all:
  foreach: "{{ context.documents }}"
  as: doc
  machine: doc_processor
  output_to_context:
    results: "{{ output }}"

# Fire-and-forget: launch background work without waiting
notify:
  launch: notification_machine
  launch_input: { message: "{{ context.message }}" }
```

### Error Recovery

Route errors to specific states. Context gets `last_error` and `last_error_type` automatically:

```yaml
do_work:
  agent: worker
  on_error: handle_error          # route to error handler
  transitions:
    - to: done

handle_error:
  agent: cleanup
  input:
    error: "{{ context.last_error }}"
    error_type: "{{ context.last_error_type }}"
  transitions:
    - to: retry_or_fail
```

Per-error-type routing:
```yaml
on_error:
  default: generic_handler
  RateLimitError: wait_and_retry
  ValidationError: fix_input
```

### Checkpoint & Resume

Crash mid-workflow? Resume from the last checkpoint:

```yaml
persistence:
  enabled: true
  backend: sqlite                   # local | memory | sqlite
  db_path: ./my_workflows.sqlite
```

```python
# Resume a crashed execution
result = await machine.execute(resume_from="exec_abc123")
```

### Signals & Wait-For (Human-in-the-Loop)

Pause a machine, shut down the process, and resume when an external signal arrives. 10,000 waiting machines = 10,000 rows in SQLite. Zero processes, zero memory.

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

Signal delivery (from any process):
```python
send("approval/task-001", {"approved": True})
# → SQLite write → trigger fires → dispatcher resumes the machine
```

### Distributed Workers

Built-in worker pool orchestration with `DistributedWorkerHooks`, `RegistrationBackend`, and `WorkBackend`:

```
Checker:  get_pool_state → calculate_spawn → spawn_workers
Worker:   register → claim_job → process → complete/fail → deregister
Reaper:   list_stale_workers → reap_stale_workers
```

All defined in YAML — the checker, worker, and reaper are each FlatMachines:

```yaml
# job_worker.yml
spec: flatmachine
spec_version: "2.5.0"
data:
  name: job_worker
  hooks: "distributed-worker"
  machines:
    processor: ./processor.yml
  states:
    start:
      type: initial
      transitions: [{ to: register_worker }]
    register_worker:
      action: register_worker
      transitions: [{ to: claim_job }]
    claim_job:
      action: claim_job
      output_to_context:
        job: output.job
      transitions:
        - condition: "context.job == None"
          to: no_work
        - to: process_job
    process_job:
      machine: processor
      input: { job: context.job }
      on_error: job_failed
      transitions: [{ to: complete_job }]
    complete_job:
      action: complete_job
      transitions: [{ to: deregister }]
    job_failed:
      action: fail_job
      transitions: [{ to: deregister }]
    deregister:
      action: deregister_worker
      transitions: [{ to: done }]
    done:
      type: final
      output: { result: "{{ context.result }}" }
```

See [distributed_worker example](./sdk/examples/distributed_worker) for a runnable demo.

### Hooks

Extend behavior with Python hooks — the escape hatch for anything the YAML can't express:

```python
from flatmachines import FlatMachine, MachineHooks

class MyHooks(MachineHooks):
    def on_action(self, action: str, context: dict) -> dict:
        if action == "fetch_data":
            context["data"] = fetch_from_api()
        return context

    def on_error(self, state: str, error: Exception, context: dict) -> dict:
        alert_ops_team(state, error)
        return context

machine = FlatMachine(config_file="workflow.yml", hooks=MyHooks())
```

Available hooks: `on_machine_start`, `on_machine_end`, `on_state_enter`, `on_state_exit`, `on_transition`, `on_error`, `on_action`

Built-ins: `LoggingHooks`, `MetricsHooks`, `WebhookHooks`, `CompositeHooks`

## Agent Framework Agnostic

FlatMachines uses adapters to execute agents. It works with FlatAgents configs, smolagents, pi-agent, or custom adapters:

```yaml
agents:
  # FlatAgent config file
  reviewer: ./reviewer.yml

  # smolagents adapter
  researcher:
    type: smolagents
    ref: "my_agents:create_researcher"

  # pi-agent adapter
  coder:
    type: pi-agent
    config: { model: "claude-sonnet-4-20250514" }
```

Register custom adapters via `AgentAdapterRegistry`.

## Model Profiles

Centralize model config in one file. Agents reference profiles by name:

```yaml
# profiles.yml
spec: flatprofiles
spec_version: "2.5.0"
data:
  model_profiles:
    fast:
      provider: cerebras
      name: zai-glm-4.6
      temperature: 0.6
    smart:
      provider: anthropic
      name: claude-3-opus-20240229
      temperature: 0.3
  default: fast
```

```yaml
# In any agent.yml
model: "fast"                        # profile lookup
model: { profile: "fast", temperature: 0.9 }  # profile + override
```

## Execution Strategies

```yaml
execution:
  type: retry
  backoffs: [2, 8, 16, 35]
  jitter: 0.1
```

| Type | Purpose |
|------|---------|
| `default` | Single call |
| `retry` | Backoff on rate limits / transient errors |
| `parallel` | Run N samples, pick best (`n_samples`) |
| `mdap_voting` | Consensus voting (`k_margin`, `max_candidates`) |

## Quick Start

For a coding agent (tool calling repl) example, see [Coding Machine CLI](./sdk/examples/coding_machine_cli).

The fastest path is to run the [helloworld example](./sdk/examples/helloworld):


```bash
# 1. Set an API key
export OPENAI_API_KEY="sk-..."   # or CEREBRAS_API_KEY

# 2. Run the example (sets up venv, installs deps, runs)
cd sdk/examples/helloworld/python
./run.sh
```

To start from scratch in your own project:

```bash
pip install flatmachines[flatagents] flatagents[litellm]
```

You need three config files — a **profiles.yml** (model config), an **agent.yml** (LLM call), and a **machine.yml** (state machine):

**config/profiles.yml**
```yaml
spec: flatprofiles
spec_version: "2.5.0"
data:
  model_profiles:
    fast:
      provider: openai
      name: gpt-5-mini
      max_tokens: 2048
  default: fast
```

**config/agent.yml**
```yaml
spec: flatagent
spec_version: "2.5.0"
data:
  name: greeter
  model: "fast"
  system: "You are a friendly assistant. Reply concisely in plain text."
  user: |
    Say hello to {{ input.name }} and tell them something interesting.
```

**config/machine.yml**
```yaml
spec: flatmachine
spec_version: "2.5.0"
data:
  name: hello-machine
  context:
    name: "{{ input.name }}"
  agents:
    greeter: ./agent.yml
  states:
    start:
      type: initial
      agent: greeter
      execution: { type: retry, backoffs: [2, 8, 16] }
      input:
        name: "{{ input.name }}"
      output_to_context:
        response: "{{ output.content }}"
      transitions:
        - to: done
    done:
      type: final
      output:
        response: "{{ context.response }}"
```

**run.py**
```python
import asyncio
from flatmachines import FlatMachine, setup_logging

setup_logging(level="INFO")

async def main():
    machine = FlatMachine(config_file="config/machine.yml")
    result = await machine.execute(input={"name": "World"})
    print(result["response"])

asyncio.run(main())
```

```bash
python run.py
```

## Versioning

All specs (`flatagent.d.ts`, `flatmachine.d.ts`, `profiles.d.ts`) and SDKs use **lockstep versioning**. A single version number applies across the entire repository.

## Examples

Runnable examples in [`./sdk/examples`](./sdk/examples):

| Example | What it demonstrates |
|---------|---------------------|
| [helloworld](./sdk/examples/helloworld) | Minimal loop — build a string char by char |
| [writer_critic](./sdk/examples/writer_critic) | Feedback loop between two agents |
| [parallelism](./sdk/examples/parallelism) | Parallel machines, foreach, fire-and-forget |
| [error_handling](./sdk/examples/error_handling) | Error routing and recovery |
| [human-in-the-loop](./sdk/examples/human-in-the-loop) | Pause for human approval |
| [distributed_worker](./sdk/examples/distributed_worker) | Worker pools with job queues |
| [coding_agent_cli](./sdk/examples/coding_agent_cli) | CLI coding assistant |
| [research_paper_analysis](./sdk/examples/research_paper_analysis) | Multi-step paper analysis |
| [multi_paper_synthesizer](./sdk/examples/multi_paper_synthesizer) | Cross-paper synthesis |
| [character_card](./sdk/examples/character_card) | Character card generation |
| [support_triage_json](./sdk/examples/support_triage_json) | Support ticket triage |
| [story_writer](./sdk/examples/story_writer) | Story generation pipeline |
| [dfss_deepsleep](./sdk/examples/dfss_deepsleep) | Deep-sleep scheduling |
| [dfss_pipeline](./sdk/examples/dfss_pipeline) | DFSS pipeline pattern |
| [dynamic_agent](./sdk/examples/dynamic_agent) | Runtime agent construction |
| [gepa_self_optimizer](./sdk/examples/gepa_self_optimizer) | Self-optimizing agent |
| [listener_os](./sdk/examples/listener_os) | OS-level signal triggers |
| [mdap](./sdk/examples/mdap) | Multi-draft aggregation voting |
| [peering](./sdk/examples/peering) | Cross-machine peering |
| [rlm](./sdk/examples/rlm) | Reinforcement learning loop |

## Specs

TypeScript definitions are the source of truth:
- [`flatagent.d.ts`](./flatagent.d.ts) — agent config schema
- [`flatmachine.d.ts`](./flatmachine.d.ts) — machine config schema
- [`profiles.d.ts`](./profiles.d.ts) — model profile schema

## SDKs

| SDK | Install | Status |
|-----|---------|--------|
| Python (agents) | `pip install flatagents[litellm]` | Stable |
| Python (machines) | `pip install flatmachines[flatagents]` | Stable |
| JavaScript | [`sdk/js`](./sdk/js) | In progress |

## Logging & Metrics

```python
from flatmachines import setup_logging
setup_logging(level="INFO")
```

| Env var | Default | Purpose |
|---------|---------|---------|
| `FLATAGENTS_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `FLATAGENTS_LOG_FORMAT` | `standard` | `standard` / `json` / `simple` |
| `FLATAGENTS_METRICS_ENABLED` | `true` | OpenTelemetry metrics |
| `OTEL_METRICS_EXPORTER` | `console` | `console` or `otlp` for production |

## Planned

- Distributed execution backends (Redis/Postgres) + cross-network peering
- TypeScript SDK (in progress)
- `max_depth` to limit machine launch nesting
- Checkpoint pruning
- Input size validation (warn on prompt > context window)
