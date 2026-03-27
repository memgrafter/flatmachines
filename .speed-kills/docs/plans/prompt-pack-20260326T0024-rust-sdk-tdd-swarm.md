# Prompt Pack: Rust SDK TDD — flatagents + flatmachines (full coverage)

**Plan:** Rust SDK TDD for flatagents and flatmachines crates
**Generated:** 2026-03-26T00:24
**Approach:** Full TDD — tests first, red phase expected, implementation follows

---

## Execution DAG

Stage S0 (bootstrap) must complete before S1 (parallel test suites) begins.
All S1 workers own disjoint files and run fully in parallel.

```yaml
stages:
  - id: S0
    workers: [rust-bootstrap-stubs]
    depends_on: []
  - id: S1
    workers: [rust-flatagents-types-suite, rust-flatagents-profiles-suite, rust-flatagents-templating-suite, rust-flatagents-validation-suite, rust-flatmachines-types-suite, rust-flatmachines-expression-suite, rust-flatmachines-hooks-suite, rust-flatmachines-execution-suite, rust-flatmachines-persistence-suite, rust-flatmachines-locking-suite, rust-flatmachines-signals-suite, rust-flatmachines-backends-suite]
    depends_on: [S0]
```

## Shared Baseline Context

### Project structure
- Workspace root: `sdk/rust/Cargo.toml` (members: `flatagents`, `flatmachines`)
- FlatAgents crate: `sdk/rust/flatagents/` — config types, profiles, templating, validation
- FlatMachines crate: `sdk/rust/flatmachines/` — machine types, execution, expression, hooks, persistence, signals, locking, backends
- Python reference SDK: `sdk/python/flatagents/` and `sdk/python/flatmachines/`
- Python reference tests: `sdk/python/tests/unit/` and `sdk/python/tests/integration/`
- Spec type definitions: `flatagent.d.ts`, `flatmachine.d.ts`, `profiles.d.ts` (root level)

### Rust SDK conventions
- Use `serde` with `Serialize`/`Deserialize` for all config types
- Use `thiserror` for error types
- Use `async-trait` for async trait objects
- Use `tokio` for async runtime
- Use `minijinja` (NOT Jinja2) for templates
- Use `serde_yaml` 0.9 for YAML parsing
- Use `pretty_assertions` in dev-dependencies for readable test diffs
- Tests go in `#[cfg(test)] mod tests { ... }` blocks at the bottom of each module OR in `tests/` directory
- For this TDD run: put tests in `tests/` directory files so they are separate from the stubs

### TDD rules
- **Write tests FIRST** that document what the behavior SHOULD be based on the Python reference.
- The Rust implementation is skeletal/incomplete. Tests WILL FAIL. That is the desired outcome.
- **Do NOT weaken assertions to make tests pass.** Write correct tests based on Python behavior.
- **Do NOT write fake tests** that construct objects and assert their own literals without exercising real SDK code.
- Every test must `use flatagents::*` or `use flatmachines::*` and exercise real crate APIs.
- If a function/type doesn't exist yet, write the test with the correct import anyway — a compile error is a valid red test.
- **Delivering a partially or fully red suite is expected and intentional.** Red tests are the backlog.
- Run `cd sdk/rust && cargo test 2>&1` to validate. Report pass/fail/compile-error counts honestly.

### Important: Do NOT modify files you don't own
- Each worker owns specific files listed below. Only modify those.
- The bootstrap worker (S0) creates stub files. S1 workers create test files.
- Do NOT modify `Cargo.toml` files, `lib.rs`, or any existing source files unless explicitly in your owned-files list.

### Validation command
```bash
cd sdk/rust && cargo test 2>&1
```
For individual crate tests:
```bash
cd sdk/rust && cargo test -p flatagents 2>&1
cd sdk/rust && cargo test -p flatmachines 2>&1
```

---

## Worker: rust-bootstrap-stubs

**Stage:** S0 (must complete before S1)
**Objective:** Create minimal stub files so `flatmachines` compiles. Each stub provides the trait/type signatures referenced by `lib.rs` with `todo!()` or empty implementations.
**Owned files:** `sdk/rust/flatmachines/src/backends.rs`, `sdk/rust/flatmachines/src/execution.rs`, `sdk/rust/flatmachines/src/expression.rs`, `sdk/rust/flatmachines/src/hooks.rs`, `sdk/rust/flatmachines/src/persistence.rs`, `sdk/rust/flatmachines/src/signals.rs`, `sdk/rust/flatmachines/src/validation.rs`
Refs: `sdk/rust/flatmachines/src/lib.rs`, `sdk/python/flatmachines/flatmachines/`
Dependencies: none
Constraints: Stubs must export the types that lib.rs re-exports. Keep implementations minimal with todo!() bodies. Goal is ONLY to make cargo check pass.
Validation: `cd sdk/rust && cargo check 2>&1`

**Prompt:**
```text
Create minimal stub files for the 7 missing modules in sdk/rust/flatmachines/src/ so the crate compiles.

The lib.rs already declares these modules and re-exports:
  pub use backends::{ResultBackend, InMemoryResultBackend};
  pub use execution::{ExecutionType, AgentExecutor};
  pub use expression::ExpressionEngine;
  pub use hooks::{MachineHooks, HooksRegistry};
  pub use locking::ExecutionLock;  // already exists
  pub use persistence::PersistenceBackend;
  pub use signals::{SignalBackend, TriggerBackend};

For each missing module, create the .rs file with:
1. The trait/struct that lib.rs expects to import
2. Minimal trait definitions using async_trait where needed
3. Empty/todo!() implementations
4. Proper doc comments describing the intended purpose (reference Python SDK)

Read these Python files for API shape reference:
- sdk/python/flatmachines/flatmachines/backends.py → backends.rs
- sdk/python/flatmachines/flatmachines/execution.py → execution.rs
- sdk/python/flatmachines/flatmachines/expressions/simple.py → expression.rs
- sdk/python/flatmachines/flatmachines/hooks.py → hooks.rs
- sdk/python/flatmachines/flatmachines/persistence.py → persistence.rs
- sdk/python/flatmachines/flatmachines/signals.py → signals.rs
- sdk/python/flatmachines/flatmachines/validation.py → validation.rs

After creating all 7 files, run: cd sdk/rust && cargo check
Report: 0 errors = done. Any errors = fix them.
```

---

## Worker: rust-flatagents-types-suite

**Stage:** S1
**Objective:** Comprehensive test suite for flatagents config types — deserialization from YAML, serialization round-trips, all enum variants, nested types, edge cases.
**Owned files:** `sdk/rust/flatagents/tests/types_test.rs`
**Refs:** `sdk/python/flatagents/flatagents/baseagent.py`, `sdk/python/tests/unit/metrics/test_dataclasses.py`, `flatagent.d.ts`, `sdk/rust/flatagents/src/types.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatagents/tests/types_test.rs — comprehensive tests for all config types.

Reference: flatagent.d.ts (spec schema), sdk/rust/flatagents/src/types.rs (Rust types), sdk/python/tests/unit/metrics/test_dataclasses.py (Python test patterns)

Test categories (aim for 40+ tests):

1. AgentConfig deserialization (5+ tests):
   - Minimal valid config (spec, spec_version, data with model/system/user)
   - Full config with all optional fields
   - Missing required fields → error
   - Extra unknown fields in metadata
   - Round-trip serialize/deserialize

2. ModelRef variants (8+ tests):
   - Profile string: model: "fast"
   - Inline config: model: { provider: openai, name: gpt-4 }
   - Profiled config: model: { profile: "fast", temperature: 0.9 }
   - Inline with all optional fields (temperature, max_tokens, top_p, etc.)
   - Backend enum values: litellm, aisuite, codex
   - OAuth config nested in model
   - Profiled with name override
   - Ambiguous cases (serde untagged discrimination)

3. OutputSchema (6+ tests):
   - Simple string field
   - All field types: str, int, float, bool, json, list, object
   - Nested list with items
   - Nested object with properties
   - Enum field with allowed values
   - Required/optional fields

4. AgentResult / runtime types (10+ tests):
   - Default AgentResult (all None)
   - Full AgentResult with all fields
   - UsageInfo with partial fields
   - CostInfo with total calculation
   - AgentError with retryable flag
   - RateLimitState with windows
   - RateLimitWindow fields
   - ProviderData serialization
   - JSON round-trip for AgentResult
   - Deserialize from JSON (cross-language compat)

5. Tool/MCP types (6+ tests):
   - ToolDefinition with function
   - FunctionDef with parameters (JSON Schema)
   - MCPConfig with servers
   - MCPServerDef stdio transport
   - MCPServerDef HTTP transport
   - ToolFilter allow/deny

6. Edge cases (5+ tests):
   - Empty YAML data section → error
   - Unicode in prompts
   - Very long prompt strings
   - Null vs missing optional fields
   - serde rename behavior (field_type → "type")

Run: cd sdk/rust && cargo test -p flatagents --test types_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatagents-profiles-suite

**Stage:** S1
**Objective:** Test suite for profile resolution logic — all resolution paths, override behavior, default fallbacks, error cases.
**Owned files:** `sdk/rust/flatagents/tests/profiles_test.rs`
**Refs:** `sdk/python/flatagents/flatagents/profiles.py`, `sdk/python/tests/unit/test_profiles_discovery.py`, `profiles.d.ts`, `sdk/rust/flatagents/src/profiles.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatagents/tests/profiles_test.rs — comprehensive tests for profile resolution.

Reference: sdk/python/tests/unit/test_profiles_discovery.py (14 cases), sdk/rust/flatagents/src/profiles.rs

Test categories (aim for 25+ tests):

1. ProfilesConfig deserialization (5+ tests):
   - Full profiles YAML with multiple profiles, default, override
   - Minimal profiles (one profile, no default)
   - Profile with all model parameters
   - YAML round-trip
   - Invalid YAML → error

2. resolve_model — Profile name lookup (4+ tests):
   - Existing profile resolves correctly
   - Missing profile → ProfileNotFound error
   - No profiles provided → ProfileNotFound error
   - Case sensitivity of profile names

3. resolve_model — Inline config (3+ tests):
   - Inline config passes through unchanged
   - Inline config ignores profiles entirely
   - Inline with backend set

4. resolve_model — Profiled with overrides (5+ tests):
   - Base profile + temperature override
   - Base profile + name override
   - Base profile + provider override
   - Multiple overrides applied
   - Missing base profile → error

5. resolve_model — Override trumps all (4+ tests):
   - Override profile replaces inline config
   - Override profile replaces named profile
   - Override profile replaces profiled config
   - Missing override profile → error

6. resolve_model_with_default (4+ tests):
   - Falls back to default when profile not found
   - Default profile used when model ref is unknown profile
   - No default and no match → Config error
   - Default profile resolution with overrides

Run: cd sdk/rust && cargo test -p flatagents --test profiles_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatagents-templating-suite

**Stage:** S1
**Objective:** Test suite for minijinja template rendering — all render functions, namespace handling, error cases, map rendering.
**Owned files:** `sdk/rust/flatagents/tests/templating_test.rs`
**Refs:** `sdk/python/tests/unit/test_type_preservation.py`, `sdk/rust/flatagents/src/templating.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatagents/tests/templating_test.rs — comprehensive tests for template rendering.

Reference: sdk/rust/flatagents/src/templating.rs, sdk/python/tests/unit/test_type_preservation.py (34 cases)

Test categories (aim for 30+ tests):

1. render() basic (6+ tests):
   - Simple variable substitution
   - Multiple variables
   - Nested object access (dot notation)
   - Missing variable → error or empty string (check minijinja behavior)
   - Integer variable renders as string
   - Boolean variable
   - List/array variable

2. render_with_input() (5+ tests):
   - Single input field
   - Multiple input fields
   - Nested input objects
   - Input with special characters
   - Empty input map

3. render_with_context() (5+ tests):
   - Both input and context namespaces
   - Context overrides don't leak into input
   - Complex context with nested values
   - Numeric context values
   - Template referencing both namespaces

4. render_map() (6+ tests):
   - String values get rendered as templates
   - Non-string values pass through unchanged
   - Rendered string that looks like JSON number → parsed as number
   - Rendered string that looks like JSON bool → parsed as bool
   - Rendered string that is plain text → stays as string
   - Mixed map with templates and literals

5. Type preservation (4+ tests, from Python test_type_preservation.py):
   - Integer values preserved through render_map
   - Float values preserved
   - Boolean values preserved
   - Null/None values preserved

6. Error handling (4+ tests):
   - Invalid template syntax → Template error
   - Unclosed tag → error
   - Undefined filter → error
   - Template with recursive reference

Run: cd sdk/rust && cargo test -p flatagents --test templating_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatagents-validation-suite

**Stage:** S1
**Objective:** Test suite for spec version validation — compatibility rules, error messages, edge cases.
**Owned files:** `sdk/rust/flatagents/tests/validation_test.rs`
**Refs:** `sdk/rust/flatagents/src/validation.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatagents/tests/validation_test.rs — comprehensive tests for spec version validation.

Reference: sdk/rust/flatagents/src/validation.rs

Test categories (aim for 15+ tests):

1. Compatible versions (4+ tests):
   - Same version as SDK → ok
   - Same major, different minor → ok
   - Same major, different patch → ok
   - "2.0.0" vs "2.5.0" → ok

2. Incompatible versions (3+ tests):
   - Different major version (1.x vs 2.x) → error
   - Future major version (3.x vs 2.x) → error
   - Major version 0 → error

3. Invalid format (4+ tests):
   - Empty string → error
   - Non-numeric → error
   - Missing minor/patch → ok or error (test actual behavior)
   - Just a number "2" → test behavior

4. load_yaml / load_file integration (4+ tests):
   - Valid YAML with matching version → ok
   - Valid YAML with mismatched version → error
   - Invalid YAML → Yaml error
   - Valid YAML, invalid spec version format → error

Run: cd sdk/rust && cargo test -p flatagents --test validation_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-types-suite

**Stage:** S1
**Objective:** Comprehensive test suite for flatmachines config types — MachineConfig, StateDefinition, transitions, all enums, nested types.
**Owned files:** `sdk/rust/flatmachines/tests/types_test.rs`
**Refs:** `flatmachine.d.ts`, `sdk/python/tests/unit/test_helloworld_machine.py`, `sdk/python/tests/unit/test_machine_is_the_job.py`, `sdk/rust/flatmachines/src/types.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/types_test.rs — comprehensive tests for machine config types.

Reference: flatmachine.d.ts, sdk/rust/flatmachines/src/types.rs, sdk/python/tests/unit/test_helloworld_machine.py (9 cases), sdk/python/tests/unit/test_machine_is_the_job.py (10 cases)

Test categories (aim for 50+ tests):

1. MachineConfig deserialization (8+ tests):
   - Minimal machine (just states with initial+final)
   - Full machine with all fields
   - Hello-world machine from examples
   - Machine with agents map (path refs)
   - Machine with inline agent configs
   - Machine with machines map (sub-machines)
   - Machine with persistence config
   - Round-trip serialize/deserialize

2. StateDefinition variants (10+ tests):
   - Initial state
   - Final state with output
   - State with agent reference
   - State with machine invocation (single)
   - State with parallel machines (array)
   - State with action
   - State with wait_for
   - State with tool_loop: true
   - State with tool_loop: detailed config
   - State with foreach/as/key

3. Transition/OnError (6+ tests):
   - Simple transition (just to)
   - Conditional transition
   - Multiple transitions (first match wins)
   - Default transition (no condition)
   - OnError as single state name
   - OnError as per-type mapping

4. Execution config (5+ tests):
   - Default execution type
   - Retry with backoffs and jitter
   - Parallel with n_samples
   - MDAP voting with k_margin
   - Missing required fields

5. AgentRef / MachineRef variants (6+ tests):
   - AgentRef::Path (string)
   - AgentRef::Typed (adapter ref)
   - AgentRef::Inline (full agent config)
   - MachineRef::Path
   - MachineRef::Inline
   - Typed agent ref with config

6. MachineSnapshot (6+ tests):
   - Full snapshot with all fields
   - Minimal snapshot
   - Snapshot with tool_loop_state
   - Snapshot with waiting_channel
   - Snapshot with pending_launches
   - JSON round-trip (cross-language compat)

7. Enums and small types (6+ tests):
   - StateType variants
   - ParallelMode variants
   - ExpressionEngineType variants
   - PersistenceBackendType variants
   - ExecutionConfigType variants
   - HooksRef variants (name, config, composite)

8. Settings and edge cases (3+ tests):
   - MachineSettings with max_steps
   - ParallelFallback variants
   - Extra fields via serde flatten

Run: cd sdk/rust && cargo test -p flatmachines --test types_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-expression-suite

**Stage:** S1
**Objective:** Test suite for expression evaluation engine — the simple expression engine that evaluates transition conditions.
**Owned files:** `sdk/rust/flatmachines/tests/expression_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/expressions/simple.py`, `sdk/python/tests/unit/test_type_preservation.py`, `sdk/rust/flatmachines/src/expression.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/expression_test.rs — tests for the expression evaluation engine.

Reference: sdk/python/flatmachines/flatmachines/expressions/simple.py, sdk/python/tests/unit/test_type_preservation.py

The simple expression engine evaluates condition strings like "context.score >= 8" against a context map. It supports: comparison operators (==, !=, >, <, >=, <=), boolean literals (true/false), dot-path variable lookup, string comparison, numeric comparison, None/null handling, and basic boolean logic (and, or, not).

Test categories (aim for 30+ tests):

1. ExpressionEngine trait (3+ tests):
   - Trait exists and can be instantiated
   - evaluate() method signature
   - Returns bool result

2. Numeric comparisons (6+ tests):
   - context.score >= 8 → true when score=10
   - context.score >= 8 → false when score=5
   - context.count == 0
   - context.value < 100
   - context.value > 0
   - Float comparison: context.ratio <= 0.5

3. String comparisons (4+ tests):
   - context.status == "approved"
   - context.status != "rejected"
   - context.name == "hello world" (with spaces)
   - Single vs double quotes

4. Boolean expressions (4+ tests):
   - context.is_done == true
   - context.is_done == false
   - context.flag (truthy check)
   - not context.flag

5. Dot-path variable lookup (4+ tests):
   - context.a.b.c (nested access)
   - context.missing_key → false/error
   - context.list[0] (if supported)
   - input.value access

6. Compound expressions (4+ tests):
   - context.a > 1 and context.b < 10
   - context.x == 1 or context.y == 2
   - not (context.done)
   - Operator precedence

7. Null/None handling (3+ tests):
   - context.missing_field == null
   - context.present_field != null
   - Comparison with null

8. Edge cases (2+ tests):
   - Empty expression string
   - Malformed expression → error

Run: cd sdk/rust && cargo test -p flatmachines --test expression_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-hooks-suite

**Stage:** S1
**Objective:** Test suite for machine hooks — lifecycle callbacks, composite hooks, registry pattern.
**Owned files:** `sdk/rust/flatmachines/tests/hooks_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/hooks.py`, `sdk/python/tests/integration/hooks_registry/test_hooks_registry.py`, `sdk/rust/flatmachines/src/hooks.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/hooks_test.rs — tests for the hooks system.

Reference: sdk/python/flatmachines/flatmachines/hooks.py, sdk/python/tests/integration/hooks_registry/test_hooks_registry.py (20 cases)

Test categories (aim for 25+ tests):

1. MachineHooks trait (5+ tests):
   - Trait can be implemented
   - Default implementations are no-ops
   - on_machine_start receives context
   - on_state_enter receives state name
   - on_error receives error info

2. HooksRegistry (6+ tests):
   - Register hooks by name
   - Retrieve hooks by name
   - Missing hooks → None/error
   - Register multiple hooks
   - Override existing registration
   - List registered names

3. Composite hooks (5+ tests):
   - CompositeHooks chains multiple hooks
   - All hooks called in order
   - on_state_enter fires for each hook
   - on_error fires for each hook
   - Empty composite hooks (no-op)

4. on_action hook (4+ tests):
   - on_action receives action name and context
   - on_action can modify context
   - Unknown action passes through
   - Action hook result used as new context

5. Hook lifecycle (5+ tests):
   - on_machine_start → on_state_enter → on_state_exit → on_transition → on_machine_end
   - on_machine_start called before first state
   - on_machine_end called after final state
   - Hooks receive correct state names
   - Error in hook propagates

Run: cd sdk/rust && cargo test -p flatmachines --test hooks_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-execution-suite

**Stage:** S1
**Objective:** Test suite for execution strategies — default, retry, parallel, MDAP voting.
**Owned files:** `sdk/rust/flatmachines/tests/execution_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/execution.py`, `sdk/python/tests/unit/test_machine_is_the_job.py`, `sdk/rust/flatmachines/src/execution.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/execution_test.rs — tests for execution strategies.

Reference: sdk/python/flatmachines/flatmachines/execution.py, sdk/python/tests/unit/test_machine_is_the_job.py

Test categories (aim for 20+ tests):

1. ExecutionType enum (3+ tests):
   - All variants exist: Default, Retry, Parallel, MdapVoting
   - Deserialization from config
   - Type display

2. AgentExecutor trait (4+ tests):
   - Trait exists and can be implemented
   - execute() method returns AgentResult
   - Mock executor for testing
   - Async execution support

3. Default execution (3+ tests):
   - Single call to agent
   - Result passed through unchanged
   - Error from agent propagates

4. Retry execution (5+ tests):
   - Retry with backoffs [2, 4, 8]
   - Retry succeeds on second attempt
   - Retry exhausted → final error
   - Jitter applied to backoffs
   - Max retries respected

5. Parallel execution (3+ tests):
   - n_samples concurrent calls
   - All results collected
   - Partial failure handling

6. MDAP voting (2+ tests):
   - k_margin consensus
   - max_candidates limit

Run: cd sdk/rust && cargo test -p flatmachines --test execution_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-persistence-suite

**Stage:** S1
**Objective:** Test suite for persistence backend — checkpoint save/load, snapshot management.
**Owned files:** `sdk/rust/flatmachines/tests/persistence_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/persistence.py`, `sdk/python/tests/unit/test_sqlite_checkpoint_backend.py`, `sdk/python/tests/unit/test_sqlite_persistence_config.py`, `sdk/rust/flatmachines/src/persistence.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/persistence_test.rs — tests for persistence backends.

Reference: sdk/python/tests/unit/test_sqlite_checkpoint_backend.py (20 cases), sdk/python/tests/unit/test_sqlite_persistence_config.py (11 cases), sdk/python/flatmachines/flatmachines/persistence.py

Test categories (aim for 25+ tests):

1. PersistenceBackend trait (4+ tests):
   - Trait exists with save/load/list/delete methods
   - All methods are async
   - Returns Result types
   - MachineSnapshot type compatibility

2. Memory persistence backend (8+ tests):
   - Save snapshot
   - Load snapshot by execution_id
   - Load returns None for missing
   - List all snapshots
   - List by machine_name
   - Delete snapshot
   - Delete missing → no error
   - Multiple snapshots for same execution (step progression)

3. Snapshot content (6+ tests):
   - Snapshot preserves all fields
   - Context serialization round-trip
   - tool_loop_state preserved
   - waiting_channel preserved
   - pending_launches preserved
   - config_hash preserved

4. Snapshot listing/filtering (4+ tests):
   - List by machine name
   - List by waiting_channel
   - List empty result
   - Most recent snapshot per execution

5. Edge cases (3+ tests):
   - Empty context
   - Large context (many keys)
   - Special characters in state names

Run: cd sdk/rust && cargo test -p flatmachines --test persistence_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-locking-suite

**Stage:** S1
**Objective:** Test suite for execution locking — NoOpLock behavior, lock trait contract, contention behavior.
**Owned files:** `sdk/rust/flatmachines/tests/locking_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/locking.py`, `sdk/python/tests/unit/test_sqlite_lease_lock.py`, `sdk/rust/flatmachines/src/locking.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/locking_test.rs — tests for execution locking.

Reference: sdk/python/tests/unit/test_sqlite_lease_lock.py (11 cases), sdk/rust/flatmachines/src/locking.rs

Test categories (aim for 15+ tests):

1. ExecutionLock trait (3+ tests):
   - Trait exists with acquire/release
   - Both methods are async
   - acquire returns bool, release returns ()

2. NoOpLock (4+ tests):
   - Always acquires successfully
   - Re-entrant (acquire twice returns true)
   - Release is no-op (doesn't fail)
   - Can be constructed with Default

3. Lock contract expectations (for future impls) (5+ tests):
   - Acquire same key twice → second should fail (for real lock)
   - Release then acquire → should succeed
   - Different keys are independent
   - Lock key is a string identifier
   - Acquire after release succeeds

4. Concurrency (3+ tests):
   - Multiple tasks acquiring different keys → all succeed
   - NoOpLock with concurrent access → no panic
   - Lock is Send + Sync

Run: cd sdk/rust && cargo test -p flatmachines --test locking_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-signals-suite

**Stage:** S1
**Objective:** Test suite for signal/trigger backends — signal storage, retrieval, trigger notification.
**Owned files:** `sdk/rust/flatmachines/tests/signals_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/signals.py`, `sdk/python/tests/unit/test_signals.py`, `sdk/python/tests/unit/test_signals_helpers.py`, `sdk/rust/flatmachines/src/signals.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/signals_test.rs — tests for signal and trigger backends.

Reference: sdk/python/tests/unit/test_signals.py (36 cases), sdk/python/tests/unit/test_signals_helpers.py (7 cases), sdk/python/flatmachines/flatmachines/signals.py

Test categories (aim for 25+ tests):

1. SignalBackend trait (4+ tests):
   - Trait exists with send/receive/list/consume methods
   - All methods are async
   - Signal has id, channel, data, created_at
   - Signal data is JSON value

2. Memory signal backend (8+ tests):
   - Send signal to channel
   - Receive signal from channel
   - Receive returns None when no signals
   - List signals by channel
   - Consume signal (read + delete)
   - Multiple signals on same channel (FIFO)
   - Different channels are isolated
   - Signal data preserved

3. TriggerBackend trait (4+ tests):
   - Trait exists with notify/listen methods
   - NoOp trigger (always succeeds, does nothing)
   - Trigger channel is a string
   - Trigger is fire-and-forget

4. Signal helpers (5+ tests):
   - send_and_notify (send signal + fire trigger)
   - Channel templating (e.g., "approval/{{ task_id }}")
   - List by waiting channel
   - Has channel check
   - Broadcast semantics (multiple waiters)

5. Edge cases (4+ tests):
   - Empty channel name
   - Large signal data
   - Special characters in channel
   - Concurrent signal operations

Run: cd sdk/rust && cargo test -p flatmachines --test signals_test
Report pass/fail/compile-error counts.
```

---

## Worker: rust-flatmachines-backends-suite

**Stage:** S1
**Objective:** Test suite for result backends — in-memory result storage for machine execution.
**Owned files:** `sdk/rust/flatmachines/tests/backends_test.rs`
**Refs:** `sdk/python/flatmachines/flatmachines/backends.py`, `sdk/rust/flatmachines/src/backends.rs`
**Dependencies:** S0

**Prompt:**
```text
Create sdk/rust/flatmachines/tests/backends_test.rs — tests for result backends.

Reference: sdk/python/flatmachines/flatmachines/backends.py, sdk/rust/flatmachines/src/backends.rs

Test categories (aim for 15+ tests):

1. ResultBackend trait (3+ tests):
   - Trait exists with store/retrieve/list/delete methods
   - All methods are async
   - Returns JSON values

2. InMemoryResultBackend (8+ tests):
   - Store result by execution_id
   - Retrieve stored result
   - Retrieve missing → None
   - List all results
   - Delete result
   - Delete missing → no error
   - Multiple results stored
   - Store overwrites existing

3. Result content (4+ tests):
   - Complex JSON values preserved
   - Nested objects
   - Arrays
   - Empty result map

Run: cd sdk/rust && cargo test -p flatmachines --test backends_test
Report pass/fail/compile-error counts.
```

---
