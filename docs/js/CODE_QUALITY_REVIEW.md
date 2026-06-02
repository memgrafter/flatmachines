# JS SDK Code Quality & Architecture Review

**Date:** 2026-03-26  
**Scope:** `sdk/js/packages/flatagents` + `sdk/js/packages/flatmachines`  
**Codebase:** ~10,580 lines across 2 packages (68 source files)

---

## Overall Assessment

Solid foundation, well-ported from Python, clean layered architecture. Some areas need tightening — primarily around the god-class `FlatMachine`, type safety, error handling, and resource lifecycle.

---

## Strengths

### 1. Clean package boundary
`flatagents` has zero dependency on `flatmachines`. No circular references. Adapters live in flatmachines and register themselves via `AgentAdapterRegistry.registerBuiltinFactory()` side-effect imports — a practical pattern.

### 2. Consistent abstractions
The `AgentExecutor` / `AgentAdapter` / `AgentAdapterRegistry` protocol is well-defined and identical across all 3 adapters (FlatAgent, ClaudeCode, CodexCli). Each adapter maps cleanly to an executor.

### 3. Good separation of concerns
Types in `types.ts`, expression evaluation separate from machine execution, persistence backends pluggable, signal/trigger backends pluggable. The `CheckpointManager` wrapping pattern keeps the machine core clean.

### 4. SQLite auto-wiring
When `persistence.backend = 'sqlite'`, the constructor auto-wires `SQLiteLeaseLock` and `SQLiteConfigStore` from the same DB handle — nice ergonomic that eliminates boilerplate.

### 5. Python compatibility in templates
The nunjucks `suppressValue` patch (`true→"True"`, `false→"False"`, `null→"None"`) and `tojson` filter with Python-compatible separators (`', '` and `': '`) are thoughtful and necessary for cross-SDK config parity.

### 6. Test coverage
1,821 passing parity tests mapping directly to Python test cases. The test matrix system (`test-matrix.ts` + manifest) tracks ownership clearly. 53 remaining failures are well-documented.

---

## Issues to Address

### 1. `flatmachine.ts` is a 1,324-line god class
**Severity: Medium — Maintainability**

The `FlatMachine` class handles: config parsing, context rendering, agent execution, machine execution, foreach parallelism, tool loop orchestration, wait-for/signals, checkpointing, launches, expression evaluation, and metadata injection.

**Recommendation:** Extract into focused modules:
- `machine_executor.ts` — the `executeInternal` loop + state dispatch
- `machine_context.ts` — render/template/expression helpers
- `machine_lifecycle.ts` — checkpoint/resume/launch logic

### 2. Excessive `as any` casts
**Severity: Medium — Type Safety**

22 `as any` casts in `flatmachine.ts`, 14 in `flatagents`. Many work around the SDK's own types, signaling the type definitions aren't expressive enough.

**Examples:**
- `(this.config as any)?.data?.profiles` — `MachineConfig` should have `profiles` in the type
- `(backend as SQLiteCheckpointBackend).db` — narrowing via `instanceof` should type-check without cast
- `(extOpts as any).config_store` — `ExtendedMachineOptions` already has `configStore` but the code also checks a snake_case variant

**Recommendation:** Tighten the `MachineConfig` and `ExtendedMachineOptions` types to remove the cast necessity. Add missing optional fields to interfaces rather than casting.

### 3. Mixed `require()` / ESM imports in library code
**Severity: Medium — Compatibility**

`LocalFileConfigStore`, `FileTrigger`, `SocketTrigger`, `SubprocessInvoker`, and `expression_cel.ts` use runtime `require()` inside methods. This works with tsup bundling but:
- Breaks in strict ESM-only environments
- Makes tree-shaking impossible for those code paths
- `require('yaml')` inside `SQLiteConfigStore.put()` is redundant — `yaml` is already a dependency imported at top-level elsewhere

**Files affected:**
- `persistence_sqlite.ts` (6 occurrences)
- `signals.ts` (2 occurrences)
- `actions.ts` (5 occurrences)
- `expression_cel.ts` (1 occurrence)
- `resume.ts` (1 occurrence)

**Recommendation:** Use dynamic `import()` for truly optional deps (node:sqlite, cel-js). Use top-level imports for deps that are already in package.json (fs, path, yaml).

### 4. Silent error swallowing in `CompositeHooks`
**Severity: High — Debuggability**

Every hook method in `CompositeHooks` has a bare `catch {}`. If a hook throws, it's silently ignored with no logging. This makes debugging machine behavior very difficult — hooks that fail appear to succeed.

**File:** `sdk/js/packages/flatmachines/src/hooks.ts` (11 bare catch blocks)

**Recommendation:**
- At minimum, log a warning via the SDK's logger
- Consider an optional `strict` mode that makes hook errors fatal
- At very least, catch the error variable: `catch (e) { /* log e */ }`

### 5. Hardcoded fallback cost estimation
**Severity: Low — Accuracy**

`FlatAgent._calculate_cost()` has fixed per-token costs (`$0.000001` input, `$0.000003` output) baked in as constants with no way to override. These will drift from actual provider pricing.

**File:** `sdk/js/packages/flatagents/src/flatagent.ts`

**Recommendation:** Either make them configurable per-model via profile config, or return zero-cost `CostInfo` when real pricing isn't available (preferred — inaccurate numbers are worse than none).

### 6. Two parallel result type systems
**Severity: Low — API Surface**

- `AgentResponse` (class with methods, used by `FlatAgent.call()`)
- `AgentResult` (plain interface/dict, used by `AgentExecutor.execute()`)

The `FlatAgentExecutor._mapResponse()` manually translates between them. This adds surface area for bugs and forces consumers to know which type they're getting depending on whether they use FlatAgent directly vs through a machine.

**Recommendation:** Long-term, unify to one type. Short-term, this is inherited from Python parity and is acceptable.

### 7. `extractRateLimitInfo()` mutates after construction
**Severity: Low — Fragility**

```ts
const result = new RateLimitInfo({ raw_headers: headers });
(result as any).remaining_requests = remaining_requests;  // bypasses constructor
```

The class constructor defaults fields to `null`, then they're overwritten with `undefined` (semantically different in JS). The comment in the code acknowledges the mismatch.

**File:** `sdk/js/packages/flatagents/src/agent_response.ts`

**Recommendation:** Pass all fields to the constructor directly.

### 8. No `close()` / `dispose()` lifecycle on `FlatMachine`
**Severity: Medium — Resource Leaks**

`SQLiteCheckpointBackend`, `SQLiteSignalBackend`, etc. have `.close()` methods, but `FlatMachine` has no cleanup path. Long-running processes that create/destroy machines leak DB handles.

**Recommendation:** Add `FlatMachine.close()` (or `dispose()`) that cascades to owned backends. Consider implementing `Symbol.dispose` for `using` support.

### 9. Expression parser limitations undocumented
**Severity: Low — DX**

The simple expression evaluator handles dot-access, comparisons, bracket indexing, and boolean logic (`and`, `or`, `not`), but not:
- `x in list`
- `len(items)` or any function calls
- Arithmetic (`+`, `-`, `*`, `/`)
- String concatenation

The CEL fallback (`cel-js`) handles most of these but must be explicitly opted into via `expression_engine: cel` in machine config.

**Recommendation:** Document the simple engine's limitations clearly in the spec/README. Consider making CEL the default since it's already a dependency.

### 10. Barrel export re-exports entire dependency
**Severity: Low — Bundle Size**

`flatmachines/src/index.ts` has `export * from '@memgrafter/flatagents'` plus 32 additional export blocks. Consumers who only need `FlatMachine` pull in the entire agent SDK surface through the barrel.

**Recommendation:** Consider split entry points (e.g., `@memgrafter/flatmachines/machine` for just the machine). Alternatively, document that tsup's tree-shaking handles this for production builds.

---

## Minor Nits

- **Zero TODO/FIXME/HACK comments.** Either everything is done or these were stripped. Some tracked tech debt comments would be helpful for future contributors.
- **`nunjucks` is a large dependency** for a library SDK (~450KB). A lighter Jinja2-subset might be worth evaluating eventually (e.g., liquidjs is ~60KB).
- **`SQLiteCheckpointBackend` latest-pointer logic** stores the value as raw JSON when the key ends in `/latest`, but as a forward-reference key otherwise. This dual behavior is implicit and easy to misuse.
- **`WebhookHooks`** uses `fetch()` with no retry and silent error swallowing — appropriate for a non-critical notification hook, but should document this.
- **`SubprocessInvoker`** in `actions.ts` generates Node.js code strings with `require()` and writes them to temp files for execution — a creative approach but fragile. Would benefit from a dedicated worker script.

---

## Summary

| Area | Grade | Notes |
|------|-------|-------|
| Package architecture | **A** | Clean layering, no circular deps |
| Type safety | **B-** | Too many `as any` casts |
| Error handling | **C+** | Silent swallowing in hooks, bare catches |
| Test coverage | **A-** | 1,821 parity tests, 53 failures remaining |
| API surface | **B+** | Two result types, large barrel exports |
| Resource lifecycle | **C** | No cleanup path for DB handles |
| Code organization | **B** | flatmachine.ts needs decomposition |
| Python parity fidelity | **A** | Template compat, expression semantics, adapter patterns |

---

## Prioritized Action Items

1. **Add `FlatMachine.close()`** — resource leak prevention (medium effort, high impact)
2. **Add logging to `CompositeHooks` catch blocks** — debuggability (low effort, high impact)
3. **Tighten types to eliminate `as any`** — type safety (medium effort, medium impact)
4. **Replace `require()` with top-level imports or `import()`** — ESM compat (medium effort, medium impact)
5. **Decompose `flatmachine.ts`** — maintainability (high effort, medium impact)
6. **Fix `extractRateLimitInfo` constructor usage** — correctness (low effort, low impact)
7. **Remove hardcoded cost fallback** — accuracy (low effort, low impact)
8. **Document expression engine limitations** — DX (low effort, low impact)
