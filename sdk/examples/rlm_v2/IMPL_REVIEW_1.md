
 Implementation Review — RLM v2

 19 tests pass. Demo runs end-to-end. The five PLAN_REV3 invariants hold in code and tests. The core loop is paper-aligned.

 Below is what needs to change, what's desirable but optional, and what's clutter.

 ────────────────────────────────────────────────────────────────────────────────

 ### Needed

 1. Add dir to _SAFE_BUILTINS in repl.py.

 The demo trace shows the model hit NameError: name 'dir' is not defined on iteration 1. Models reach for dir() constantly when exploring a REPL. Also add
 hasattr, getattr. These are safe, standard, and their absence causes wasted iterations. Three lines.

 2. __import__ must be removed from _SAFE_BUILTINS.

 It's in there now. This allows import os; os.system(...) from model-generated code, which negates the sandbox. One line to delete.

 ────────────────────────────────────────────────────────────────────────────────

 ### Desirable

 3. Coder prompt should say "do not repeatedly print the full context."

 The demo trace shows iterations 2–5 all run print(context) identically. The model loops because it keeps seeing the same bounded stdout metadata and doesn't
 know what else to do. One sentence in coder.yml system prompt. PROBLEMS1.md flags this and the recommendation (anti-loop guidance) is correct and cheap.

 4. PROBLEMS1.md recommends a "nudge after no-subcall iterations" and "loop-detection hint."

 These are prompt engineering improvements, not architecture changes. Desirable for demo quality but not needed for correctness. Could be a follow-up.

 ────────────────────────────────────────────────────────────────────────────────

 ### Observations on Scope

 The implementation exceeds PLAN_REV3 §13 significantly. The plan asked for structured logging. What was built:

 - trace.py (119 lines) — JSONL recorder, manifest writer, file locks
 - 11 context fields not in the plan (inspect, inspect_level, trace_dir, root_run_id, parent_call_id, print_iterations, experiment, tags, history_meta_text)
 - ~250 lines of trace instrumentation woven through hooks.py
 - CLI flags: --inspect, --inspect-level, --trace-dir, --experiment, --tag
 - run.sh defaults to full trace mode

 This is well-built and the test coverage is good (integration tests verify trace output). It's useful for research iteration. But it roughly doubled the code
 surface. The question is whether this example prioritizes being a minimal reference implementation (per the plan's "keep architecture simple" goal) or a
 research-ready tool. If the former, the trace layer could be extracted or simplified later. Not a blocker — just noting the tradeoff.

 PROBLEMS1.md correctly categorizes all the trace/inspect infrastructure as "our custom engineering layer, not from paper implementation." The sentinels and
 final-variable strategy are correctly tagged as paper-aligned.

 ────────────────────────────────────────────────────────────────────────────────

 ### Summary

 ┌───┬────────────────────────────────────────────┬───────────┬────────────────────┐
 │ # │ Change                                     │ Type      │ Size               │
 ├───┼────────────────────────────────────────────┼───────────┼────────────────────┤
 │ 1 │ Add dir, hasattr, getattr to safe builtins │ Needed    │ 3 lines            │
 ├───┼────────────────────────────────────────────┼───────────┼────────────────────┤
 │ 2 │ Remove __import__ from safe builtins       │ Needed    │ 1 line             │
 ├───┼────────────────────────────────────────────┼───────────┼────────────────────┤
 │ 3 │ Anti-loop prompt guidance in coder.yml     │ Desirable │ 1–2 sentences      │
 ├───┼────────────────────────────────────────────┼───────────┼────────────────────┤
 │ 4 │ Subcall nudge / loop detection             │ Desirable │ Future prompt work │
 └───┴────────────────────────────────────────────┴───────────┴────────────────────┘


