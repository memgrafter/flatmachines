# FlatAgents

Define LLM agents in YAML. Run them anywhere.

Many changes in this repo are generated code, it is open source.

**For LLM/machine readers:** see [MACHINES.md](./MACHINES.md) for comprehensive reference.

## Why?

- **Composition over inheritance** — compose stateless agents and checkpointable machines
- **Compact structure** — easy for LLMs to read and generate
- **Simple hook interfaces** — escape hatches without complexity; webhook ready
- **Inspectable** — every agent and machine is readable config
- **Language-agnostic** — reduce code in any particular runtime
- **Common TypeScript interface** — single schema for agents, single schema for machines
- **Limitations** — machine topologies can get complex at scale

*Inspired by Kubernetes manifests and character card specifications.*

## Versioning

All specs (`flatagent.d.ts`, `flatmachine.d.ts`, `profiles.d.ts`) and SDKs (Python, JS) use **lockstep versioning**. A single version number applies across the entire repository.

## Core Concepts

Use machines to write flatagents and flatmachines, they are designed for LLMs.

| Term | What it is |
|------|------------|
| **FlatAgent** | A single LLM call: model + prompts + output schema |
| **FlatMachine** | A state machine that orchestrates multiple agents, actions, and state machines |

Use FlatAgent alone for simple tasks. Use FlatMachine when you need multi-step workflows, branching, or error handling.

## Examples

Current runnable examples live in [`./sdk/examples`](./sdk/examples):

| Example | Link |
|---------|------|
| anything_agent | [./sdk/examples/anything_agent](./sdk/examples/anything_agent) |
| character_card | [./sdk/examples/character_card](./sdk/examples/character_card) |
| coding_agent_cli | [./sdk/examples/coding_agent_cli](./sdk/examples/coding_agent_cli) |
| custom_coding_workflow | [./sdk/examples/custom_coding_workflow](./sdk/examples/custom_coding_workflow) |
| dfss_deepsleep | [./sdk/examples/dfss_deepsleep](./sdk/examples/dfss_deepsleep) |
| dfss_pipeline | [./sdk/examples/dfss_pipeline](./sdk/examples/dfss_pipeline) |
| distributed_worker | [./sdk/examples/distributed_worker](./sdk/examples/distributed_worker) |
| dynamic_agent | [./sdk/examples/dynamic_agent](./sdk/examples/dynamic_agent) |
| error_handling | [./sdk/examples/error_handling](./sdk/examples/error_handling) |
| gepa_self_optimizer | [./sdk/examples/gepa_self_optimizer](./sdk/examples/gepa_self_optimizer) |
| helloworld | [./sdk/examples/helloworld](./sdk/examples/helloworld) |
| human-in-the-loop | [./sdk/examples/human-in-the-loop](./sdk/examples/human-in-the-loop) |
| mdap | [./sdk/examples/mdap](./sdk/examples/mdap) |
| multi_paper_synthesizer | [./sdk/examples/multi_paper_synthesizer](./sdk/examples/multi_paper_synthesizer) |
| parallelism | [./sdk/examples/parallelism](./sdk/examples/parallelism) |
| peering | [./sdk/examples/peering](./sdk/examples/peering) |
| research_paper_analysis | [./sdk/examples/research_paper_analysis](./sdk/examples/research_paper_analysis) |
| rlm | [./sdk/examples/rlm](./sdk/examples/rlm) |
| story_writer | [./sdk/examples/story_writer](./sdk/examples/story_writer) |
| support_triage_json | [./sdk/examples/support_triage_json](./sdk/examples/support_triage_json) |
| writer_critic | [./sdk/examples/writer_critic](./sdk/examples/writer_critic) |

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
spec_version: "2.4.4"

data:
  name: code-reviewer

  model: "smart-expensive"  # Reference profile from profiles.yml

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
- **data.model** — Profile name, inline config, or profile with overrides
- **data.system** — System prompt (sets behavior)
- **data.user** — User prompt template (uses Jinja2, `{{ input.* }}` for runtime values)
- **data.output** — Structured output schema (the runtime extracts these fields)

## Model Profiles

Centralize model configurations in `profiles.yml` and reference them by name:

**profiles.yml**
```yaml
spec: flatprofiles
spec_version: "2.4.4"

data:
  model_profiles:
    fast-cheap:
      provider: cerebras
      name: zai-glm-4.6
      temperature: 0.6
      max_tokens: 2048

    smart-expensive:
      provider: anthropic
      name: claude-3-opus-20240229
      temperature: 0.3
      max_tokens: 4096

  default: fast-cheap      # Fallback when agent has no model
  # override: smart-expensive  # Uncomment to force all agents
```

**Agent usage:**
```yaml
# String shorthand — profile lookup
model: "fast-cheap"

# Profile with overrides
model:
  profile: "fast-cheap"
  temperature: 0.9

# Inline config (no profile)
model:
  provider: openai
  name: gpt-4
  temperature: 0.3
```

Resolution order (low → high): default profile → named profile → inline overrides → override profile

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

## Distributed Worker Pattern

FlatAgents includes `DistributedWorkerHooks` plus `RegistrationBackend`/`WorkBackend` implementations (SQLite in the reference SDK) to build worker pools.

Typical topology:
- **Checker**: `get_pool_state` → `calculate_spawn` → `spawn_workers` (requires `worker_config_path` in context or override in hooks)
- **Worker**: `register_worker` → `claim_job` → process → `complete_job`/`fail_job` → `deregister_worker`
- **Reaper**: `list_stale_workers` → `reap_stale_workers`

See [distributed_worker](./sdk/examples/distributed_worker/python) for a runnable demo.

## Features

- Checkpoint and restore
- Python SDK (TypeScript SDK in progress)
- [MACHINES.md](./MACHINES.md) — LLM-optimized reference docs
- Decider agents and machines
- On-the-fly agent and machine definitions
- Webhook hooks for remote state machine handling
- Metrics and logging
- Error recovery and exception handling at the state machine level
- Parallel machine execution (`machine: [a, b, c]`)
- Dynamic parallelism with `foreach`
- Fire-and-forget launches for background tasks
- Distributed worker orchestration (registration/work backends, scaling hooks, stale worker reaping)

## Planned

- Distributed execution backends (Redis/Postgres) + cross-network peering strategies
- SQL persistence backend
- TypeScript SDK
- `max_depth` config to limit machine launch nesting
- Checkpoint pruning to prevent storage explosion
- `$root/` path prefix — resolve agent/machine refs from workspace root, not config dir
- Input size validation — warn when prompt exceeds model context window
- Serialization warnings — flag non-JSON-serializable context values before checkpoint

## Specs

TypeScript definitions are the source of truth:
- [`flatagent.d.ts`](./flatagent.d.ts)
- [`flatmachine.d.ts`](./flatmachine.d.ts)
- [`profiles.d.ts`](./profiles.d.ts)

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

Codex OAuth backend (ChatGPT Plus/Pro credentials):

```yaml
model:
  provider: openai-codex
  name: gpt-5
  backend: codex
  oauth:
    auth_file: ~/.pi/agent/auth.json
    originator: pi
    refresh: true
```

Login helper:

```bash
python -m flatagents.providers.openai_codex_login --auth-file ~/.pi/agent/auth.json
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

Metrics are enabled by default and print to stdout every 5s. Redirect to file or use OTLP for production:

```bash
# Metrics print to stdout by default
python your_script.py

# Save to file
python your_script.py >> metrics.log 2>&1

# Disable if needed
FLATAGENTS_METRICS_ENABLED=false python your_script.py

# Send to OTLP collector for production
OTEL_METRICS_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
python your_script.py
```

**Env vars for metrics**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `FLATAGENTS_METRICS_ENABLED` | `true` | Enable OpenTelemetry metrics |
| `OTEL_METRICS_EXPORTER` | `console` | `console` (stdout) or `otlp` (production) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP collector endpoint |
| `OTEL_METRIC_EXPORT_INTERVAL` | `5000` / `60000` | Export interval in ms (5s for console, 60s for otlp) |
| `OTEL_SERVICE_NAME` | `flatagents` | Service name in metrics |
