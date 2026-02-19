
 I checked REVIEW_REV3.md — it’s a strong review, and I agree with almost all of it.

 What I agree with

 - ✅ REV3 is genuinely implementation-ready and much cleaner than prior revs.
 - ✅ Bare-path mappings were the right fix (type preservation, no Jinja null/none footgun).
 - ✅ max_steps needs explicit caller wiring (both top-level and recursive subcalls).
 - ✅ machine_config_path ambiguity should be resolved (required or sentinel behavior).
 - ✅ best_partial null behavior should be explicitly intentional.
 - ✅ Recursive llm_query design is feasible with thread bridge + execute_sync.

 One correction to the reviewer

 - The note that _json_finalize will make history_meta render as JSON in the agent prompt is not strictly correct for FlatAgent.
     - _json_finalize is in FlatMachine’s Jinja env, not FlatAgent’s.
     - FlatAgent uses its own Jinja environment without that finalize hook.
     - So {{ input.history_meta }} may render as Python-ish repr, not guaranteed JSON.
     - Safer fix: pass history_meta_text (pre-serialized JSON string from hooks) to the coder agent.

 Recommended deltas before implementation (small)

 1. Define terminal fallback behavior explicitly (answer may be None vs guaranteed string).
 2. Add one sentence clarifying max_steps dual role (input propagation + execute kwarg).
 3. Make machine_config_path required, or return SUBCALL_NOT_CONFIGURED in llm_query.
 4. Add a concrete coder.yml skeleton/prompt block in the plan.
 5. (Optional) mention CompositeHooks / LoggingHooks shortcut in observability section.

 If you want, I can apply these directly as a PLAN_REV4.md.


