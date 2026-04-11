# FlatMachines

Orchestrate agents with a peer network of state machines. Supports checkpoint/restore, persistence, and more. Batteries included.

BYO cli, or agent, or use flatagents with API.

Warning: this repo is a product of its times. Caveat emptor. Prefer the Python SDK for now, not yet JS or Rust. Use [./sdk/examples/](./sdk/examples/) to get started.

**For LLM/machine readers:** see [AGENTS.md](./AGENTS.md) for a compact reference.

## TL;DR

You write YAML that describes states, transitions, and agents. The runtime handles retries, parallelism, checkpointing, error recovery, and distributed workers. Your Python code stays small.

The runtime handles retries, error routing, and state. You change behavior by editing YAML, not refactoring Python.

## Quick Start

For a coding agent (tool calling repl) example, see [Coding Machine CLI](./sdk/examples/coding_machine_cli).

The fastest path is to run the [helloworld example](./sdk/examples/helloworld):


```bash
# 1. Set an API key e.g.
export OPENAI_API_KEY="sk-..."

# 2. Run the example (sets up venv, installs deps, runs)
cd sdk/examples/helloworld/python
./run.sh
```

To start from scratch in your own project:

```bash
pip install flatmachines[flatagents] flatagents[litellm]
```

We will use 3 config files for this demo: **profiles.yml** (model catalog), **agent.yml** (single LLM call), and **machine.yml** (orchestration).

Start with a clear default profile, then let agents reference it by name:

**config/profiles.yml**
```yaml
spec: flatprofiles
spec_version: "2.6.0"
data:
  model_profiles:
    fast:
      provider: openai
      name: gpt-5-mini
      max_tokens: 2048

    quality:
      provider: openai
      name: gpt-5
      max_tokens: 4096

  # Used when a flatagent has no model field
  default: fast

  # Uncomment to force every agent to this profile
  # override: quality
```

**config/agent.yml**
```yaml
spec: flatagent
spec_version: "2.6.0"
data:
  name: hello-world-agent
  model:
    profile: fast
  system: >
    You are an agent in a test-time sequential scaling.
    Reply with exactly one output character in text format.
    No explanation. No wrapper.
  user: |
    Target: {{ input.target }}
    Built so far: {{ input.current }}
    Next character:
```

**config/machine.yml**
```yaml
spec: flatmachine
spec_version: "2.6.0"
data:
  name: hello-world-loop
  context:
    target: "{{ input.target }}"
    current: ""
  agents:
    builder: ./agent.yml
  hooks: hello-world-hooks
  states:
    start:
      type: initial
      transitions:
        - condition: "context.current == context.target"
          to: done
        - to: build_char
    build_char:
      agent: builder
      execution:
        type: retry
        retry_on_empty: true
        backoffs: [2, 8, 16, 35]
        jitter: 0.1
      input:
        current: "{{ context.current }}"
        target: "{{ context.target }}"
      output_to_context:
        expected_char: "{{ context.target[context.current|length] }}"
        last_output: "{{ output.next_char or output.content }}"
      transitions:
        - condition: "context.last_output != null and context.last_output != '' and context.last_output[0] == context.expected_char"
          to: append_char
        - to: build_char
    append_char:
      action: append_char
      transitions:
        - condition: "context.current == context.target"
          to: done
        - to: build_char
    done:
      type: final
      output:
        result: "{{ context.current }}"
        success: true
```

**run.py**
```python
import asyncio
from flatmachines import FlatMachine, HooksRegistry, LoggingHooks, setup_logging, get_logger

setup_logging(level="INFO")
logger = get_logger(__name__)

class HelloWorldHooks(LoggingHooks):
    def on_action(self, action_name, context):
        if action_name == "append_char":
            last_output = context.get("last_output", "")
            if last_output:
                context["current"] = context["current"] + str(last_output)[0]
        return context

async def main():
    hooks_registry = HooksRegistry()
    hooks_registry.register("hello-world-hooks", HelloWorldHooks)

    machine = FlatMachine(
        config_file="config/machine.yml",
        hooks_registry=hooks_registry,
    )

    result = await machine.execute(input={"target": "Hello, World!"}, max_agent_calls=20)
    logger.info(f"Result: '{result.get('result', '')}'")
    logger.info(f"Success: {result.get('success')}")

asyncio.run(main())
```

```bash
python run.py
```

## Versioning

All specs and SDKs use **lockstep versioning**. A single version number applies across the entire repository.

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
- [`flatagents-runtime.d.ts`](./flatagents-runtime.d.ts) — runtime interfaces + backend configuration contract

### Runtime definitions (from `flatagents-runtime.d.ts`)

`BackendConfig` defines runtime backend categories and allowed values:
- `persistence`: `memory` | `local` | `sqlite` | `redis` | `postgres` | `s3` | `dynamodb`
- `locking`: `none` | `local` | `sqlite` | `redis` | `consul` | `dynamodb`
- `results`: `memory` | `redis` | `dynamodb`
- `registration`: `memory` | `sqlite` | `redis` | `dynamodb`
- `work`: `memory` | `sqlite` | `redis` | `dynamodb`
- `signal`: `memory` | `sqlite` | `redis` | `dynamodb`
- `trigger`: `none` | `file` | `socket`

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
