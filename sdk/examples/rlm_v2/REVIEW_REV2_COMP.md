 # PLAN_REV2 vs. Python SDK Alignment

 ### ✅ Strong alignment (used correctly)

 1. Machine YAML envelope — spec: flatmachine, spec_version: "1.0.0", data: with context:, agents:, states:, settings: all match the SDK's _validate_spec()
 and _parse_machine_config() exactly.
 2. Hooks pattern — hooks: { file: "...", class: "RLMV2Hooks" } matches _load_hooks_local(). The MachineHooks base class with on_action() dispatch is
 idiomatic — same pattern as v1's RLMHooks.
 3. Retry execution — execution: { type: retry, backoffs: [2, 8, 16], jitter: 0.1 } maps exactly to RetryExecution.from_config().
 4. Machine-level on_error: error_done — Correctly handled by _get_error_recovery_state() which checks state-level first, then falls back to machine-level
 on_error.
 5. Agent output mapping — output_to_context: { raw_response: "{{ output.content }}" } is correct. The FlatAgentExecutor returns AgentResult(content=...,
 output=...), and output_payload() returns {"content": content} when output is None. This path works.
 6. Transition conditions — condition: "context.is_final == true" works because the simple expression engine (SimpleExpressionEngine) recognizes true/True as
 boolean via ast.Name handling. context.iteration >= context.max_iterations works as long as hooks set them as integers (which the plan correctly does via
 Python code in hooks).
 7. Final state output rendering — type: final with output: dict gets rendered via _render_dict() in _execute_state(). Correct.
 8. Profiles reference — profiles: ./profiles.yml is discovered by discover_profiles_file() in the adapter.

 ────────────────────────────────────────────────────────────────────────────────

 ### ⚠️ Concrete bugs / gaps

 1. null is not valid Jinja2 — use none

 The plan has:

 ```yaml
   sub_model_profile: "{{ input.sub_model_profile | default(null) }}"
   model_override: "{{ input.model_override | default(null) }}"
 ```

 Jinja2 uses none, not null. This would raise an UndefinedError at render time. Should be default(none).

 2. settings.max_steps is NOT automatically honored

 The plan puts settings: { max_steps: 80 } in YAML. But FlatMachine.execute() defaults to max_steps=1000 as a parameter, and neither the SDK nor run.py reads
 settings.max_steps from config. The v1 example has the same field but it's also not auto-read. The plan's main.py must explicitly wire:

 ```python
   max_steps = machine.settings.get("max_steps", 80)
   result = await machine.execute(input=input_data, max_steps=max_steps)
 ```

 3. Jinja2 renders initial context values as strings, not native types

 ```yaml
   current_depth: "{{ input.current_depth | default(0) }}"
   max_iterations: "{{ input.max_iterations | default(20) }}"
 ```

 These render as strings "0" and "20" because _render_template() goes through Jinja (returns strings). The plan mitigates this by having hooks overwrite these
 with proper Python ints before conditions are evaluated. This works but is fragile — if any code path skips hooks and evaluates conditions against the raw
 Jinja-rendered context, comparisons like context.iteration >= context.max_iterations would compare int >= str and fail. Worth noting.

 ────────────────────────────────────────────────────────────────────────────────

 ### 🔶 Biggest design challenge: Recursive llm_query()

 This is PLAN_REV2's most ambitious feature and the SDK has no built-in support for it, but the public API makes it feasible:

 - What the plan needs: A Python function callable inside the REPL that creates a new FlatMachine from the same config and blocks until it completes.
 - What the SDK offers: FlatMachine(config_file=...).execute_sync(input=...) exists and wraps asyncio.run(). This is exactly what a blocking REPL call needs.
 - The gap: The hooks need to inject this function into the REPL, which means hooks need access to machine_config_path (stored in context ✅) and must
 instantiate a new FlatMachine manually. The plan correctly designs for this in §7 but doesn't show the actual FlatMachine import/construction code. It's
 doable but is the most DIY part.
 - Async caveat: execute_sync() calls asyncio.run(), which can't be called from within an already-running event loop. The plan's ThreadPoolExecutor approach
 (§7.3) correctly solves this by running the sync call in a separate thread.

 ────────────────────────────────────────────────────────────────────────────────

 ### 📊 Summary scorecard

 ┌──────────────────────────────┬────────┬─────────────────────────────────────────────────────────────────────────────┐
 │ Aspect                       │ Rating │ Notes                                                                       │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ YAML schema correctness      │ 9/10   │ null → none is the only bug                                                 │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Hooks/actions pattern        │ 10/10  │ Idiomatic, matches v1 exactly                                               │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Agent I/O contract           │ 9/10   │ Correct; smoke assertion idea is smart                                      │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ State flow/transitions       │ 10/10  │ Clean loop with proper final states                                         │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Error handling               │ 10/10  │ Machine-level + state-level, matches SDK                                    │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Retry execution              │ 10/10  │ Exact match to RetryExecution                                               │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Recursive invocation         │ 7/10   │ Feasible via public API but needs careful async/thread bridging; not native │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ settings.max_steps           │ 5/10   │ Specified but not auto-honored; needs caller wiring                         │
 ├──────────────────────────────┼────────┼─────────────────────────────────────────────────────────────────────────────┤
 │ Type safety (Jinja → Python) │ 7/10   │ Works via hooks overwriting, but initial context values are strings         │
 └──────────────────────────────┴────────┴─────────────────────────────────────────────────────────────────────────────┘

 Overall: PLAN_REV2 uses the SDK well. The YAML is nearly correct, hooks are idiomatic, and the design follows the v1 precedent. The three actionable fixes
 are: null → none in Jinja, wire max_steps in the caller, and be explicit about FlatMachine instantiation inside the llm_query() REPL function.


 Also review ~/code/flatagents/docs/BEST_PRACTICES.md

 # FlatAgents / FlatMachines Best Practices (v2)

 ## 1) Checkpoint/Restore as the Job Engine (not a separate scheduler layer)

 ### Core rule
 - Treat **machine checkpoint state** as the job state.
 - Avoid duplicating truth in an external job engine unless you truly need multi-tenant orchestration.

 ### Why this worked
 - Cancel/restart safety comes from checkpoint + resume, not worker heartbeats.
 ... (194 more lines, ctrl+o to expand)


 Now let me cross-reference the BEST_PRACTICES.md against PLAN_REV2.md to see where the plan aligns or conflicts with these established best practices.

 Key best practices to check against PLAN_REV2:

 1. Checkpoint/Restore as Job Engine — Plan uses persistence: { enabled: true, backend: local } which is the file-based approach. Best practices recommend
 DB-backed (SQLite) for high concurrency. For a single-execution example, file-based is fine, but if recursive subcalls create many concurrent machines, this
 could be an issue.
 2. LLM Handoff Simplicity — This is a BIG one.

 The best practices explicitly say "avoid JSON/Jinja between model stages" and "pass plain text/markdown payloads between LLM stages." The plan's coder agent
 returns freeform text with simple text pass-through via output_to_context, which aligns well with this guidance.

 3. Depth-first completion — The plan's resume-first policy and loop-until-Final approach matches the DFS completion philosophy.
 4. Locks — The plan doesn't specify locks, so it defaults to LocalFileLock when using file-based persistence, which is acceptable for this simple example but
 could become a bottleneck under concurrent load.
 5. Data Flow Quality — The plan stores the full paper text in a REPL variable and passes only metadata to the LLM, allowing programmatic access to the
 complete text without bloating the prompt—this correctly implements the RLM pattern.
 6. Machine I/O mappings — The input: and output_to_context: mappings are straightforward and explicit, keeping the data flow transparent.
 7. Error handling — The plan routes errors to a final state via on_error: error_done, which is appropriate for this example.
 8. Concurrency — The plan uses thread-based execution...

 Now I'm checking the plan against the best practices more systematically. It aligns well with plain text between LLM stages, explicit I/O mappings, and error
 routing to recovery states. The main gaps are around persistence strategy—the plan uses file-based checkpoints which works for examples but doesn't address
 the DB-backed approach recommended for high concurrency, and there's no discussion of checkpoint pruning for recursive subcalls or file descriptor pressure.

 Good call — there's meaningful overlap. Here's how PLAN_REV2 stacks up against the best practices:

 ────────────────────────────────────────────────────────────────────────────────

 BEST_PRACTICES.md cross-check against PLAN_REV2

 ### ✅ Strong alignment

 §2 — LLM Handoff Simplicity ("avoid JSON/Jinja between model stages")

 This is arguably the most important best practice, and PLAN_REV2 follows it well:
 - The coder agent returns freeform text (output.content), not structured JSON.
 - output_to_context: { raw_response: "{{ output.content }}" } is a single shallow mapping — plain text pass-through.
 - The plan explicitly says "FlatAgent returns freeform text" and treats it as the primary contract.
 - No intermediate JSON parsing, schema extraction, or Jinja transformations between model stages.
 - The REPL code blocks are extracted by hooks (Python string parsing), not by another LLM.

 This is textbook compliant with: "Pass plain text/markdown payloads between LLM stages. Keep context mappings explicit and shallow."

 §2 — "Every transformation must justify itself in one line"

 The plan's transformations are minimal and justified:
 - raw_response → parse code blocks → execute in REPL (core RLM loop)
 - REPL state → bounded history_meta (prevent context blowup)
 - Final variable → final_answer (termination signal)

 No gratuitous extraction agents in the loop (unlike v1 which has findings_extractor, subquery_extractor, answer_extractor as separate agent stages with
 structured output parsing between them).

 §Data Flow Quality — "Pass full source text end-to-end"

 The plan stores long_context in the REPL variable context, making the full text programmatically accessible at every iteration without ever truncating it.
 The LLM can slice, index, or query any part via code. This is stronger than v1's chunk-based approach and aligns with "Preserve full source text through
 expensive stages."

 §Architecture — "Machine state as job source of truth"

 The plan keeps all execution state in context.* — iteration count, history_meta, best_partial, final_answer, REPL variable state. No external job tables or
 separate scheduler.

 §Keep It Simple

 Single machine with a tight loop (5 states). Compare to v1's 12 states + a peer machine + 7 agents. The plan is dramatically simpler.

 ────────────────────────────────────────────────────────────────────────────────

 ### ⚠️ Gaps / things the plan should address

 §1 — Checkpoint/Persistence strategy is underspecified

 The plan's YAML sketch doesn't include a persistence: block at all. The best practices strongly advocate for treating checkpoint state as the job engine. For
 a single-execution example persistence: { enabled: true, backend: memory } is fine, but the plan should be explicit, especially because:

 - Recursive subcalls each create a new FlatMachine. If backend: local, each subcall writes file checkpoints + acquires LocalFileLock. At depth 5 with
 iterations, this creates checkpoint file proliferation.
 - Best practices say: "DB-backed checkpoint persistence (not file temp checkpoints) for high concurrency" and "DB lease locks (not file .locks) to avoid FD
 churn."
 - For an example this isn't critical, but the plan's §7 (recursive llm_query()) creates a mini-concurrency problem. Worth a one-liner noting persistence: {
 enabled: false } for subcall machines or backend: memory.

 §1 — No pruning/cleanup discussion for recursive subcalls

 Each recursive depth level creates a FlatMachine instance. The best practices say: "Prune terminal checkpoint history regularly." The plan should note that
 subcall machines are ephemeral and don't need persistence, or explicitly disable it for recursive invocations.

 §4 — No operational observability

 The best practices include health queries, FD pressure checks, and status monitoring. The plan has no equivalent — no logging strategy beyond what the SDK
 provides, no way to inspect recursion depth or subcall tree during a run. For an example this is acceptable, but the plan could add one sentence about
 logging hooks (the SDK's LoggingHooks or MetricsHooks via CompositeHooks).

 §Output Quality Guardrails — "Run a lightweight sentinel"

 The best practices recommend sentinel checks on outputs (section completeness, fallback phrase detection). The plan's check_final action only checks for the
 Final variable's existence. There's no quality gate on the answer itself. The plan could note this as a Phase D hardening item — e.g., checking that Final
 isn't a trivial/degenerate answer.

 ────────────────────────────────────────────────────────────────────────────────

 ### 🔶 One notable tension

 v1's multi-agent extraction pattern vs. best practice §2

 This isn't a PLAN_REV2 problem — it's a v1 problem that PLAN_REV2 correctly avoids. The v1 machine has findings_extractor, subquery_extractor,
 answer_extractor as separate agent stages that parse structured JSON from other agents' freeform output. This is exactly what §2 warns against: "Fragile
 parsing under load/retries. More transformation layers = more failure points."

 PLAN_REV2 eliminates all intermediate extraction agents. The coder produces code, hooks parse it mechanically, the REPL executes it. This is a clear
 improvement over v1 in light of the best practices.

 ────────────────────────────────────────────────────────────────────────────────

 ### 📊 Updated scorecard (with BEST_PRACTICES)

 ┌──────────────────────────────────────────┬───────────┬─────────────────────────────────────────────────────────────────┐
 │ Best Practice                            │ PLAN_REV2 │ Notes                                                           │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Checkpoint as job engine (§1)            │ 6/10      │ No persistence block; recursive subcalls need explicit strategy │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Avoid JSON/Jinja between LLM stages (§2) │ 10/10     │ Textbook compliance; big improvement over v1                    │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Explicit/shallow I/O mappings (§2)       │ 10/10     │ Single raw_response mapping                                     │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Full source text end-to-end (§Data Flow) │ 10/10     │ REPL context variable holds full text                           │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ DFS-style completion (§3)                │ 9/10      │ Loop-until-Final is inherently DFS                              │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Operational observability (§4)           │ 3/10      │ Not discussed; should note CompositeHooks + logging             │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Output quality guardrails                │ 4/10      │ Only checks Final is not None; no sentinel                      │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ FD/resource pressure (§Concurrency)      │ 5/10      │ Recursive subcalls create machines + locks; not discussed       │
 ├──────────────────────────────────────────┼───────────┼─────────────────────────────────────────────────────────────────┤
 │ Keep It Simple (§KIS)                    │ 10/10     │ 5 states, 1 agent, 1 machine — dramatically simpler than v1     │
 └──────────────────────────────────────────┴───────────┴─────────────────────────────────────────────────────────────────┘

 Bottom line: PLAN_REV2 nails the most impactful best practice (§2 — LLM handoff simplicity) and correctly avoids v1's anti-patterns. The gaps are operational
 (persistence strategy for subcalls, observability, quality guardrails) — all addressable as one-liners in Phase D.


