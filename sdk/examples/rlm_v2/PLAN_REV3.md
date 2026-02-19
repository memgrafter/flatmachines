# PLAN_REV3 — Standalone Implementation Plan for `sdk/examples/rlm_v2/python`

This is a standalone, implementation-ready plan for a stripped-down RLM v2 example that is aligned with the paper’s Algorithm 1 while fitting the FlatAgents/FlatMachines Python SDK.

---

## 1) Scope and goals

## 1.1 Primary goal
Implement a minimal recursive loop with these properties:

1. Long input is stored in a persistent REPL variable (`context`), **not** injected into root model context.
2. Root model iteratively emits REPL code.
3. Code executes in persistent REPL state.
4. Only bounded execution metadata is fed back to root model.
5. `llm_query()` can recursively invoke the same machine.
6. Termination is strict: stop only when REPL variable `Final` exists and is not `None`.

## 1.2 Secondary goals
- Keep architecture simple (single machine + single coder agent + hooks).
- Thread parameter limits end-to-end (`max_depth`, `timeout_seconds`, `max_iterations`, `max_steps`).
- Align with FlatMachines best practices for simple handoff and explicit mappings.

## 1.3 Non-goals (v3 still deferred)
- No `FINAL(...)` / `FINAL_VAR(...)` text-tag parsing.
- No async subcall fan-out (`llm_query_batched`) in this version.
- No advanced compaction/summarization of full trajectory history.
- No production-grade hard cancellation of timed-out recursive threads.

---

## 2) Key invariants (must not be violated)

1. **Task/context separation invariant**
   - `task` (short) is passed to root agent.
   - `long_context` (large) is loaded into REPL only.
   - Root agent never receives full `long_context` directly.

2. **Persistent state invariant**
   - REPL locals/globals survive across loop iterations for one machine execution.

3. **Bounded feedback invariant**
   - Root prompt only receives compact metadata from each REPL execution (prefix/length/error/changed-vars summary).

4. **Strict final invariant**
   - Final state reached only when `Final` exists in REPL namespace and `Final is not None`.
   - Falsy values like `0` and `False` are valid final answers.

5. **Depth guard invariant**
   - `llm_query()` recursion must enforce `current_depth + 1 <= max_depth`.

---

## 3) SDK compatibility constraints and design choices

This plan is designed around observed FlatMachines/FlatAgents behavior:

1. **Template typing**
   - Jinja rendering returns strings.
   - Use **bare path mappings** (`input.task`, `output.content`) wherever possible to preserve native types.
   - Coerce/default numeric fields in hooks (`init_session`) to avoid int/str comparison bugs.

2. **`settings.max_steps` behavior**
   - `settings.max_steps` in config is not auto-applied by `FlatMachine.execute()`.
   - `main.py` and recursive invoker must explicitly pass `max_steps=...` to execute calls.

3. **Agent output contract**
   - For non-schema FlatAgent responses, `output.content` should exist via adapter fallback.
   - We still include a runtime sanity check and explicit failure path if empty/non-string.

4. **Persistence default clarity**
   - This example explicitly configures memory/no-persist behavior in YAML for minimal overhead.

---

## 4) Input/output contract

## 4.1 Top-level machine input
Required:
- `task: str`
- `long_context: str`

Optional controls:
- `current_depth: int` (default 0)
- `max_depth: int` (default 5)
- `timeout_seconds: int` (default 300)
- `max_iterations: int` (default 20)
- `max_steps: int` (default 80)
- `machine_config_path: str` (absolute path to same `machine.yml`)
- `sub_model_profile: str | None`
- `model_override: str | None`

## 4.2 Final output
Common fields (all terminal states):
- `answer`
- `reason` (`final` | `max_iterations` | `error`)
- `iteration`
- `depth`

Additional on error:
- `error`

---

## 5) Context schema (machine-level)

Context keys initialized in `data.context`:

- `task`: `input.task`
- `long_context`: `input.long_context`

- `current_depth`: `input.current_depth`
- `max_depth`: `input.max_depth`
- `timeout_seconds`: `input.timeout_seconds`
- `max_iterations`: `input.max_iterations`
- `max_steps`: `input.max_steps`

- `machine_config_path`: `input.machine_config_path`
- `sub_model_profile`: `input.sub_model_profile`
- `model_override`: `input.model_override`

- `session_id`: `null`
- `context_length`: `0`
- `context_prefix`: `""`

- `iteration`: `0`
- `raw_response`: `null`
- `last_exec_metadata`: `{}`
- `history_meta`: `[]`

- `best_partial`: `null`
- `final_answer`: `null`
- `is_final`: `false`

Type normalization/defaulting is performed in `init_session` hook.

---

## 6) Machine YAML design (single-loop)

## 6.1 State flow
1. `start` (initial) → action `init_session`
2. `generate_code` → agent `coder` (retry enabled)
3. `execute_code` → action `execute_response_code`
4. `check_final` → action `check_final`
5. loop back or terminate:
   - `done` if final
   - `max_iter_done` if iteration cap
   - `error_done` on unhandled error

## 6.2 Pseudo-YAML sketch

```yaml
spec: flatmachine
spec_version: "1.0.0"

data:
  name: rlm-v2
  profiles: ./profiles.yml

  persistence:
    enabled: false
    backend: memory

  context:
    task: input.task
    long_context: input.long_context

    current_depth: input.current_depth
    max_depth: input.max_depth
    timeout_seconds: input.timeout_seconds
    max_iterations: input.max_iterations
    max_steps: input.max_steps

    machine_config_path: input.machine_config_path
    sub_model_profile: input.sub_model_profile
    model_override: input.model_override

    session_id: null
    context_length: 0
    context_prefix: ""

    iteration: 0
    raw_response: null
    last_exec_metadata: {}
    history_meta: []

    best_partial: null
    final_answer: null
    is_final: false

  agents:
    coder: ./coder.yml

  on_error: error_done

  states:
    start:
      type: initial
      action: init_session
      transitions:
        - to: generate_code

    generate_code:
      agent: coder
      execution:
        type: retry
        backoffs: [2, 8, 16]
        jitter: 0.1
      input:
        task: context.task
        context_length: context.context_length
        context_prefix: context.context_prefix
        depth: context.current_depth
        max_depth: context.max_depth
        iteration: context.iteration
        history_meta: context.history_meta
      output_to_context:
        raw_response: output.content
      on_error: error_done
      transitions:
        - to: execute_code

    execute_code:
      action: execute_response_code
      on_error: error_done
      transitions:
        - to: check_final

    check_final:
      action: check_final
      on_error: error_done
      transitions:
        - condition: "context.is_final == true"
          to: done
        - condition: "context.iteration >= context.max_iterations"
          to: max_iter_done
        - to: generate_code

    done:
      type: final
      output:
        answer: context.final_answer
        reason: "final"
        iteration: context.iteration
        depth: context.current_depth

    max_iter_done:
      type: final
      output:
        answer: context.best_partial
        reason: "max_iterations"
        iteration: context.iteration
        depth: context.current_depth

    error_done:
      type: final
      output:
        answer: context.best_partial
        reason: "error"
        error: context.last_error
        iteration: context.iteration
        depth: context.current_depth

  settings:
    max_steps: 80

  hooks:
    file: "../python/src/rlm_v2/hooks.py"
    class: "RLMV2Hooks"
```

Notes:
- Bare-path mappings are used intentionally for type preservation.
- `settings.max_steps` is advisory in config; caller must pass explicit `max_steps` during execution.

---

## 7) Coder agent design (`coder.yml`)

Single flatagent (no output schema to preserve freeform text/code behavior).

System prompt requirements:
1. You are solving `task` over REPL variable `context`.
2. You only receive compact metadata from execution outputs.
3. Use ```repl code blocks for concrete actions.
4. Use `llm_query()` for semantic sub-analysis when needed.
5. Keep intermediate buffers in variables.
6. When complete, set `Final = <answer>` in REPL code.
7. Do not emit FINAL tags in plain text.

User prompt includes:
- task
- depth/iteration
- context metadata
- bounded `history_meta`

---

## 8) Hooks and REPL internals

## 8.1 `hooks.py` action handlers

`RLMV2Hooks.on_action(action_name, context)` dispatches:
- `init_session`
- `execute_response_code`
- `check_final`

### `init_session`
Responsibilities:
- Normalize defaults and types:
  - ints: `current_depth`, `max_depth`, `timeout_seconds`, `max_iterations`, `max_steps`
  - sensible defaults when `None`
- Validate required fields (`task`, `machine_config_path` optionally if recursion expected)
- Create REPL session (`session_id`) and load `long_context` into REPL variable `context`
- Compute and store metadata:
  - `context_length`
  - `context_prefix` (bounded)

### `execute_response_code`
Responsibilities:
- Read `raw_response` (must be string)
- Extract all ```repl blocks (ordered)
- Execute blocks sequentially in persistent REPL
- Increment `iteration`
- Capture compact metadata entry:
  - `iteration`
  - `code_prefix` (<=240)
  - `stdout_prefix` (<=240)
  - `stdout_length`
  - `stderr_prefix` (<=120)
  - `had_error`
  - `changed_vars` (<=10)
- Append to `history_meta`, keep last N=5
- Update `last_exec_metadata`
- Update `best_partial` heuristically from known variable names or useful stdout

### `check_final`
Responsibilities:
- Use strict strategy:
  - final iff `Final` key exists in REPL locals and `Final is not None`
- If final:
  - `is_final = True`
  - `final_answer = repl.locals['Final']`
- Else:
  - `is_final = False`

## 8.2 `repl.py` session manager

Provide:
- `REPLSession` (persistent namespace)
- `REPLRegistry` (session_id -> session)
- Utility:
  - code extraction
  - execution with stdout/stderr capture
  - variable diff (changed vars)

Injected symbols:
- `context` (long context)
- `llm_query(prompt, model=None)`

---

## 9) Recursive `llm_query()` design

## 9.1 Strategy
`llm_query()` is implemented as a Python callable injected into REPL globals. It performs a blocking recursive machine invocation using the same `machine.yml`.

## 9.2 Sub-input mapping (important)
At parent depth `d`, for call `llm_query(sub_prompt, model=None)`:

1. If `d + 1 > max_depth`, return sentinel string, e.g. `"SUBCALL_DEPTH_LIMIT"`.
2. Else build sub-input:
   - `task`: `"Answer the request encoded in REPL variable context. Set Final when complete."`
   - `long_context`: `sub_prompt`
   - `current_depth`: `d + 1`
   - inherit: `max_depth`, `timeout_seconds`, `max_iterations`, `max_steps`, `machine_config_path`
   - pass routing hints: `sub_model_profile`, `model_override`

This preserves the long-context invariant: sub-prompt payload is treated as REPL context for the submachine.

## 9.3 Execution bridge
- Use `ThreadPoolExecutor(max_workers=1)`
- Inside worker thread:
  - instantiate `FlatMachine(config_file=machine_config_path)`
  - call `execute_sync(input=sub_input, max_steps=sub_input['max_steps'])`
- Wait with `future.result(timeout=timeout_seconds)`
- On timeout, return deterministic sentinel string (e.g., `"SUBCALL_TIMEOUT"`)
- On exception, return deterministic sentinel string (e.g., `"SUBCALL_ERROR: ..."`)

## 9.4 Known limitation
Timed-out worker thread is not forcibly terminated by Python futures timeout; this is documented in README as a v2 limitation.

---

## 10) Model routing policy

For `llm_query(prompt, model=None)`:

1. If `model` is provided:
   - set `model_override=model` in sub-input.
2. If `model` is `None`:
   - use `sub_model_profile` if present; otherwise inherit root/default profile.

Implementation note:
- If dynamic model override cannot be cleanly threaded through flatagent config at runtime, fallback to `sub_model_profile` and record a warning in execution metadata.

---

## 11) `main.py` and CLI wiring (required details)

## 11.1 CLI args
- `--task`
- `--file` (long context source)
- `--max-depth` (default 5)
- `--timeout-seconds` (default 300)
- `--max-iterations` (default 20)
- `--max-steps` (default 80)
- `--sub-model-profile` (optional)
- `--demo`

## 11.2 Runtime wiring
- Resolve `machine_config_path` as absolute path to `config/machine.yml`.
- Build input payload with explicit typed values.
- Call `await machine.execute(input=input_payload, max_steps=max_steps)`.

This explicit `max_steps` pass is mandatory.

---

## 12) Persistence and operational posture for this example

Given recursion and many short subcalls, this example should minimize checkpoint overhead:

- `persistence.enabled: false`
- backend `memory`

Rationale:
- This is an educational example, not a high-concurrency production runner.
- Avoids file lock/checkpoint churn in recursive paths.

Future productionization can switch to explicit DB-backed persistence + lease locks per best-practice doc.

---

## 13) Observability and guardrails (lightweight)

## 13.1 Observability
- Add structured logging in hooks for:
  - iteration, depth
  - number of code blocks
  - recursion count per iteration
  - timeout/depth-limit events

## 13.2 Lightweight quality guardrail
In `check_final`, when `Final` set:
- record metadata warning if answer is trivially degenerate (e.g., empty whitespace only)
- do not block termination in v3 (just mark warning)

---

## 14) Demo scenario (recursion-friendly)

Use a long multi-section text and task:

> “For each chapter, extract the main argument and one supporting quote; then synthesize an overall thesis across all chapters.”

Why this demo:
- Encourages semantic decomposition.
- Naturally benefits from `llm_query()` over section/chunk prompts.
- Not trivially solvable by `context.count(...)`.

---

## 15) Implementation phases

### Phase A — Scaffold
- Create files under `sdk/examples/rlm_v2/config` and `python/src/rlm_v2`.
- Add machine/agent/profile configs and CLI skeleton.

### Phase B — Core loop
- Implement REPL session manager.
- Implement hooks actions (`init_session`, `execute_response_code`, `check_final`).
- Validate strict final behavior.

### Phase C — Recursive subcalls
- Implement `llm_query` recursion invoker with depth + timeout + thread bridge.
- Validate depth caps and timeout sentinel behavior.

### Phase D — Reliability & docs
- Add retry/error paths and structured logging.
- Document known limitations and model-routing fallback behavior.

### Phase E — Smoke validation
- Run demo and verify invariants.

---

## 16) Validation checklist

1. Root coder input excludes full `long_context`.
2. REPL persistence works across iterations.
3. `Final=0` and `Final=False` terminate correctly.
4. `llm_query` launches recursive machine call.
5. `max_depth=5` enforced.
6. `timeout_seconds=300` enforced (sentinel output on timeout).
7. `history_meta` bounded to last 5 entries.
8. Explicit `max_steps` is passed from caller.
9. Terminal outputs are structured and reasoned (`final`/`max_iterations`/`error`).

---

## 17) Open flagged questions

1. Paper-level canonical subcall semantics: strict sub-RLM vs sub-LM behavior in reported experiments.
2. Exact paper footnote details for metadata shape/size.
3. Dynamic per-subcall model override support limits in current adapter stack.

These remain documented as non-blocking uncertainties for the example.
