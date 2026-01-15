# JS SDK v0.4.0 Compatibility Findings

Scope: Compare the current JS SDK implementation against the repo-root specs:
- `flatmachine.d.ts` (SPEC_VERSION 0.4.0)
- `flatagent.d.ts` (SPEC_VERSION 0.6.0)

This report calls out issues that block the JS examples when using the spec-compliant YAML configs.
Each finding notes whether the root cause is the JS SDK or a config/spec mismatch.

## Findings

1) **Machine name mapping (`data.machines`) is ignored**
   - Spec: `data.machines` maps logical machine names to paths/inline configs. State `machine:` references those names. (`flatmachine.d.ts`)
   - JS SDK: `FlatMachine.executeMachine` treats `def.machine` as a filepath string and never resolves `data.machines`. (`sdk/js/src/flatmachine.ts:126-155`)
   - Impact: `machine: [summarizer_machine, sentiment_machine]` fails because the SDK tries to open `.../summarizer_machine` as a file.
   - Root cause: **JS SDK bug** (missing spec feature).

2) **`foreach` expects arrays but templating returns strings**
   - Spec: `foreach` takes a Jinja2 expression that yields an array. (`flatmachine.d.ts`)
   - JS SDK: `render()` always returns strings for Jinja output unless it parses valid JSON. (`sdk/js/src/flatmachine.ts:194-198`)
   - Impact: `foreach: "{{ context.texts }}"` yields a string, so `items.map` throws. (`sdk/js/src/flatmachine.ts:129-137`)
   - Root cause: **JS SDK bug** (template engine not preserving structured types).

3) **`action` hooks are not implemented**
   - Spec: State `action` calls a hook action by name. (`flatmachine.d.ts`)
   - JS SDK: No `action` in `State` type and no runtime dispatch. (`sdk/js/src/types.ts:26-40`, `sdk/js/src/flatmachine.ts`)
   - Impact: Human-in-the-loop configs using `action: human_review` never trigger the review logic.
   - Root cause: **JS SDK bug** (missing spec feature).

4) **`on_error` only supports string, not mapping**
   - Spec: `on_error` can be a string or a map by error type. (`flatmachine.d.ts`)
   - JS SDK: Assumes `def.on_error` is a string; no map support. (`sdk/js/src/flatmachine.ts:73-76`)
   - Impact: Error-routing maps in configs are ignored.
   - Root cause: **JS SDK bug** (missing spec feature).

5) **Parallelism features missing: `key`, `mode`, `timeout`, per-machine inputs**
   - Spec: `foreach.key`, parallel `mode`, `timeout`, and `machine: [{name, input}]` are supported. (`flatmachine.d.ts`)
   - JS SDK: These fields are absent from types and runtime handling. (`sdk/js/src/types.ts`, `sdk/js/src/flatmachine.ts`)
   - Impact: Results cannot be keyed, parallel mode/timeouts are ignored, and per-machine inputs are unsupported.
   - Root cause: **JS SDK bug** (missing spec features).

6) **`expression_engine` and settings are ignored**
   - Spec: `expression_engine` and `settings.max_steps` are supported. (`flatmachine.d.ts`)
   - JS SDK: Uses a hard-coded simple parser and fixed `maxSteps = 100`. (`sdk/js/src/flatmachine.ts:46-50`, `sdk/js/src/expression.ts`)
   - Impact: CEL expressions and custom max steps are unsupported.
   - Root cause: **JS SDK bug** (missing spec features).

7) **Config-level persistence is ignored**
   - Spec: `data.persistence` enables checkpointing with backend and options. (`flatmachine.d.ts`)
   - JS SDK: Only uses `options.persistence`; ignores YAML persistence fields. (`sdk/js/src/flatmachine.ts:29-38`)
   - Impact: Machines with persistence defined in YAML run without checkpointing.
   - Root cause: **JS SDK bug** (missing spec feature).

8) **`context.last_error`/`last_error_type` naming mismatch**
   - Spec: Errors populate `context.last_error` and `context.last_error_type`. (docs in repo instructions)
   - JS SDK: Sets `context.lastError` only. (`sdk/js/src/flatmachine.ts:73-76`)
   - Impact: Configs checking `context.last_error` will not see the error info.
   - Root cause: **JS SDK bug** (spec mismatch).

9) **Structured output prompting is disabled**
   - Spec: Output schema should guide structured output. (`flatagent.d.ts`)
   - JS SDK: `if (this.config.data.output && !tools)` is always false because `tools` is an array; output instruction never added. (`sdk/js/src/flatagent.ts:28-38`)
   - Impact: Lower JSON adherence for all agents.
   - Root cause: **JS SDK bug**.

10) **Model config fields are dropped**
    - Spec: `top_p`, `frequency_penalty`, `presence_penalty`, etc. are supported. (`flatagent.d.ts`)
    - JS SDK: `AgentConfig` in `sdk/js/src/types.ts` only includes `name`, `provider`, `temperature`, `max_tokens`.
    - Impact: Configs that set these fields are ignored.
    - Root cause: **JS SDK bug** (incomplete model mapping).

11) **`instruction_suffix` is not implemented**
    - Spec: `instruction_suffix` is supported in agent config. (`flatagent.d.ts`)
    - JS SDK: Missing from types and runtime; never appended. (`sdk/js/src/types.ts`, `sdk/js/src/flatagent.ts`)
    - Impact: Agents relying on instruction suffix behavior will diverge.
    - Root cause: **JS SDK bug**.

12) **Spec version mismatch in some configs**
    - Spec baseline: `flatmachine.d.ts` is 0.4.0; `flatagent.d.ts` is 0.6.0.
    - Example configs copied from Python include `spec_version: "0.3.0"` (e.g., `sdk/js/examples/human-in-the-loop/config/machine.yml`).
    - Impact: If the SDK enforces spec_version (or validation is added), these configs will be invalid.
    - Root cause: **Config mismatch** (not JS SDK).

## Summary

The configs are largely spec-compliant for 0.4.0, but the JS SDK does not yet implement several required 0.4.0 machine features and 0.6.0 agent fields. The largest blockers for the current examples are machine name resolution (`data.machines`), `foreach` handling of arrays, and `action` hooks.
