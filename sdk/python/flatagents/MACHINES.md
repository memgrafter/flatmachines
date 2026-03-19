# FlatAgents (Python SDK) Reference

> **Target: ~1000 tokens.** LLM-optimized. See `flatagent.d.ts`, `profiles.d.ts` for canonical schemas.
>
> **Scope:** This file documents the **Python FlatAgents runtime** (single-call agents). Machine orchestration lives in the `flatmachines` package and is only re-exported here when installed.

## Concepts

**FlatAgent**: Single LLM call. Model + prompts + output schema. No orchestration.
**FlatMachine**: State machine that orchestrates multiple agents, actions, and machines (separate package).

| Need | Use |
|------|-----|
| Single LLM call | FlatAgent |
| Multi-step/branching/retry/errors | FlatMachine |

## FlatAgent Config (Spec Envelope)

```yaml
spec: flatagent
spec_version: "0.10.0"

data:
  name: code-reviewer
  model: "fast"          # profile name, or inline dict
  system: "..."          # Jinja2 template
  user: "..."            # Jinja2 template
  instruction_suffix: "..."  # appended to user prompt (optional)
  output:                # optional structured output schema
    issues: { type: list, items: { type: str } }
  mcp:                   # optional MCP tool config
    servers: { ... }
    tool_filter: { allow: ["filesystem:*"] }
    tool_prompt: |
      You have access to these tools:
      {% for tool in tools %}
      - {{ tool.name }}: {{ tool.description }}
      {% endfor %}

metadata: { ... }
```

### Template Variables

Jinja2 templates are rendered with:
- `input.*` — runtime input passed to `FlatAgent.call(**input)`
- `model.*` — resolved model config (provider/name/temperature/etc)
- `tools` — list of MCP tool definitions (if configured)
- `tools_prompt` — rendered tool prompt string

## Model Profiles (profiles.yml)

```yaml
spec: flatprofiles
spec_version: "0.10.0"

data:
  model_profiles:
    fast: { provider: cerebras, name: zai-glm-4.6, temperature: 0.6 }
    smart: { provider: anthropic, name: claude-3-opus-20240229 }
  default: fast
  # override: smart
```

Model resolution order (low → high): default profile → named profile → inline overrides → override profile.

**Python behavior:** `FlatAgent` auto-discovers the nearest `profiles.yml` in the agent’s config directory. If a parent machine/agent passes `profiles_dict`, it is used only as a fallback (no merging).

### Model Config Fields (inline)

Common fields supported by the Python runtime:
- `provider`, `name` (combined into `provider/name` if needed)
- `temperature`, `max_tokens`, `top_p`, `top_k`
- `frequency_penalty`, `presence_penalty`, `seed`
- `base_url` (passed as `api_base` to LiteLLM, or Codex base URL for `backend: codex`)
- `stream` (bool), `stream_options`
- `backend` ("litellm" | "aisuite" | "codex")
- `oauth` (Codex auth config: `auth_file`, `originator`, `refresh`, `timeout_seconds`, `max_retries`, `token_url`, `client_id`)

## Python Runtime Behavior

### Construction

```python
from flatagents import FlatAgent

agent = FlatAgent(config_file="agent.yml")
# or FlatAgent(config_dict={...})
# optional: profiles_file / profiles_dict / backend override
```

The runtime requires **jinja2** (for templates). YAML configs require **pyyaml**.

### Execution

```python
result = await agent.call(question="...")
print(result.output, result.content)
```

`FlatAgent.call(...)`:
- Renders system/user prompts with Jinja2.
- If an output schema is present **and no tools are used**, calls the LLM with `response_format: {type: "json_object"}`.
- Parses JSON output; if parsing fails, returns `{"_raw": "..."}`.
- Returns an `AgentResponse`:
  - `content`: raw text
  - `output`: structured JSON (optional)
  - `tool_calls`: list of tool requests (optional)
  - `raw_response`: provider response object

`call_sync(...)` is a synchronous wrapper for scripts.

### Backends

The Python SDK supports:
- **LiteLLMBackend** (default; `litellm`)
- **AISuiteBackend** (`aisuite`)
- **Codex OAuth backend** (`codex`)
- **LLMBackend** protocol for custom providers

Backend selection order:
1. `backend` argument to `FlatAgent(...)`
2. `data.model.backend` field
3. `FLATAGENTS_BACKEND` env var ("litellm" or "aisuite")
4. Auto-detect installed backend (prefers litellm)

Codex is never auto-detected; configure it explicitly via `backend: codex`.

Codex login helper:
```bash
python -m flatagents.providers.openai_codex_login --auth-file ~/.pi/agent/auth.json
```

## MCP Tooling

`FlatAgent` can call MCP tools when `data.mcp` is configured and a `MCPToolProvider` is supplied. The provider must implement:
- `connect(server_name, config)`
- `get_tools(server_name)`
- `call_tool(server_name, tool_name, arguments)`

Tool behavior:
- Tools are discovered per server and filtered via allow/deny patterns.
- Tool prompts can be injected into system/user templates via `tools_prompt`.
- Tool calls return as `tool_calls` in `AgentResponse`.

## Extractors (Advanced)

The SDK ships with extractors in `flatagents.baseagent`:
- `FreeExtractor` / `FreeThinkingExtractor`
- `StructuredExtractor` (JSON)
- `ToolsExtractor`
- `RegexExtractor`

These are useful when implementing **custom agents** via `BaseFlatAgent`.

## Custom Multi-step Agents (BaseFlatAgent)

For advanced workflows, subclass `BaseFlatAgent` and implement:
- `create_initial_state()`
- `generate_step_prompt(state)`
- `update_state(state, step_result)`
- `is_solved(state)`

`BaseFlatAgent` still uses the same backend and config loading utilities, but lets you define your own multi-step loop.

## Validation & Assets

- `validate_flatagent_config(config, warn=True, strict=False)`
- Schema bundles live in `flatagents/assets/` and are loaded via `importlib.resources`.
- Version mismatch triggers a **warning** (not a hard error).

## Logging & Metrics

Logging helpers:
```python
from flatagents import setup_logging, get_logger
setup_logging(level="INFO")
logger = get_logger(__name__)
```

Env vars:
- `FLATAGENTS_LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR)
- `FLATAGENTS_LOG_FORMAT` (standard/json/simple)
- `FLATAGENTS_LOG_DIR` (write logs to files)

Metrics (OpenTelemetry):
- Install with `flatagents[metrics]`
- `FLATAGENTS_METRICS_ENABLED=true` to enable
- Supports OTLP exporter via standard `OTEL_*` env vars

## Distributed Worker Pattern (Python)

The FlatAgents package includes worker orchestration helpers (used by FlatMachines):
- `DistributedWorkerHooks` (actions: register_worker, claim_job, complete_job, etc.)
- Backends: `RegistrationBackend`, `WorkBackend`
- Implementations: `SQLiteRegistrationBackend`, `SQLiteWorkBackend`, plus memory variants

These are designed to plug into FlatMachines state actions.

## Compatibility Notes

- If `flatmachines` is installed, `flatagents` **re-exports** `FlatMachine`, `MachineHooks`, execution types, persistence, and worker helpers for convenience.
- `python -m flatagents.run` delegates to the FlatMachines CLI runner (requires `flatmachines`).

Use this document to reason about **agent configs and runtime behavior**. For orchestration, see the FlatMachines package docs.
