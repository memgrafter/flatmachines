- [x] FlatAgents debug I/O mode (raw, opt-in, redacted): add first-class debug capability to print rendered prompts + raw model output (and optionally transport payload metadata) across FlatAgents/FlatMachines without per-example custom hooks. Proposed levels: (a) metadata only (model/tokens/finish_reason), (b) rendered system+user prompts + raw completion text, (c) full request/response payload with secret/header redaction. Must be explicit opt-in (env/flag), safe by default to avoid PII/secret leakage, and consistent across providers/backends.
- [x] First-class explicit next-state from action output in FlatMachine (DX improvement): current pattern (action writes `context.next_state`, YAML transitions branch on it) is correct and stable, but has boilerplate and “stringly-typed” routing risks. Evaluate adding a direct contract like action-returned `next_state` (or reserved context key validated by engine) that jumps immediately when valid. Keep current transitions behavior for compatibility; add validation/error-on-unknown-state and good tracing so routing mistakes don’t silently fall through default branches.
- [x] Explore FlatAgent-level provider/profile fallback hooks (or document why fallback swapping should be FlatMachine-only). Use case: avoid dual-agent YAML files by swapping profile/provider at runtime with safe key handling.
- [x] Anthropic prompt caching support (.tickets/fla-ghnk). Anthropic supports automatic caching via a top-level cache_control param on the request body (no content-block restructuring needed). FlatAgent already forwards unknown model config keys to litellm params, so callers can add cache_control: {type: ephemeral} to their model config and it passes through. Verify this works end-to-end through litellm → OpenRouter → Anthropic and document it. If litellm strips the param, add it to the explicit pass-through list. See plan-checker for usage example.
- [x] ToolLoopAgent per-turn callback / input_data refresh (.tickets/fla-qfot). Currently run() takes input_data once and only renders templates on turn 0. There is no hook to inject dynamic state (remaining budget, elapsed cost, steering context) into subsequent turns. Callers who need per-turn injection must reimplement the loop (see plan-atomizer _run_tool_loop). Options: (a) accept a per-turn callback that returns extra messages to append after tool results, receiving current (turns, tool_calls, usage) as args; (b) accept a callable that returns updated input_data for re-rendering each turn. Option (a) is simpler and doesn't require re-rendering. The existing SteeringProvider is close but receives no loop state.
- [x] Port the live Codex cache tests built in swarm worker back into flatmachines/flatagents proper test suites (unit + integration) (.tickets/fla-yxu8). Specifically cover: execution_id->session_id/prompt_cache_key plumbing in execute_with_tools, first-3-message prefix stability across continuation turns, and large-initial-prompt continuation cache-hit behavior.
- [x] Hierarchical profile discovery with directory walk (.tickets/fla-zm0w). [2026-03-22T15:24:30]
  Currently profiles.yml is discovered only in the agent/machine's own config_dir (or passed explicitly). This means every subdirectory that contains agents needs its own profiles.yml, even when the whole project shares the same model defaults.
  **Desired behavior:** Walk parent directories from the agent's config_dir up to the project root (git root), then finally check ~/.agents/profiles.yml. Each closer directory's profiles.yml overrides the more distant one. Resolution order (lowest to highest priority):
    1. ~/.agents/profiles.yml  (user-global defaults)
    2. <git-root>/profiles.yml  (project-wide defaults)
    3. <git-root>/subdir/profiles.yml  (subdirectory overrides)
    4. ...intermediate dirs...
    5. <config_dir>/profiles.yml  (agent's own dir — highest priority)
  **Open design question — two options:**
  (A) **Synthesized fallback chain**: Walk the directory tree, load each profiles.yml found, and merge them into a single ProfileManager where each level's `model_profiles` dict is overlaid on top of the parent's. `default` and `override` settings from the nearest file win. This gives fine-grained per-profile inheritance: ~/.agents defines `fast` and `smart`, a subdirectory redefines only `fast` with a different model, and `smart` still resolves from the global. More powerful but merging semantics need clear documentation (shallow merge per profile name? deep merge per profile fields?).
  (B) **Bulk override — nearest file wins entirely**: Walk the tree, use the first (nearest) profiles.yml found. No merging. This is the current `resolve_profiles_with_fallback` semantics, just extended to walk directories instead of only own-vs-parent. Simpler mental model: "the closest profiles.yml is THE profiles config, period." Downside: if you override one profile in a subdirectory, you must copy all profiles into that file.
  **Recommendation:** Option A (synthesized fallback) with **shallow merge at the profile-name level** — each named profile is replaced wholesale, not field-merged. This gives the composability benefit (don't repeat profiles you didn't change) without confusing partial-field inheritance. `default` and `override` are taken from the nearest file that sets them (not inherited from parent if the child file exists but omits them — that would be surprising). This is the less confusing decision: profile names are the unit of override, not individual fields within a profile.
  **Affected code:**
  - Python: `sdk/python/flatagents/flatagents/profiles.py` — new `discover_profiles_chain(config_dir) -> List[str]` that walks dirs, new `merge_profiles_chain(chain) -> Dict` that shallow-merges. Update `ProfileManager.get_instance()` and `resolve_model_config()` to use the chain. Update `resolve_profiles_with_fallback` or deprecate it.
  - JS: `sdk/js/packages/flatagents/src/profiles.ts` — same pattern. New `discoverProfilesChain()`, update `ProfileManager.getInstance()`.
  - Python FlatAgent (`flatagent.py` L367-383): currently calls `discover_profiles_file` + `resolve_profiles_with_fallback`. Replace with chain discovery.
  - JS FlatAgent (`flatagent.ts` L79-83): currently checks only configDir. Replace with chain discovery.
  - FlatMachine profile propagation (`flatmachine.py` L151-152, L666-667, L936-937): child machines/agents should inherit the parent's resolved chain, not just a single profiles_dict. Or: the chain is resolved once at the top-level entry point and the merged result propagates down (simpler, already how `_profiles_dict` works).
  - Spec: `profile.d.ts` doc comments should document the directory-walk resolution.
  - Tests: chain discovery with nested dirs, git-root boundary, ~/.agents fallback, merge semantics (child profile overrides parent profile by name, parent-only profiles survive, `default`/`override` nearest-wins).
  **Git root detection:** Use `git rev-parse --show-toplevel` or walk looking for `.git`. Cache the result. Non-git projects: walk to filesystem root or stop at a sentinel file (e.g., `.flatagents-root`).

- [x] Headful logging: flatagents assumes headless operation and forces console output that can't be cleanly suppressed by embedding applications (.tickets/fla-710v). Two independent problems in monitoring.py need fixing:
  1. setup_logging() adds a StreamHandler(sys.stdout) to the "flatagents" namespace logger with propagate=False. This means host applications that configure the root logger never see flatagents logs, and can't redirect them. The stdout handler fires even if the host already configured logging.
     - Fix: change setup_logging() to NOT add any handlers by default. Instead, set propagate=True so flatagents logs flow to whatever the host application configured on root. Only add the stdout handler when there's an explicit opt-in (e.g. FLATAGENTS_LOG_HANDLER=stdout env var, or a new add_console_handler=True kwarg). This follows the Python logging best practice: libraries configure loggers and levels, applications configure handlers.
     - Files: sdk/python/flatagents/flatagents/monitoring.py — setup_logging(), around line 125-133.
     - Code change: replace the unconditional stdout handler block:
       ```python
       # BEFORE
       if not lib_logger.handlers:
           stdout_handler = logging.StreamHandler(sys.stdout)
           stdout_handler.setFormatter(formatter)
           lib_logger.addHandler(stdout_handler)
       lib_logger.propagate = False
       
       # AFTER
       add_console = os.getenv('FLATAGENTS_LOG_HANDLER', '').lower() in ('stdout', 'console', 'true')
       if force or add_console:
           if not lib_logger.handlers:
               stdout_handler = logging.StreamHandler(sys.stdout)
               stdout_handler.setFormatter(formatter)
               lib_logger.addHandler(stdout_handler)
           lib_logger.propagate = False
       else:
           # Library default: propagate to root, let host app decide output
           lib_logger.propagate = True
       ```
  2. _CompactConsoleMetricExporter.export() writes directly to sys.stdout.write() bypassing logging entirely (line ~290-291). When otel is installed and OTEL_METRICS_EXPORTER is unset (defaults to "console"), metrics JSON lines dump to stdout on a 5-second interval regardless of any logging config.
     - Fix: change the console exporter default. When otel is available but no explicit OTEL_METRICS_EXPORTER is set, default to "none" (disabled) instead of "console". Add "none" as a recognized exporter_type that skips reader/provider setup entirely. Console export becomes opt-in via OTEL_METRICS_EXPORTER=console.
     - Files: sdk/python/flatagents/flatagents/monitoring.py — _init_metrics(), around line 236.
     - Code change:
       ```python
       # BEFORE
       exporter_type = os.getenv('OTEL_METRICS_EXPORTER', 'console').lower()
       
       # AFTER
       exporter_type = os.getenv('OTEL_METRICS_EXPORTER', 'none').lower()
       if exporter_type == 'none':
           _metrics_enabled = False
           return
       ```
  3. Tests: add tests confirming (a) default setup_logging() adds no handlers and sets propagate=True, (b) FLATAGENTS_LOG_HANDLER=stdout adds the handler and sets propagate=False, (c) default _init_metrics() with otel installed does not create a console exporter, (d) OTEL_METRICS_EXPORTER=console creates the exporter.
  Motivation: sterling-swarm prototype needed 15 lines of workaround code to suppress flatagents console output. Any headful app (CLI, TUI, REPL) embedding flatagents hits the same problem. The fix is backward-compatible: headless/daemon users who already see logs on stdout can set FLATAGENTS_LOG_HANDLER=stdout to preserve current behavior.

- [x] Add live/integration coverage for FlatAgents-side `smolagents` and `pi-agent` runtimes (.tickets/fla-fjl7). Current migration moved those single-agent runtime adapters into Python FlatAgents, but we do not yet have live end-to-end tests/examples validating auth/environment/session behavior the way Codex/Claude paths are exercised. Add at least smoke tests and one example per runtime once credentials/tooling are available.
- [x] JS Codex CLI adapter mocked test suite (unit + integration-style) (.tickets/fla-2kur): add tests that mock `child_process.spawn` and feed NDJSON event streams to validate success/error/timeout/resume parsing without live Codex auth.
- [x] Python codex_cli adapter regression (.tickets/fla-5wx0): fix `CodexCliExecutor.execute()` compatibility with execution layer `session_id` kwarg (`TypeError: unexpected keyword argument 'session_id'`) so `sdk/examples/codex_cli_adapter/python` runs again.
- [x] Parity checker strict mode (.tickets/fla-hopv): harden `scripts/check-example-sdk-parity.mjs` to fail on capability mismatch (not only target resolution), with optional flag to keep current permissive behavior for transitional runs.
- [x] Distributed execution backends (Redis/Postgres) + cross-network peering (.tickets/fla-163j)
- [x] TypeScript SDK (vibe complete, untested) (.tickets/fla-h9ts)
- [x] `max_depth` to limit machine launch nesting (.tickets/fla-w11m)
- [x] Checkpoint pruning (easy to implement) (.tickets/fla-5i0n)
- [x] Tool registry (.tickets/fla-5kue)
- [x] If state actions living in hooks continues to confuse the mental model, add a separate action registry (.tickets/fla-d3ts) so actions and hooks are distinct concepts.
- [x] FlatAgents profiles UX (.tickets/fla-e9hr): warn loudly when `data.override` points to a missing profile (e.g. `override: fast` but only `cheap` exists). Should emit clear actionable warning and ideally fail fast or auto-fallback with explicit notice so users know the intended model override was not applied.

- [x] Fix FlatMachines -> FlatAgents embedded config path handling (.tickets/fla-pazj): when FlatMachine resolves an agent file ref (e.g. config/agents/foo.flatagent.yml) into an embedded config dict for checkpoint/self-contained execution, preserve the agent file's source config_dir (dirname of the agent file). FlatAgentAdapter should pass that preserved config_dir to FlatAgent(config_dict=..., config_dir=...) instead of the machine config_dir. This allows canonical agent-local prompt refs like `prompt: ../prompts/foo.prompt.yml` and removes the need for symlink workarounds such as config/agents/prompts -> ../prompts.
