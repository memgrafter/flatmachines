# Plan: Named Entrypoints, Runner Commands & Hook Registration

**Status:** Draft
**Created:** 2026-03-22
**Scope:** `sdk/python/flatmachines/`, `sdk/js/`, spec
**Goal:** Add named entrypoints to the FlatMachine spec, define the execution/runner command surface, and formalize hook registration for both compiled and runtime-bound deployments.

---

## Executive Summary

FlatMachines currently have a single `type: initial` state as the implicit entry point. This plan introduces **named entrypoints** — multiple named entry paths into the same state machine — plus **runner commands** for the execution lifecycle (`start`, `resume`, `status`, `signal`), and a **hook registration model** that separates compiled hooks from runtime-registered hooks to support deployment targets from CLI binaries to Lambda functions.

---

## 1. Named Entrypoints

### Problem

A machine has one way in: the `type: initial` state. But real machines need multiple modes:
- Full interactive workflow vs headless batch
- Validate-only vs full execution
- Dry-run vs live
- Resume-from-error with different recovery logic

Today you work around this by creating separate machines or overloading context flags. Both are brittle.

### Spec Change

Add an optional `entrypoints` map at the top level of `data`:

```yaml
spec: flatmachine
spec_version: "2.6.0"
data:
  name: tagline-writer

  entrypoints:
    default: start          # required if entrypoints block present
    validate: validate_only
    dry-run: dry_run_start
    repair: resume_from_error

  states:
    start:
      type: initial
      transitions:
        - to: plan

    validate_only:
      type: initial
      transitions:
        - to: run_validation

    dry_run_start:
      type: initial
      context_override:
        dry_run: true
      transitions:
        - to: plan

    resume_from_error:
      type: initial
      transitions:
        - to: "{{ context.last_good_state }}"
```

### Rules

- `entrypoints` is optional. If absent, the single `type: initial` state is the default (backward compatible).
- If present, `default` key is required.
- Every entrypoint value must reference a state with `type: initial`.
- Entrypoint names are lowercase kebab-case identifiers.
- `context_override` on an initial state merges into context before execution begins.
- Validation: unreferenced `type: initial` states should warn if `entrypoints` is declared (suggests a forgotten registration).

### SDK Changes

**Python:**

```python
# Current
await machine.execute(input={"task": "..."})

# New — entrypoint selection
await machine.execute(input={"task": "..."}, entrypoint="validate")
await machine.execute(input={"task": "..."}, entrypoint="dry-run")
await machine.execute(input={"task": "..."})  # uses "default"
```

**JavaScript:**

```typescript
await machine.execute({ input: { task: "..." }, entrypoint: "validate" });
```

**Rust (future):**

```rust
machine.execute(input).entrypoint("validate").run().await?;
```

### Implementation

| Task | Scope | Complexity |
|------|-------|------------|
| Add `entrypoints` to spec schema | spec | S |
| Parse and validate `entrypoints` in Python SDK | `flatmachine.py` | M |
| Add `entrypoint` param to `execute()` | `flatmachine.py` | S |
| Add `context_override` merge on initial states | `flatmachine.py` | S |
| Validation: warn on orphaned initial states | `validation.py` | S |
| Parse and validate in JS SDK | `flatmachine.ts` | M |
| Update templates in flatmachine-manager skill | `templates.py` | S |
| Add `--entrypoint` flag to skill runner | `cli.py` | S |

---

## 2. Runner Commands

### Problem

The flatmachine-manager skill can create, validate, and manage configs. But there's no way to **run** a machine through the skill. The user has to write their own Python script or know the SDK API.

### Command Surface

Add execution lifecycle commands to the skill CLI:

```bash
# Execute
run.sh start --name tagline-writer --input '{"task": "write a tagline"}'
run.sh start --name tagline-writer --entrypoint validate --input '{"config": "..."}'

# Resume from checkpoint
run.sh resume --execution-id abc123

# Observe
run.sh status --name tagline-writer
run.sh executions --name tagline-writer [--status active|terminated|waiting]

# Interact with waiting machines
run.sh signal --execution-id abc123 --channel approval/task-1 --data '{"approved": true}'
```

### How It Works

| Command | What it does |
|---------|-------------|
| `start` | Loads config from registry, instantiates FlatMachine, calls `execute()`. Requires model profiles to be configured. |
| `resume` | Loads checkpoint from machine's SQLite DB, calls `execute(resume_from=id)`. |
| `status` | Queries the machine's checkpoint DB for latest snapshot per execution. No LLM. |
| `executions` | Lists all executions for a machine with state/event/timestamp. No LLM. |
| `signal` | Writes signal to the machine's signal backend, triggers dispatcher. No LLM. |

### Dependency Split

| Command | Needs LLM/API keys? | Needs registry? | Needs machine DB? |
|---------|---------------------|------------------|--------------------|
| `start` | Yes | Yes (config) | Yes (checkpoints) |
| `resume` | Yes | No | Yes |
| `status` | No | No | Yes |
| `executions` | No | No | Yes |
| `signal` | No | No | Yes (signal backend) |

### Implementation

| Task | Scope | Complexity |
|------|-------|------------|
| Add `start` command — load config, instantiate, execute | `cli.py` | M |
| Add `--entrypoint` flag to `start` | `cli.py` | S |
| Add `resume` command | `cli.py` | M |
| Add `status` command — query checkpoint DB | `cli.py` | S |
| Add `executions` command — list all executions | `cli.py` | S |
| Add `signal` command — write to signal backend | `cli.py` | M |
| Resolve profiles.yml path (config, env, default) | `cli.py` | S |
| Error handling for missing API keys / profiles | `cli.py` | S |

---

## 3. Hook Registration Model

### Problem

Today hooks are passed as Python objects at construction time. This works for:
- CLI tools (compile hooks in)
- Python scripts (instantiate and pass)

It doesn't work for:
- Lambda (need stable SDK artifact, swap hooks without rebuild)
- Multi-tenant (different hooks per customer/machine)
- Non-Python environments (WASM, HTTP services, shell scripts)

### Architecture

The SDK runtime is the stable core. Hooks are plugged in through a registration surface that supports multiple binding methods:

```
FlatMachineRuntime
  ├── Compiled hooks (trait impl, maximum performance)
  ├── WASM hooks (sandboxed, portable, hot-swappable)
  ├── HTTP hooks (hooks are services — Lambda, Cloud Run, any API)
  ├── Script hooks (Python/Lua/shell via IPC, dev/prototyping)
  └── Config-declared hooks (behavior in YAML — routing, templating)
```

### Hook Registration API

**Python:**

```python
runtime = FlatMachineRuntime()
runtime.register_action("human_review", HttpAction("https://review-svc/api"))
runtime.register_action("score", WasmAction.load("scoring.wasm"))
runtime.register_action("notify", lambda ctx: send_notification(ctx))
runtime.register_tool("create_machine", create_machine_handler)

machine = runtime.build(config)
await machine.execute(input)
```

**Rust (future):**

```rust
let runtime = FlatMachineRuntime::new()
    .register_action("human_review", HttpAction::new("https://review-svc/api"))
    .register_action("score", WasmAction::load("scoring.wasm"))
    .register_tool("create_machine", create_machine_handler)
    .default_action_handler(ConfigDeclaredAction::new())
    .build();
```

### Config-Declared Actions

The `action` field in states can become a structured callable declaration instead of an opaque string:

```yaml
states:
  review:
    action:
      type: http
      url: https://review-service/approve
      timeout: 300

  process:
    action:
      type: wasm
      module: scoring.wasm
      function: score_content

  notify:
    action:
      type: lambda
      arn: arn:aws:lambda:us-east-1:123:function:notify
```

Backward compatible: plain string `action: human_review` still resolves through `hooks.on_action()` as today.

### Lambda Deployment

**Zip structure:**

```
lambda.zip/
└── bootstrap              # stable SDK binary (Rust) or handler.py (Python)
```

Config and hooks fetched from S3/registry at cold start. HTTP hooks are URLs. WASM hooks downloaded to `/tmp`.

**Update without redeployment:**

| Changed | Update method | Downtime |
|---------|--------------|----------|
| Machine YAML config | Update in S3/registry, next cold start picks up | None |
| WASM hook module | Update in S3, next cold start downloads | None |
| HTTP hook URL | Update config | None |
| SDK binary | Update Layer/zip | ~seconds |

Force pickup by bumping a config version env var:

```bash
aws lambda update-function-configuration \
  --function-name my-machine \
  --environment "Variables={CONFIG_VERSION=v3}"
```

### Skill Integration

The skill can manage hook registrations as registry entries:

```bash
run.sh register-hook --machine my-machine --action human_review --type http --url https://...
run.sh register-hook --machine my-machine --action score --type wasm --module ./scoring.wasm
run.sh list-hooks --machine my-machine
run.sh export --name my-machine --target s3://bucket/machines/my-machine/
run.sh deploy --name my-machine --lambda my-function --bucket my-bucket
```

### Implementation

| Task | Scope | Complexity |
|------|-------|------------|
| Define `FlatMachineRuntime` builder with `register_action`/`register_tool` | Python SDK | L |
| Implement `HttpAction` (POST with JSON body/response) | Python SDK | M |
| Implement `WasmAction` (wasmtime runtime) | Python SDK | L |
| Implement config-declared action dispatch (type: http/wasm/lambda) | Python SDK | M |
| Backward compat: string action still resolves through hooks | Python SDK | S |
| Add `register-hook`, `list-hooks` to skill CLI | skill | M |
| Add `export` command (config + hooks to S3/directory) | skill | M |
| Add `deploy` command (export + Lambda update) | skill | L |
| Schema: `hook_registrations` table in registry | registry | S |

---

## Spec Version

These changes target **spec version 2.6.0**:
- `entrypoints` map (additive, backward compatible)
- `context_override` on initial states (additive)
- Structured `action` declarations (backward compatible — string still works)

---

## Sequencing

```
Phase 1: Named entrypoints (spec + Python SDK + JS SDK + skill templates)
    ↓
Phase 2: Runner commands (start, resume, status, executions, signal)
    ↓
Phase 3: Hook registration (FlatMachineRuntime, HttpAction, config-declared actions)
    ↓
Phase 4: Deployment commands (export, deploy, register-hook)
```

Phase 1 is self-contained and immediately useful. Phase 2 depends on Phase 1 (needs `--entrypoint`). Phase 3 is independent but enables Phase 4.
