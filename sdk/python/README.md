# FlatAgents

Define LLM agents in YAML. Run them anywhere.

**For LLM/machine readers:** see [MACHINES.md](./MACHINES.md) for comprehensive reference.

## Why?

- **Composition over inheritance** — compose stateless agents and checkpointable machines
- **Compact structure** — easy for LLMs to read and generate
- **Simple hook interfaces** — escape hatches without complexity; webhook ready
- **Inspectable** — every agent and machine is readable config
- **Language-agnostic** — reduce code in any particular runtime
- **Common TypeScript interface** — single schema for agents, single schema for machines
- **Limitations** — hierarchical state machine networks can get complex at scale

*Inspired by Kubernetes manifests and character card specifications.*

## Core Concepts

Use machines to write flatagents and flatmachines, they are designed for LLMs.

| Term | What it is |
|------|------------|
| **FlatAgent** | A single LLM call: model + prompts + output schema |
| **FlatMachine** | A state machine that orchestrates multiple agents, actions, and state machines |

Use FlatAgent alone for simple tasks. Use FlatMachine when you need multi-step workflows, branching, or error handling.

## Examples

| Example | What it demonstrates |
|---------|---------------------|
| [helloworld](./sdk/python/examples/helloworld) | Minimal setup — single agent, single state machine |
| [writer_critic](./sdk/python/examples/writer_critic) | Multi-agent loop — writer drafts, critic reviews, iterates |
| [story_writer](./sdk/python/examples/story_writer) | Multi-step creative workflow with chapter generation |
| [human_in_loop](./sdk/python/examples/human_in_loop) | Pause execution for human approval via hooks |
| [error_handling](./sdk/python/examples/error_handling) | Error recovery and retry patterns at state machine level |
| [dynamic_agent](./sdk/python/examples/dynamic_agent) | On-the-fly agent generation from runtime context |
| [character_card](./sdk/python/examples/character_card) | Loading agent config from character card format |
| [mdap](./sdk/python/examples/mdap) | MDAP voting execution — multi-sample consensus |
| [gepa_self_optimizer](./sdk/python/examples/gepa_self_optimizer) | Self-optimizing prompts via reflection and critique |
| [research_paper_analysis](./sdk/python/examples/research_paper_analysis) | Document analysis with structured extraction |
| [multi_paper_synthesizer](./sdk/python/examples/multi_paper_synthesizer) | Cross-document synthesis with dynamic child machines |
| [support_triage_json](./sdk/python/examples/support_triage_json) | JSON input/output with classification pipeline |

## Quick Start

```bash
pip install flatagents[all]
```

```python
from flatagents import FlatAgent

agent = FlatAgent(config_file="reviewer.yml")
result = await agent.call(query="Review this code...")
print(result.output)
```

## Example Agent

**reviewer.yml**
```yaml
spec: flatagent
spec_version: "0.0.0"

data:
  name: code-reviewer

  model:
    provider: openai
    name: gpt-4
    temperature: 0.3

  system: |
    You are a senior code reviewer. Analyze code for bugs, 
    style issues, and potential improvements.

  user: |
    Review this code:
    {{ input.code }}

  output:
    issues:
      type: list
      items:
        type: str
      description: "List of issues found"
    rating:
      type: str
      enum: ["good", "needs_work", "critical"]
      description: "Overall code quality"
```

**What the fields mean:**

- **spec/spec_version** — Format identifier and version
- **data.name** — Agent identifier
- **data.model** — LLM provider, model name, and parameters
- **data.system** — System prompt (sets behavior)
- **data.user** — User prompt template (uses Jinja2, `{{ input.* }}` for runtime values)
- **data.output** — Structured output schema (the runtime extracts these fields)

## Output Types

```yaml
output:
  answer:      { type: str }
  count:       { type: int }
  score:       { type: float }
  valid:       { type: bool }
  raw:         { type: json }
  items:       { type: list, items: { type: str } }
  metadata:    { type: object, properties: { key: { type: str } } }
```

Use `enum: [...]` to constrain string values.

## Multi-Agent Workflows

For orchestration, use FlatMachine ([full docs in MACHINES.md](./MACHINES.md)):

```python
from flatagents import FlatMachine

machine = FlatMachine(config_file="workflow.yml")
result = await machine.execute(input={"query": "..."})
```

FlatMachine provides: state transitions, conditional branching, loops, retry with backoff, and error recovery—all in YAML.

## Features

- Checkpoint and restore
- Python SDK (TypeScript SDK in progress)
- [MACHINES.md](./MACHINES.md) — LLM-optimized reference docs
- Decider agents and machines
- On-the-fly agent and machine definitions
- Webhook hooks for remote state machine handling
- Metrics and logging
- Error recovery and exception handling at the state machine level

## Planned

- Distributed execution — cross-network HSMs, inter-machine strategies
- Parallel state execution
- SQL persistence backend
- TypeScript SDK
- `max_depth` config to limit child machine nesting
- Checkpoint pruning to prevent storage explosion
- `$root/` path prefix — resolve agent/machine refs from workspace root, not config dir
- Input size validation — warn when prompt exceeds model context window
- Serialization warnings — flag non-JSON-serializable context values before checkpoint

## Specs

TypeScript definitions are the source of truth:
- [`flatagent.d.ts`](./flatagent.d.ts)
- [`flatmachine.d.ts`](./flatmachine.d.ts)

## Python SDK

```bash
pip install flatagents[litellm]
```

### LLM Backends

```python
from flatagents import LiteLLMBackend, AISuiteBackend

# LiteLLM (default)
agent = FlatAgent(config_file="agent.yml")

# AISuite
backend = AISuiteBackend(model="openai:gpt-4o")
agent = FlatAgent(config_file="agent.yml", backend=backend)
```

### Hooks

Extend machine behavior with Python hooks:

```python
from flatagents import FlatMachine, MachineHooks

class CustomHooks(MachineHooks):
    def on_state_enter(self, state: str, context: dict) -> dict:
        context["entered_at"] = time.time()
        return context

    def on_action(self, action: str, context: dict) -> dict:
        if action == "fetch_data":
            context["data"] = fetch_from_api()
        return context

machine = FlatMachine(config_file="machine.yml", hooks=CustomHooks())
```

**Available hooks**: `on_machine_start`, `on_machine_end`, `on_state_enter`, `on_state_exit`, `on_transition`, `on_error`, `on_action`

### Execution Types

```yaml
execution:
  type: retry              # retry | parallel | mdap_voting
  backoffs: [2, 8, 16, 35] # Seconds between retries
  jitter: 0.1              # ±10% random variation
```

| Type | Use Case |
|------|----------|
| `default` | Single call |
| `retry` | Rate limit handling with backoff |
| `parallel` | Multiple samples (`n_samples`) |
| `mdap_voting` | Consensus voting (`k_margin`, `max_candidates`) |

### Schema Validation

```python
from flatagents import validate_flatagent_config, validate_flatmachine_config

warnings = validate_flatagent_config(config)
warnings = validate_flatmachine_config(config)
```

### Logging & Metrics

```python
from flatagents import setup_logging, get_logger

setup_logging(level="INFO")  # Respects FLATAGENTS_LOG_LEVEL env var
logger = get_logger(__name__)
```

**Env vars**: `FLATAGENTS_LOG_LEVEL` (`DEBUG`/`INFO`/`WARNING`/`ERROR`), `FLATAGENTS_LOG_FORMAT` (`standard`/`json`/`simple`)

For OpenTelemetry metrics:

```bash
pip install flatagents[metrics]
export FLATAGENTS_METRICS_ENABLED=true
```
