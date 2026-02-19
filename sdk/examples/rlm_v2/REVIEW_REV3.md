 PLAN_REV3 Standalone Review

 ### Overall assessment

 This is a well-structured, implementation-ready plan. It's self-contained — an implementer wouldn't need REV1/REV2. The document is organized logically:
 invariants → SDK constraints → contracts → YAML → hooks → recursion → CLI → phases → checklist.

 ────────────────────────────────────────────────────────────────────────────────

 ### ✅ What REV3 gets right

 Bare-path mappings solve the biggest REV2 bug

 REV3 switches from "{{ input.task }}" to input.task throughout. This is the single most impactful change:
 - The SDK's _render_template() detects bare paths via _PATH_PATTERN regex (^(output|context|input)(\.[a-zA-Z_][a-zA-Z0-9_]*)*$) and resolves them via
 _resolve_path(), preserving native Python types.
 - No more Jinja string coercion. input.current_depth stays an int. input.long_context stays a string. No null vs none issue.
 - YAML-native defaults (session_id: null, iteration: 0, is_final: false, history_meta: []) are parsed by YAML directly as None, 0, False, []. No Jinja
 needed.

 This is correct and clean.

 §3 (SDK compatibility constraints) is excellent

 This section didn't exist in REV2. It explicitly documents four SDK behaviors the plan depends on: template typing, settings.max_steps, agent output
 contract, and persistence defaults. This is exactly the kind of "design rationale" section that prevents implementation surprises. An implementer reading
 only this doc would know what to watch for.

 §12 (Persistence posture) is well-reasoned

 persistence: { enabled: false, backend: memory } with an explicit rationale paragraph. This directly addresses the best-practice concern about
 checkpoint/lock churn from recursive subcalls. The forward pointer to "DB-backed persistence for productionization" is appropriate.

 §9 (Recursive llm_query()) is concrete enough to implement

 The sub-input mapping, thread bridge, timeout sentinel, and known-limitation acknowledgment are all specified. The ThreadPoolExecutor + execute_sync()
 strategy is correct — execute_sync calls asyncio.run(), which works in a fresh worker thread with no existing event loop.

 The invariant list (§2) is the right anchor

 Five crisp invariants. The validation checklist (§16) maps back to them. This makes it testable.

 ────────────────────────────────────────────────────────────────────────────────

 ### ⚠️ Issues and gaps

 1. Terminal states can emit answer: None with no fallback

 ```yaml
   max_iter_done:
     type: final
     output:
       answer: context.best_partial    # bare path → None if never set
 ```

 REV2 had {{ context.best_partial | default('No Final variable set') }}. REV3 drops this because it switched to bare paths (which can't have Jinja filters).
 If no iteration produced a useful partial, the output is {"answer": null, "reason": "max_iterations", ...}.

 Options:
 - Accept None and let the caller handle it (simplest, arguably correct for an example).
 - Have check_final hook always maintain a non-None best_partial string (e.g., "No answer produced").
 - Note the design choice explicitly in §4.2.

 This isn't a bug, but it's a behavior change from REV2 that should be intentional and documented.

 2. max_steps lives in two roles — machine input AND execution parameter

 §4.1 lists max_steps as a machine input field. §5 puts it in context. §11.2 says caller passes it to execute(). The llm_query() bridge (§9.3) calls
 execute_sync(input=sub_input, max_steps=...).

 The subtlety: max_steps needs to be extracted from context and passed as a keyword argument to execute_sync(), not just included in the input dict. The input
 dict feeds into data.context template rendering; max_steps as an execute() parameter controls the loop ceiling independently.

 The plan implies this but doesn't say it explicitly. §9.3 says:

 │ call execute_sync(input=sub_input, max_steps=sub_input['max_steps'])

 This works if sub_input contains max_steps, but it's slightly confusing because max_steps is doing double duty (input field for context propagation AND
 execution parameter). A one-liner clarification would help: "max_steps is passed both in input (for context propagation to further subcalls) and as a keyword
 to execute_sync (for loop control)."

 3. machine_config_path is loosely required

 §4.1 lists it as "Optional controls" but §8.1 says init_session should "validate required fields (task, machine_config_path optionally if recursion
 expected)." The parenthetical "optionally" is ambiguous.

 In practice, if machine_config_path is None and REPL code calls llm_query(), it will fail at FlatMachine(config_file=None). The plan should either:
 - Make it required (simplest — the demo always needs it).
 - Have llm_query() return a sentinel like "SUBCALL_NOT_CONFIGURED" when machine_config_path is missing.

 4. §7 (Coder agent) is under-specified for standalone implementation

 The section describes system prompt requirements (7 bullets) and user prompt contents (4 items), but doesn't include the actual coder.yml structure or prompt
 text. An implementer would need to write the agent config and both prompts from scratch.

 Compare to the v1 example which has full agent YAML files (e.g., explorer.yml, decomposer.yml) with complete prompts. §7 should either include the actual
 YAML or note it as a Phase A deliverable with enough specificity (model profile reference, expected output format, example prompt sketch).

 5. history_meta as agent input — bare path resolves to Python list, not JSON string

 ```yaml
   input:
     history_meta: context.history_meta
 ```

 Bare path resolves to a Python list. The FlatAgent adapter calls await self._agent.call(**input_data), so history_meta arrives as a Python list in the
 agent's call() kwargs. Inside FlatAgent.call(), this gets templated into the prompt.

 This should work — FlatAgent's prompt rendering handles lists — but it's worth confirming that the agent prompt template renders the list readably (not as
 Python repr [{'iteration': 1, ...}]). The SDK's _json_finalize converts lists/dicts to JSON strings in Jinja output, so {{ history_meta }} in the agent
 prompt would render as valid JSON. This is fine, just noting the path.

 6. No mention of CompositeHooks for observability

 §13.1 says "add structured logging in hooks." The simplest SDK-idiomatic approach is CompositeHooks(RLMV2Hooks(), LoggingHooks()) or MetricsHooks(). The plan
 doesn't mention these built-in helpers. Minor, but a one-liner would save implementation time.

 ────────────────────────────────────────────────────────────────────────────────

 ### 📋 Structural quality as a standalone doc

 ┌──────────────────────────────────────────┬────────┬───────────────────────────────────────────────────────────────────────────────────┐
 │ Criterion                                │ Rating │ Notes                                                                             │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Self-contained (no REV1/REV2 dependency) │ 10/10  │ Everything needed is here                                                         │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Logical flow                             │ 9/10   │ Invariants → constraints → contracts → design → impl phases                       │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Implementability                         │ 8/10   │ Coder agent (§7) needs more detail; everything else is buildable                  │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ SDK accuracy                             │ 9/10   │ Bare paths, persistence, hooks all correct; max_steps dual-role is slightly muddy │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Invariant traceability                   │ 9/10   │ §2 invariants → §16 checklist alignment is strong                                 │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Ambiguity count                          │ Low    │ Only machine_config_path optionality and best_partial null fallback               │
 ├──────────────────────────────────────────┼────────┼───────────────────────────────────────────────────────────────────────────────────┤
 │ Scope discipline                         │ 10/10  │ Non-goals (§1.3) are explicit; no feature creep                                   │
 └──────────────────────────────────────────┴────────┴───────────────────────────────────────────────────────────────────────────────────┘

 ────────────────────────────────────────────────────────────────────────────────

 ### Summary of actionable items

 1. Decide and document best_partial null behavior in terminal states — accept None or default in hooks.
 2. Clarify max_steps dual role (input field for propagation + execute() kwarg for control) with one sentence.
 3. Tighten machine_config_path — either make it required or define llm_query() behavior when absent.
 4. Flesh out §7 with at minimum a coder.yml skeleton (model profile ref, prompt template structure).
 5. Optional: mention CompositeHooks / LoggingHooks in §13 as SDK shortcut.

 None of these are blocking — the plan is implementable as-is. Items 1–3 are one-liners; item 4 is the only one requiring real content.

