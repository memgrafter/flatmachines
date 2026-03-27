# Dependency Surface & Optionalization Audit (FlatAgents + FlatMachines)

## Purpose

Document the current dependency model for:

- `sdk/python/flatagents`
- `sdk/python/flatmachines`

with emphasis on:

1. **Install-time optionality** (extras vs required)
2. **Runtime usage surface** (how much of each dependency is actually used)
3. **Dependency-chain impact** (how many transitive packages each dependency pulls in)
4. Design implications for making infrequently used features truly optional (not installed unless selected)

---

## Definitions

- **Optional (install-time):** dependency appears only in `[project.optional-dependencies]`, so it is not installed unless explicitly requested via an extra (or aggregate extra like `[all]`).
- **Optional (runtime):** feature path may be guarded with `try/except ImportError` and only fails when that feature is invoked.

These are different. A feature can be runtime-optional while still pulling required install-time dependencies.

---

## Current pyproject declarations

## flatagents (`sdk/python/flatagents/pyproject.toml`)

### Required
- `pyyaml`
- `jinja2`
- `aiofiles`
- `httpx`

### Optional
- `litellm`
- `aisuite[all]`
- `jsonschema>=4.0` (`validation`)
- `opentelemetry-api>=1.20.0`
- `opentelemetry-sdk>=1.20.0`
- `opentelemetry-exporter-otlp>=1.20.0` (`metrics`)

## flatmachines (`sdk/python/flatmachines/pyproject.toml`)

### Required
- `pyyaml`
- `jinja2`
- `aiofiles`
- `httpx`

### Optional
- `cel-python` (`cel`)
- `jsonschema>=4.0` (`validation`)
- `opentelemetry-*` (`metrics`)
- `flatagents>=0.10.0`
- `smolagents`
- `google-cloud-firestore>=2.11.0` (`gcp`)

---

## Runtime usage surface (source scan)

Scan scope: all runtime SDK files under:

- `sdk/python/flatagents/flatagents/**/*.py` (18 files)
- `sdk/python/flatmachines/flatmachines/**/*.py` (36 files)

Total: **54 runtime files**.

### Dependency usage summary

| Dependency | Files using it | Import sites | Primary usage surface |
|---|---:|---:|---|
| `pyyaml` | 8 | 8 | `yaml.safe_load`, `yaml.dump` |
| `jinja2` | 4 | 5 | `Environment`, `Template.render`, `from_string` |
| `aiofiles` | 1 | 1 | `aiofiles.open` in persistence backends |
| `httpx` | 4 | 4 | `AsyncClient`, network exceptions |
| `litellm` | 2 | 2 | `litellm.acompletion`, `completion_cost` |
| `aisuite` | 2 | 3 | `aisuite.Client`, `ProviderFactory.create_provider` |
| `jsonschema` | 3 | 3 | `Draft7Validator`, `validate` |
| `opentelemetry-*` | 2 | 16 | meter/exporter/provider wiring in monitoring modules |
| `cel-python` | 1 | 2 | `celpy.Environment`, CEL type conversions |
| `flatagents` (from flatmachines) | 4 | 7 | adapter integration + `AgentMonitor`/`ToolResult` coupling |
| `smolagents` | 2 | 2 | adapter (`MultiStepAgent`, `RunResult`) |
| `google-cloud-firestore` | 1 | 1 | `firestore.AsyncClient` backend |

---

## Dependency-chain contents (clean venv dry-run)

Measured via `uv pip install --dry-run <pkg>` in a fresh environment.

## Chains for dependencies **other than**
`cel-python`, `smolagents`, `opentelemetry-*`, `google-cloud-firestore`, `litellm`

| Dependency | Chain size | Chain contents |
|---|---:|---|
| `pyyaml` | 1 | `pyyaml` |
| `jinja2` | 2 | `jinja2`, `markupsafe` |
| `aiofiles` | 1 | `aiofiles` |
| `httpx` | 7 | `anyio`, `certifi`, `h11`, `httpcore`, `httpx`, `idna`, `typing-extensions` |
| `aisuite` | 10 | `aisuite`, `anyio`, `certifi`, `docstring-parser`, `h11`, `httpcore`, `httpx`, `idna`, `sniffio`, `typing-extensions` |
| `jsonschema` | 6 | `attrs`, `jsonschema`, `jsonschema-specifications`, `referencing`, `rpds-py`, `typing-extensions` |
| `flatagents` | 12 | `aiofiles`, `anyio`, `certifi`, `flatagents`, `h11`, `httpcore`, `httpx`, `idna`, `jinja2`, `markupsafe`, `pyyaml`, `typing-extensions` |

(For reference: `flatmachines` core chain is similarly 12 packages.)

---

## Clarifications requested in review

## Is `httpx` used outside `aisuite`?

**Yes.** Directly used in:

- `flatagents/providers/openai_codex_client.py` (Codex API transport)
- `flatagents/providers/openai_codex_auth.py` (OAuth refresh)
- `flatagents/providers/openai_codex_login.py` (OAuth exchange)
- `flatmachines/hooks.py` (`WebhookHooks` HTTP dispatch)

So `httpx` is not only a transitive consequence of `aisuite`.

## What about `jsonschema`?

Used in:

- `flatagents/validation.py` (`Draft7Validator`)
- `flatmachines/validation.py` (`Draft7Validator`)
- `flatmachines/execution.py` (`jsonschema.validate` for MDAP parsed result)

Config validation paths in `FlatAgent`/`FlatMachine` tolerate missing `jsonschema` (best-effort validation warning path).

---

## Codex backend: how it is managed now

Codex is behaviorally explicit (backend must be selected), but import topology is mostly eager:

- `flatagents/flatagent.py` imports `CodexClient` at module import time.
- `flatagents/providers/__init__.py` imports and re-exports codex client/types/errors.
- `flatagents/__init__.py` re-exports codex symbols from providers.

Result:

- Codex usage is feature-gated at runtime,
- but codex modules are still in core import graph,
- and codex currently depends on `httpx`, which contributes to required footprint.

---

## WebhookHooks: how it is managed now

`WebhookHooks` in `flatmachines/hooks.py` is runtime-optional:

- `httpx` import is guarded (`try/except ImportError`)
- constructor raises `ImportError` only when hook is used and `httpx` missing

But install-time, `httpx` is currently required by package metadata.

---

## Status against “should be optional unless selected”

### Already true extras (install-time optional)
- `litellm`
- `cel-python`
- `smolagents`
- `google-cloud-firestore`
- `opentelemetry-*` metrics bundle

### Still required in core install footprint
- `httpx` (despite main direct uses being Codex + WebhookHooks)
- `jinja2`, `pyyaml`, `aiofiles` (core config/render/persistence paths)

---

## Design implications (no code changes in this document)

If the product goal is strict install-time optionality for infrequently used surfaces:

1. **Codex optionalization should include import-graph decoupling**, not only backend runtime checks.
   - Move codex imports behind lazy boundaries.
   - Avoid unconditional codex symbol re-exports from top-level modules.

2. **WebhookHooks optionalization should include dependency metadata changes**, not only guarded runtime import.
   - Move `httpx` from required to an extra used by webhook/codex paths.

3. Keep aggregate extras (`all`, `local`, `gcp-all`) explicit that they intentionally pull broader chains.

---

## Reproducibility notes

This audit was produced from:

- Runtime source scans (`rg` + AST parsing over SDK runtime modules)
- Dependency closure dry-runs (`uv pip install --dry-run` in fresh venv)

Command patterns used:

- `rg -n "import httpx|jsonschema|..." sdk/python/flatagents/flatagents sdk/python/flatmachines/flatmachines`
- `uv pip install --python <venv>/bin/python --dry-run <package>`

---

## Bottom line

- Your target set (`cel`, `smolagents`, `otel`, `firestore`, `litellm`) is already install-time optional by extras.
- The two remaining notable “infrequent but still required-footprint” concerns are:
  - **Codex import wiring** (bundled and eagerly surfaced)
  - **WebhookHooks/httpx** (runtime optional, install-time required)

This is the key gap between current behavior and strict “installed only when selected” policy.