 Perfect — using IMPL_REVIEW_1.md as north star, here’s a dead-minimal patch
 plan with size estimates and concrete code examples against current files.

 Target patch budget

 - Code: ~40–65 LOC net
 - Tests: ~20–35 LOC
 - Files touched: 4–5 existing files
 (repl.py, coder.yml, machine.yml, hooks.py, tests)

 ─────────────────────────────────────────────────────────────────────────────

 1) Safe builtins fix (required)

 File: sdk/examples/rlm_v2/python/src/rlm_v2/repl.py
 Size: ~4 LOC (3 add, 1 remove)
 Why: Removes first-iteration waste (dir NameError) and hardens sandbox.

 ### Patch sketch

 ```python
   _SAFE_BUILTINS = {
       ...
       "repr": repr,
       "isinstance": isinstance,
       "type": type,
       "dir": dir,
       "hasattr": hasattr,
       "getattr": getattr,
       ...
       # "__import__": __import__,   # remove this line
   }
 ```

 ─────────────────────────────────────────────────────────────────────────────

 2) Anti-loop prompt guidance (required for your goal)

 File: sdk/examples/rlm_v2/config/coder.yml
 Size: ~2–4 lines
 Why: Cheap behavior shaping; avoids repeated full-context prints.

 ### Patch sketch (in system: rules)

 ```yaml
   7. Do not repeatedly print the full `context`.
   8. After one structural inspection, switch to targeted
 slices/search/chunking,
      and use llm_query for semantic sub-analysis when repetitive outputs
 appear.
 ```

 ─────────────────────────────────────────────────────────────────────────────

 3) Minimal anti-loop detection signal (required for your goal)

 Files:
 - sdk/examples/rlm_v2/python/src/rlm_v2/hooks.py
 - sdk/examples/rlm_v2/config/machine.yml
 - sdk/examples/rlm_v2/config/coder.yml
 Size: ~20–35 LOC total
 Why: Gives model a concrete nudge when stuck, without architectural
 expansion.

 ### 3a) Add tiny loop state in machine context

 machine.yml (context defaults)

 ```yaml
   last_code_fingerprint: ""
   repeat_streak: 0
   loop_hint: ""
 ```

 ### 3b) Compute repeat streak in hooks after code execution

 hooks.py (_execute_response_code near meta_entry update)

 ```python
   normalized = " ".join(code_prefix_source.split())
   current_fp = str(hash(normalized))
   last_fp = str(context.get("last_code_fingerprint") or "")
   streak = self._coerce_int(context.get("repeat_streak"), 0, min_value=0)

   if current_fp == last_fp and normalized:
       streak += 1
   else:
       streak = 0

   context["last_code_fingerprint"] = current_fp
   context["repeat_streak"] = streak

   if streak >= 2:
       context["loop_hint"] = (
           "You are repeating near-identical REPL actions. "
           "Do not print full context again; switch strategy and use targeted
 chunking/llm_query."
       )
   else:
       context["loop_hint"] = ""
 ```

 ### 3c) Pass loop hint into agent input

 machine.yml (generate_code.input)

 ```yaml
   loop_hint: context.loop_hint
   repeat_streak: context.repeat_streak
 ```

 ### 3d) Surface hint in prompt

 coder.yml (user:)

 ```jinja2
   {% if input.loop_hint %}
   Loop hint: {{ input.loop_hint }} (repeat_streak={{ input.repeat_streak }})
   {% endif %}
 ```

 ─────────────────────────────────────────────────────────────────────────────

 4) Tests (small, focused)

 Size: ~20–35 LOC across existing tests
 Goal: Prevent regressions on the exact issues.

 ### Suggested assertions

 1. repl.py builtins includes dir, hasattr, getattr, excludes __import__.
 2. loop detector sets loop_hint after repeated same-code turns.
 3. loop hint is propagated into generate_code input payload.

 ─────────────────────────────────────────────────────────────────────────────

 Implementation shape (single small PR)

 1. repl.py builtins change
 2. coder.yml anti-loop sentence
 3. machine.yml + hooks.py loop signal
 4. add/adjust 2–3 tests
 5. run ./test.sh --local

