# PLAN_REV1 — `sdk/examples/rlm_v2/python`

A fresh, standalone implementation plan for a stripped-down RLM v2 that is closer to Algorithm 1 while still using FlatMachine orchestration.

---

## 0) Decisions locked from user

1. Build under `sdk/examples/rlm_v2/python` (adjacent to v1 example).
2. Keep architecture minimal.
3. `llm_query()` should recurse by launching the same machine (machine-orchestrated recursion).
4. **Termination is strict REPL variable `Final`** (no FINAL/FINAL_VAR tag parsing in v2).
5. Parameterize runtime limits end-to-end:
   - `max_depth` default `5`
   - `timeout_seconds` default `300`
   - `max_iterations` configurable
6. Subcall semantics ambiguity (sub-RLM vs sub-LM in paper/repo) remains flagged.

---

## 1) Design goals

- Faithful core loop to Algorithm 1:
  - persistent REPL state
  - root LM gets metadata, emits code
  - execute code in REPL
  - append bounded metadata from execution to history
  - stop when `state[Final]` is set
- Minimal moving parts:
  - one machine
  - one primary coder agent
  - one hooks class
- Keep recursion robust and explicit via `llm_query()`.

---

## 2) High-level architecture

### 2.1 Single recursive machine
A single FlatMachine config (`machine.yml`) handles both root and sub-invocations. Sub-invocations are created programmatically inside `llm_query()` via hooks.

### 2.2 Persistent REPL session per execution
Hooks maintain a per-execution REPL session object in memory, keyed by `session_id` (stored in context). Session persists across loop iterations and stores variables.

### 2.3 Blocking subcalls
`llm_query()` is synchronous/blocking (matches paper’s reported baseline behavior). Internally, submachine execution runs in a worker thread with timeout guard.

---

## 3) File layout

```text
sdk/examples/rlm_v2/
├── PLAN_REV1.md
├── REVIEW.md
├── RLM_DIGEST.md
├── config/
│   ├── machine.yml
│   ├── coder.yml
│   └── profiles.yml
└── python/
    ├── README.md
    ├── run.sh
    ├── pyproject.toml
    └── src/rlm_v2/
        ├── __init__.py
        ├── main.py
        ├── hooks.py
        └── repl.py
```

---

## 4) Machine contract and context schema

### 4.1 Input contract (minimal)
To simplify recursion, the machine accepts a single `prompt` payload string.

Top-level CLI wrapper can build this prompt from `task + context` for user ergonomics.

Required machine input:
- `prompt: str`

Optional:
- `max_depth: int` (default 5)
- `timeout_seconds: int` (default 300)
- `max_iterations: int` (default 20)
- `current_depth: int` (default 0)
- `machine_config_path: str` (explicit path for recursive self-instantiation)
- `sub_model_profile: str | null` (explicit subcall profile)

### 4.2 Context fields (explicit)
- `prompt`
- `session_id`
- `iteration` (int)
- `max_iterations`
- `current_depth`
- `max_depth`
- `timeout_seconds`
- `machine_config_path`
- `sub_model_profile`
- `raw_response`
- `last_exec_metadata` (dict)
- `history_meta` (list[dict])
- `best_partial` (str | null)
- `final_answer` (str | null)
- `is_final` (bool)

---

## 5) Machine state flow (Algorithm-1-shaped)

1. `start` (initial)
   - action: `init_session`
   - initializes REPL session with `context = prompt`

2. `generate_code`
   - agent: `coder`
   - input includes prompt metadata + compact `history_meta`
   - output: `raw_response`

3. `execute_code`
   - action: `execute_response_code`
   - parse and execute all ```repl blocks in `raw_response`
   - update REPL state
   - produce bounded execution metadata
   - increment `iteration`

4. `check_final`
   - action: `check_final`
   - strict check of REPL variable `Final`
   - if set, map to `final_answer`
   - optionally update `best_partial`

5. transitions
   - if `is_final == true` -> `done`
   - else if `iteration >= max_iterations` -> `max_iter_done`
   - else -> `generate_code`

6. `done` (final)
   - returns answer + run metadata

7. `max_iter_done` (final)
   - returns partial output with explicit reason

### 5.1 Pseudo-YAML sketch

```yaml
states:
  start:
    type: initial
    action: init_session
    transitions: [{to: generate_code}]

  generate_code:
    agent: coder
    input:
      prompt: "{{ context.prompt }}"
      depth: "{{ context.current_depth }}"
      max_depth: "{{ context.max_depth }}"
      iteration: "{{ context.iteration }}"
      history_meta: "{{ context.history_meta }}"
    output_to_context:
      raw_response: "{{ output.content }}"
    transitions: [{to: execute_code}]

  execute_code:
    action: execute_response_code
    transitions: [{to: check_final}]

  check_final:
    action: check_final
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
```

---

## 6) Agent prompt strategy (`coder.yml`)

Single agent (`coder`) with explicit instructions:
- Use only ```repl blocks for actions.
- Inspect and transform REPL variable `context`.
- Use `llm_query()` for sub-analysis when needed.
- Maintain intermediate buffers in REPL variables.
- **Completion rule:** when done, set `Final = <answer>` inside REPL code.
- Do not emit FINAL tags in plain text.

Prompt input includes bounded history metadata (not raw large stdout).

---

## 7) `llm_query()` recursion mechanism (concrete sketch)

### 7.1 Where config path comes from
`machine_config_path` is passed from `main.py` input and stored in context during `start`. Hooks use this for recursive instantiation (no hardcoded relative magic).

### 7.2 Execution model
Inside REPL, `llm_query(prompt, model=None)` calls a hook-owned `RecursionInvoker`:

1. Check depth: if `current_depth + 1 > max_depth`, return depth-limit message.
2. Build sub-input:
   - `prompt = prompt`
   - `current_depth = parent_depth + 1`
   - inherit `max_depth`, `timeout_seconds`, `max_iterations`
   - inherit `machine_config_path`
   - set `sub_model_profile` resolution field if applicable
3. Instantiate `FlatMachine(config_file=machine_config_path)`.
4. Run `machine.execute(input=sub_input)` in a worker thread.
5. Block until completion or timeout.
6. Return submachine `answer` string to REPL caller.

### 7.3 Timeout strategy
- Use `concurrent.futures.ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)`.
- On timeout: return deterministic timeout string (e.g., `"SUBCALL_TIMEOUT"`).
- This avoids nested event loop issues in the same thread.

---

## 8) History and metadata policy (concrete)

To prevent root-history bloat:
- Maintain `history_meta` list of compact entries only.
- Keep last `N=5` entries.
- Per entry fields:
  - `iteration`
  - `code_prefix` (<= 240 chars)
  - `stdout_prefix` (<= 240 chars)
  - `stdout_length` (int)
  - `stderr_prefix` (<= 120 chars)
  - `had_error` (bool)
  - `changed_vars` (<= 10 names)

No raw full stdout added to context history.

---

## 9) Strict termination abstraction (swappable later)

Implement in hooks:
- `TerminationStrategy` protocol
- `StrictFinalStrategy` now:
  - final iff REPL locals contain key `Final` with non-empty value

Machine actions call strategy object. Future tag-based strategy can be dropped in without state-flow changes.

---

## 10) Model routing policy (`llm_query(prompt, model=None)`)

v2 explicit behavior:
- `model is None`:
  - use `sub_model_profile` if provided; else use same profile as root.
- `model is not None`:
  - attempt override via recursive input field `model_override`.
  - if dynamic model override is unsupported by FlatAgent config templating, fallback to sub profile and log note in metadata.

(Implementation note: confirm model templating support in flatagent config; otherwise defer full override with clear warning.)

---

## 11) Error and cap behavior

- No code blocks in LM response:
  - record no-op metadata; continue (iteration still increments).
- REPL runtime exception:
  - capture `stderr_prefix`, set `had_error=true`, continue loop.
- Max iterations reached:
  - final output includes
    - `reason: max_iterations`
    - `answer: best_partial or fallback string`
    - `iteration`, `depth`

`best_partial` policy:
- if REPL has variable names like `answer`, `final_answer`, or last non-empty stdout, store a short candidate.

---

## 12) Demo and validation plan

### 12.1 Demo scenario (concrete)
- Input: long synthetic text (e.g., repeated sections totaling large char count)
- Task: “Count total mentions of term X and return the integer.”
- Expected behavior:
  - model uses chunking logic and possibly `llm_query`
  - sets `Final`

### 12.2 Validation checklist
1. REPL variables persist across loop iterations.
2. Setting REPL `Final` terminates immediately.
3. `llm_query` launches recursive machine call.
4. Depth increments correctly and caps at `max_depth=5`.
5. Subcall timeout enforced at `300s`.
6. `history_meta` stays bounded (`N=5`).
7. `max_iter_done` emits structured cap reason and partial answer.

---

## 13) Implementation phases

### Phase A: Skeleton
- create folder structure and boilerplate files
- add `profiles.yml`, minimal `coder.yml`, `machine.yml` with loop states

### Phase B: Runtime core
- implement `repl.py` persistent session
- implement hooks actions: `init_session`, `execute_response_code`, `check_final`

### Phase C: Recursive subcalls
- implement `RecursionInvoker` + `llm_query`
- thread timeout wrapper
- depth/cap propagation

### Phase D: CLI + docs
- `main.py` and `run.sh`
- README usage and caveats

### Phase E: Smoke verification
- run demo
- verify output contract and caps

---

## 14) Known open questions (kept flagged)

1. Paper-level canonical semantics of subcall (`sub_RLM` vs practical sub-LM behavior).
2. Exact stdout metadata format from paper footnote/appendix details.
3. Dynamic per-call model override feasibility in FlatAgent config.

These do not block v2 build but should be documented in README.
