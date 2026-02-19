# PLAN_REV2 — `sdk/examples/rlm_v2/python`

Standalone revision plan incorporating REV1 review feedback.

---

## 0) What changed from REV1

This revision explicitly fixes:
1. **Critical invariant fix**: separates `task` from `long_context` (no task+context concatenation into root LM input).
2. Adds concrete retry/error/max-steps behavior to machine sketch.
3. Corrects strict-final semantics to allow valid falsy answers (`0`, `False`).
4. Clarifies timeout/thread behavior and known limitation.
5. Uses a demo that actually encourages recursive semantic subcalls.
6. Makes agent output contract explicit and verified.

---

## 1) Locked decisions

1. Build in `sdk/examples/rlm_v2/python` (adjacent to v1).
2. Keep architecture minimal (single core machine loop).
3. `llm_query()` should recurse by launching the same machine.
4. **Termination now: strict REPL variable `Final` only**.
5. Parameterize limits end-to-end:
   - `max_depth` default `5`
   - `timeout_seconds` default `300`
   - `max_iterations` configurable
6. Subcall policy ambiguity (paper vs public repo behavior) remains flagged.

---

## 2) Core invariants (must hold)

1. **Long context never sent directly to root LM**.
2. Root LM receives only compact metadata + bounded execution history metadata.
3. REPL state persists across iterations.
4. `llm_query()` is callable from executed code and performs recursive machine invocation.
5. Run terminates only when REPL namespace contains key `Final` with value `is not None`.

---

## 3) Input / context contract

### 3.1 Machine input
- `task: str` — user question/instruction (short)
- `long_context: str` — large input payload (stored in REPL `context` variable)

Optional controls:
- `current_depth: int = 0`
- `max_depth: int = 5`
- `timeout_seconds: int = 300`
- `max_iterations: int = 20`
- `machine_config_path: str` (absolute or resolvable path)
- `sub_model_profile: str | null`
- `model_override: str | null`

### 3.2 Context fields (machine)
- `task`, `long_context`
- `context_length`, `context_prefix`
- `session_id`
- `iteration`, `max_iterations`
- `current_depth`, `max_depth`
- `timeout_seconds`
- `machine_config_path`
- `sub_model_profile`, `model_override`
- `raw_response`
- `last_exec_metadata` (dict)
- `history_meta` (bounded list)
- `best_partial` (str | null)
- `final_answer` (any serializable)
- `is_final` (bool)

---

## 4) Recursive machine behavior

## 4.1 State flow
1. `start` (initial)
   - action `init_session`
   - create persistent REPL session and load `long_context` into REPL var `context`
   - compute metadata (`context_length`, small prefix)
2. `generate_code`
   - call `coder` agent with `task + metadata + history_meta`
3. `execute_code`
   - parse and execute all ```repl blocks from response
   - update REPL state and append bounded execution metadata
4. `check_final`
   - strict final check on REPL variable `Final`
5. transition:
   - if final -> `done`
   - else if iteration cap reached -> `max_iter_done`
   - else loop to `generate_code`

Fallback:
- `error_done` for unhandled failures.

## 4.2 Pseudo-YAML sketch

```yaml
spec: flatmachine
spec_version: "1.0.0"

data:
  name: rlm-v2
  profiles: ./profiles.yml

  context:
    task: "{{ input.task }}"
    long_context: "{{ input.long_context | default('') }}"

    current_depth: "{{ input.current_depth | default(0) }}"
    max_depth: "{{ input.max_depth | default(5) }}"
    timeout_seconds: "{{ input.timeout_seconds | default(300) }}"
    max_iterations: "{{ input.max_iterations | default(20) }}"

    machine_config_path: "{{ input.machine_config_path }}"
    sub_model_profile: "{{ input.sub_model_profile | default(null) }}"
    model_override: "{{ input.model_override | default(null) }}"

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

  # Machine-level default error routing
  on_error: error_done

  states:
    start:
      type: initial
      action: init_session
      on_error: error_done
      transitions:
        - to: generate_code

    generate_code:
      agent: coder
      execution:
        type: retry
        backoffs: [2, 8, 16]
        jitter: 0.1
      input:
        task: "{{ context.task }}"
        context_length: "{{ context.context_length }}"
        context_prefix: "{{ context.context_prefix }}"
        depth: "{{ context.current_depth }}"
        max_depth: "{{ context.max_depth }}"
        iteration: "{{ context.iteration }}"
        history_meta: "{{ context.history_meta }}"
      output_to_context:
        raw_response: "{{ output.content }}"
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
        answer: "{{ context.final_answer }}"
        reason: "final"
        iteration: "{{ context.iteration }}"
        depth: "{{ context.current_depth }}"

    max_iter_done:
      type: final
      output:
        answer: "{{ context.best_partial | default('No Final variable set') }}"
        reason: "max_iterations"
        iteration: "{{ context.iteration }}"
        depth: "{{ context.current_depth }}"

    error_done:
      type: final
      output:
        answer: "{{ context.best_partial | default('Execution error before Final') }}"
        reason: "error"
        iteration: "{{ context.iteration }}"
        depth: "{{ context.current_depth }}"
        error: "{{ context.last_error }}"

  settings:
    max_steps: 80

  hooks:
    file: "../python/src/rlm_v2/hooks.py"
    class: "RLMV2Hooks"
```

---

## 5) Coder agent contract (`coder.yml`)

Single agent prompt requirements:
- Use REPL code blocks to inspect/process `context`.
- Use `llm_query()` for semantic decomposition when useful.
- Keep intermediate state in variables.
- **When finished, set REPL variable `Final = ...` in code.**
- Do not use FINAL tags in plain text.
- Only bounded execution metadata is fed back each turn.

### Output contract
- Primary assumption: FlatAgent returns freeform text as `output.content` (same pattern as v1).
- Add a startup smoke assertion in `main.py` (or first run check in hooks) to confirm this contract.
- If contract differs, fallback plan: add tiny extractor agent in-loop (deferred unless needed).

---

## 6) REPL + hooks runtime design

### 6.1 Persistent REPL session
`repl.py` provides:
- persistent globals/locals per `session_id`
- injected functions:
  - `llm_query(prompt, model=None)`
  - optional helper introspection (e.g., variable listing)

### 6.2 Hook actions
- `init_session`
  - create session if absent
  - load `long_context` into REPL var `context`
  - compute `context_length`, `context_prefix`
- `execute_response_code`
  - parse ```repl blocks
  - execute sequentially
  - increment `iteration`
  - build compact metadata and append into bounded `history_meta`
  - update `best_partial` heuristically
- `check_final`
  - use strict strategy to inspect REPL locals for key `Final`

---

## 7) `llm_query()` recursive invocation (concrete)

## 7.1 Invocation rule
Inside REPL code, `llm_query(sub_prompt, model=None)` performs recursive call to same machine.

## 7.2 Sub-input mapping
When called from depth `d`:
- if `d + 1 > max_depth`: return deterministic depth-limit string
- else invoke same machine with:
  - `task = "Answer the request encoded in REPL variable context. Set Final when complete."`
  - `long_context = sub_prompt`
  - `current_depth = d + 1`
  - inherited `max_depth`, `timeout_seconds`, `max_iterations`, `machine_config_path`
  - `sub_model_profile` / model routing fields

This preserves the invariant: sub-prompt payload is treated as environment context, not directly injected into root LM history.

## 7.3 Sync timeout mechanism
- Use `ThreadPoolExecutor(max_workers=1)` and `future.result(timeout=timeout_seconds)`.
- On timeout: return `"SUBCALL_TIMEOUT"` (or equivalent fixed token).

### Known limitation
Python thread timeout does not forcibly terminate running work; timed-out subcall thread may continue in background briefly. Document this in README as v2 limitation.

---

## 8) History metadata policy (bounded)

Keep only compact metadata entries, last `N=5`:
- `iteration`
- `code_prefix` (<= 240 chars)
- `stdout_prefix` (<= 240 chars)
- `stdout_length`
- `stderr_prefix` (<= 120 chars)
- `had_error`
- `changed_vars` (<= 10 names)

No raw long stdout history sent back to agent.

---

## 9) Strict final strategy (corrected)

`StrictFinalStrategy`:
- `is_final == True` iff REPL locals contain key `Final` and `Final is not None`.
- Valid answers include falsy values (`0`, `False`, `""` if intentionally set).

(Empty string handling can be revisited later; for strictness now, key existence + non-None is authoritative.)

---

## 10) Model routing policy for `llm_query(model=None)`

- `model=None`: use configured `sub_model_profile` if provided; else inherit root profile.
- `model` specified: attempt override via recursive input `model_override`.
- If runtime cannot honor dynamic override, fall back to sub profile and record warning in metadata.

---

## 11) Reliability and error handling

- `generate_code` uses retry with backoff+jitter.
- Machine has `on_error: error_done` fallback.
- `settings.max_steps` set (80 in sketch).
- No-code-block response => no-op metadata, continue loop.
- REPL exceptions become metadata (`had_error=true`) and loop continues unless fatal hook exception occurs.

`max_iter_done` output contract:
- `answer`: `best_partial` or fallback text
- `reason`: `max_iterations`
- `iteration`, `depth`

---

## 12) Demo / validation

## 12.1 Demo task (recursion-friendly)
Use a long multi-chapter document and task like:
- “For each chapter, extract the main claim, then synthesize a single thesis with chapter-level evidence.”

This encourages semantic sub-analysis and is less solvable by trivial string operations.

## 12.2 Validation checklist
1. Long context not sent to coder input.
2. REPL state persists across iterations.
3. `Final` variable ends run.
4. `llm_query` triggers recursive machine calls.
5. Depth caps at 5.
6. Timeout behavior enforced at 300s.
7. History metadata remains bounded (`N=5`).
8. `max_iter_done` and `error_done` outputs are structured and informative.

---

## 13) Implementation phases

### Phase A — Skeleton
- Create config/python structure
- Implement machine + coder + profiles
- Wire CLI args and input plumbing (`task`, `long_context`, limits)

### Phase B — Core loop
- Implement REPL session and hooks actions
- Strict final strategy
- Bounded metadata history

### Phase C — Recursive llm_query
- Implement recursion invoker with depth checks and timeout wrapper
- Add model routing behavior and warnings

### Phase D — Hardening + docs
- Add retry/error state behavior
- README with known limitations (thread timeout semantics, open subcall ambiguity)
- Add demo mode

### Phase E — Smoke verification
- Run demo and verify checklist

---

## 14) Open flagged questions (non-blocking)

1. Canonical paper semantics for subcall (strict sub-RLM vs practical sub-LM behavior).
2. Exact paper footnote metadata format details (prefix length, etc.).
3. Dynamic per-subcall model override capabilities in FlatAgent runtime.
