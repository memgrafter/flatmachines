# FlatMachine Parallelization Specification

**Status:** Draft
**Version:** 0.1.0
**Target FlatMachine Version:** 0.4.0

---

## Overview

This specification defines parallelization primitives for FlatMachine, enabling concurrent execution of agents, machines, and actions. The design is:

- **Declarative** - Schema defines what runs in parallel, not how
- **SDK-agnostic** - Works with async/await, futures, promises, threads, goroutines
- **Portable** - Machines run on any SDK via spec-defined fallback behavior
- **Progressive** - Parallelism is an enhancement, not a requirement

---

## Terminology

| Term | Definition |
|------|------------|
| **Task** | A unit of work (agent call, machine invocation, action) that can execute independently |
| **Spawn** | Start a task without waiting for completion |
| **Await** | Block until one or more tasks complete |
| **Branch** | A named task within a parallel block |
| **Region** | An independent state machine running concurrently (HSM) |

---

## Three Parallelization Patterns

### Pattern 1: Parallel Block

Execute multiple tasks concurrently within a single state, wait for completion before transitioning.

**Use case:** "Do these N things at once, collect all results, continue"

```yaml
states:
  analyze_all:
    parallel:
      branches:
        legal:
          agent: legal_analyzer
          input: { doc: "{{ context.document }}" }
        technical:
          agent: tech_analyzer
          input: { doc: "{{ context.document }}" }
        financial:
          agent: finance_analyzer
          input: { doc: "{{ context.document }}" }
      mode: all
    output_to_context:
      legal_review: "{{ parallel.legal }}"
      tech_review: "{{ parallel.technical }}"
      finance_review: "{{ parallel.financial }}"
    transitions:
      - to: synthesize
```

### Pattern 2: Parallel Regions (HSM)

Run independent state machines concurrently within a parent state. Parent transitions when all regions reach final states.

**Use case:** "Run these independent workflows concurrently"

```yaml
states:
  concurrent_approval:
    type: parallel
    regions:
      legal_track:
        states:
          start:
            type: initial
            transitions:
              - to: review
          review:
            agent: legal_reviewer
            output_to_context:
              approved: "{{ output.approved }}"
            transitions:
              - condition: "context.approved"
                to: done
              - to: escalate
          escalate:
            agent: legal_escalation
            transitions:
              - to: done
          done:
            type: final
            output:
              legal_approved: "{{ context.approved }}"

      security_track:
        states:
          start:
            type: initial
            transitions:
              - to: scan
          scan:
            agent: security_scanner
            transitions:
              - to: done
          done:
            type: final
            output:
              security_passed: "{{ output.passed }}"

    # Parent state transitions when ALL regions reach final
    output_to_context:
      legal_result: "{{ regions.legal_track }}"
      security_result: "{{ regions.security_track }}"
    transitions:
      - to: final_decision
```

### Pattern 3: Task Spawning (Deferred Parallel)

Spawn tasks to run in background, continue with other work, await results later.

**Use case:** "Start expensive work early, use results when needed"

```yaml
states:
  kickoff:
    type: initial
    spawn:
      deep_analysis:
        agent: deep_analyzer
        input: { doc: "{{ context.document }}" }
      background_enrichment:
        machine: enrichment_pipeline
        input: { entity: "{{ context.entity }}" }
    transitions:
      - to: quick_validation

  quick_validation:
    agent: quick_validator
    input: { doc: "{{ context.document }}" }
    output_to_context:
      is_valid: "{{ output.valid }}"
    transitions:
      - condition: "not context.is_valid"
        to: rejected
      - to: collect_results

  collect_results:
    await:
      tasks: [deep_analysis, background_enrichment]
      mode: all
    output_to_context:
      analysis: "{{ tasks.deep_analysis }}"
      enrichment: "{{ tasks.background_enrichment }}"
    transitions:
      - to: final_report

  rejected:
    type: final
    cancel: [deep_analysis, background_enrichment]
    output:
      status: rejected
      reason: "{{ context.rejection_reason }}"
```

---

## Schema Definitions

### StateDefinition (Extended)

```typescript
interface StateDefinition {
  // Existing fields
  type?: "initial" | "final" | "parallel";
  agent?: string;
  machine?: string;
  action?: string;
  execution?: ExecutionConfig;
  on_error?: string | Record<string, string>;
  input?: Record<string, any>;
  output_to_context?: Record<string, any>;
  output?: Record<string, any>;
  transitions?: Transition[];
  tool_loop?: boolean;
  sampling?: "single" | "multi";

  // Pattern 1: Parallel Block
  parallel?: ParallelBlock;

  // Pattern 2: Parallel Regions (only when type="parallel")
  regions?: Record<string, RegionDefinition>;

  // Pattern 3: Task Spawning
  spawn?: Record<string, TaskConfig>;
  await?: string[] | AwaitConfig;
  cancel?: string[];
}
```

### ParallelBlock

```typescript
interface ParallelBlock {
  branches: Record<string, TaskConfig>;
  mode?: "all" | "any" | "settled";
  max_concurrency?: number;
  timeout?: number;
  on_timeout?: string;
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `branches` | `Record<string, TaskConfig>` | required | Named tasks to execute |
| `mode` | `"all" \| "any" \| "settled"` | `"all"` | Completion semantics |
| `max_concurrency` | `number` | unlimited | Max simultaneous tasks |
| `timeout` | `number` | none | Overall timeout in seconds |
| `on_timeout` | `string` | error | State to transition to on timeout |

**Mode semantics:**
- `all` - Wait for all branches to succeed. Fail if any fails.
- `any` - Return when first branch succeeds. Cancel others.
- `settled` - Wait for all branches to complete (success or failure). Never fails due to branch failure.

### TaskConfig

```typescript
interface TaskConfig {
  agent?: string;
  machine?: string;
  action?: string;
  input?: Record<string, any>;
  timeout?: number;
  on_error?: "fail" | "ignore" | string;
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agent` | `string` | - | Agent to execute (mutually exclusive) |
| `machine` | `string` | - | Machine to invoke (mutually exclusive) |
| `action` | `string` | - | Action to run (mutually exclusive) |
| `input` | `Record<string, any>` | `{}` | Input mapping (Jinja2 templates) |
| `timeout` | `number` | none | Task-level timeout in seconds |
| `on_error` | `string` | `"fail"` | Error handling: fail parent, ignore, or go to state |

### AwaitConfig

```typescript
interface AwaitConfig {
  tasks: string[];
  mode?: "all" | "any" | "settled";
  timeout?: number;
  on_timeout?: string;
}
```

**Shorthand:** `await: [task1, task2]` is equivalent to `await: { tasks: [task1, task2], mode: "all" }`

### RegionDefinition

```typescript
interface RegionDefinition {
  states: Record<string, StateDefinition>;
  context?: Record<string, any>;
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `states` | `Record<string, StateDefinition>` | required | Nested state machine |
| `context` | `Record<string, any>` | inherits parent | Region-local context initialization |

**Context behavior:**
- Regions inherit parent context by default
- Region-local `context` creates isolated variables
- Regions can read parent context, writes go to region-local
- On completion, region output is available via `{{ regions.<name> }}`

---

## MachineSnapshot (Extended)

```typescript
interface MachineSnapshot {
  // Existing fields
  execution_id: string;
  machine_name: string;
  spec_version: string;
  current_state: string;
  context: Record<string, any>;
  step: number;
  created_at: string;
  event?: string;
  output?: Record<string, any>;
  total_api_calls?: number;
  total_cost?: number;

  // Parallelization additions
  spawned_tasks?: Record<string, TaskState>;
  region_states?: Record<string, RegionSnapshot>;
}

interface TaskState {
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  spawned_at: string;
  spawned_in_state: string;
  completed_at?: string;
  result?: any;
  error?: string;
}

interface RegionSnapshot {
  current_state: string;
  context: Record<string, any>;
  status: "running" | "completed" | "failed";
  output?: any;
}
```

---

## MachineSettings (Extended)

```typescript
interface MachineSettings {
  // Existing fields
  hooks?: string;
  max_steps?: number;

  // Parallelization settings
  parallel_fallback?: "sequential" | "error";
  max_concurrent_tasks?: number;
  task_timeout_default?: number;
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `parallel_fallback` | `"sequential" \| "error"` | `"sequential"` | Behavior when SDK lacks parallelism support |
| `max_concurrent_tasks` | `number` | unlimited | Global limit on concurrent tasks |
| `task_timeout_default` | `number` | none | Default timeout for spawned tasks |

---

## Fallback Semantics

SDKs declare their parallelism capabilities. When a machine uses unsupported features, fallback behavior is determined by `parallel_fallback` setting:

### Sequential Fallback (Default)

When `parallel_fallback: sequential`:

| Feature | Fallback Behavior |
|---------|-------------------|
| `parallel` block | Execute branches sequentially in definition order |
| `spawn` | Execute task immediately, store result |
| `await` | Results already available, no-op |
| `cancel` | No-op (task already completed) |
| `regions` | Execute regions sequentially |

**Result:** Machine produces identical output, just slower.

### Error Fallback

When `parallel_fallback: error`:

| Feature | Fallback Behavior |
|---------|-------------------|
| Any parallel feature | Throw `UnsupportedParallelFeature` error |

**Result:** Fail fast, require capable SDK.

---

## Template Variables

### Parallel Block Results

```yaml
parallel:
  branches:
    a: { agent: foo }
    b: { agent: bar }
output_to_context:
  result_a: "{{ parallel.a }}"           # Full output of branch a
  result_b: "{{ parallel.b.field }}"     # Specific field from branch b
  all_results: "{{ parallel }}"          # Dict of all branch outputs
```

### Spawned Task Results

```yaml
await: [task1, task2]
output_to_context:
  t1_result: "{{ tasks.task1 }}"         # Full output of task1
  t2_field: "{{ tasks.task2.field }}"    # Specific field from task2
```

### Region Results

```yaml
type: parallel
regions:
  region_a: { ... }
  region_b: { ... }
output_to_context:
  a_output: "{{ regions.region_a }}"     # Final output of region_a
  b_output: "{{ regions.region_b }}"     # Final output of region_b
```

---

## Validation Rules

### Mutual Exclusivity

A state may have at most ONE of:
- `agent`
- `machine`
- `action`
- `parallel`
- `regions` (requires `type: parallel`)

### Task References

- `await` and `cancel` may only reference tasks defined in `spawn` of current or ancestor states
- Task names must be unique within a machine execution

### Region Requirements

- Each region must have exactly one `type: initial` state
- Each region must have at least one `type: final` state
- Parent state with `type: parallel` must have `regions` defined
- Parent transitions only evaluated when all regions reach final

### Parallel Block

- At least one branch required
- Branch names must be valid identifiers
- Each branch must have exactly one of: `agent`, `machine`, `action`

---

## Error Handling

### Branch/Task Errors

```yaml
parallel:
  branches:
    critical:
      agent: critical_agent
      on_error: fail              # Fail entire parallel block
    optional:
      agent: optional_agent
      on_error: ignore            # Continue without this result
    recoverable:
      agent: flaky_agent
      on_error: retry_state       # Transition to named state
```

### Timeout Handling

```yaml
parallel:
  branches:
    slow_task:
      agent: slow_agent
      timeout: 30
  timeout: 60                     # Overall timeout
  on_timeout: timeout_handler     # State to handle timeout
```

### Region Errors

When a region transitions to an error state (or has no path to final):

```yaml
type: parallel
regions:
  may_fail:
    states:
      start: { type: initial, transitions: [{ to: risky }] }
      risky:
        agent: risky_agent
        on_error: failed
        transitions: [{ to: done }]
      failed:
        type: final
        output: { success: false, error: "{{ context.error }}" }
      done:
        type: final
        output: { success: true }
on_region_error: handle_failure   # Optional: state when any region fails
```

---

## Examples

### Example 1: Map-Reduce Pattern

```yaml
spec: flatmachine
spec_version: "0.4.0"

data:
  name: map-reduce-analysis

  agents:
    mapper: ./agents/mapper.yml
    reducer: ./agents/reducer.yml

  context:
    documents: "{{ input.documents }}"

  states:
    start:
      type: initial
      transitions:
        - to: map_phase

    map_phase:
      parallel:
        branches:
          doc_0:
            agent: mapper
            input: { doc: "{{ context.documents[0] }}" }
          doc_1:
            agent: mapper
            input: { doc: "{{ context.documents[1] }}" }
          doc_2:
            agent: mapper
            input: { doc: "{{ context.documents[2] }}" }
        mode: settled
      output_to_context:
        mapped_results: "{{ parallel }}"
      transitions:
        - to: reduce_phase

    reduce_phase:
      agent: reducer
      input:
        results: "{{ context.mapped_results }}"
      output_to_context:
        final_analysis: "{{ output }}"
      transitions:
        - to: done

    done:
      type: final
      output:
        analysis: "{{ context.final_analysis }}"
```

### Example 2: Speculative Execution

```yaml
spec: flatmachine
spec_version: "0.4.0"

data:
  name: speculative-search

  context:
    query: "{{ input.query }}"

  states:
    start:
      type: initial
      spawn:
        web_search:
          agent: web_searcher
          input: { query: "{{ context.query }}" }
        db_search:
          agent: db_searcher
          input: { query: "{{ context.query }}" }
        cache_lookup:
          agent: cache_checker
          input: { query: "{{ context.query }}" }
      transitions:
        - to: check_cache

    check_cache:
      await:
        tasks: [cache_lookup]
        timeout: 2
        on_timeout: wait_for_searches
      output_to_context:
        cache_hit: "{{ tasks.cache_lookup.found }}"
        cached_result: "{{ tasks.cache_lookup.result }}"
      transitions:
        - condition: "context.cache_hit"
          to: use_cache
        - to: wait_for_searches

    use_cache:
      type: final
      cancel: [web_search, db_search]
      output:
        result: "{{ context.cached_result }}"
        source: cache

    wait_for_searches:
      await:
        tasks: [web_search, db_search]
        mode: any
      output_to_context:
        search_result: "{{ tasks }}"
      transitions:
        - to: done

    done:
      type: final
      output:
        result: "{{ context.search_result }}"
        source: search
```

### Example 3: Approval Workflow with Parallel Regions

```yaml
spec: flatmachine
spec_version: "0.4.0"

data:
  name: parallel-approval

  context:
    request: "{{ input.request }}"

  states:
    start:
      type: initial
      transitions:
        - to: parallel_review

    parallel_review:
      type: parallel
      regions:
        manager_approval:
          context:
            reviewer_type: manager
          states:
            start:
              type: initial
              transitions:
                - to: review
            review:
              agent: manager_reviewer
              input:
                request: "{{ context.request }}"
                reviewer_type: "{{ context.reviewer_type }}"
              output_to_context:
                decision: "{{ output.approved }}"
                notes: "{{ output.notes }}"
              transitions:
                - to: done
            done:
              type: final
              output:
                approved: "{{ context.decision }}"
                notes: "{{ context.notes }}"

        compliance_check:
          states:
            start:
              type: initial
              transitions:
                - to: automated_check
            automated_check:
              agent: compliance_checker
              input:
                request: "{{ context.request }}"
              output_to_context:
                compliant: "{{ output.compliant }}"
                violations: "{{ output.violations }}"
              transitions:
                - condition: "context.compliant"
                  to: done
                - to: manual_review
            manual_review:
              agent: compliance_reviewer
              input:
                request: "{{ context.request }}"
                violations: "{{ context.violations }}"
              output_to_context:
                compliant: "{{ output.approved }}"
                notes: "{{ output.notes }}"
              transitions:
                - to: done
            done:
              type: final
              output:
                compliant: "{{ context.compliant }}"
                notes: "{{ context.notes }}"

      output_to_context:
        manager_result: "{{ regions.manager_approval }}"
        compliance_result: "{{ regions.compliance_check }}"
      transitions:
        - to: final_decision

    final_decision:
      type: final
      output:
        approved: "{{ context.manager_result.approved and context.compliance_result.compliant }}"
        manager_notes: "{{ context.manager_result.notes }}"
        compliance_notes: "{{ context.compliance_result.notes }}"
```

---

## SDK Implementation Guide

### Required Capabilities

SDKs should declare supported features:

```python
# Python example
class FlatMachine:
    CAPABILITIES = {
        "parallel_block": True,
        "parallel_regions": True,
        "task_spawning": True,
        "max_concurrency_limit": True,
    }
```

### Implementation Mapping

| Schema Feature | Python (asyncio) | TypeScript | Go |
|----------------|------------------|------------|-----|
| `parallel` block | `asyncio.gather()` | `Promise.all()` | `sync.WaitGroup` |
| `spawn` | `asyncio.create_task()` | `Promise` (don't await) | `go func()` |
| `await` | `await task` | `await promise` | `<-channel` |
| `cancel` | `task.cancel()` | `AbortController` | `context.Cancel()` |
| `regions` | Concurrent task per region | Promise per region | Goroutine per region |
| `mode: any` | `asyncio.wait(FIRST_COMPLETED)` | `Promise.race()` | `select` |
| `mode: settled` | `asyncio.gather(return_exceptions=True)` | `Promise.allSettled()` | Collect all |

### Sequential Fallback Implementation

```python
# Python example for sequential fallback
async def execute_parallel_block_sequential(self, block):
    results = {}
    for name, config in block["branches"].items():
        try:
            results[name] = await self.execute_task(config)
        except Exception as e:
            if config.get("on_error") == "ignore":
                results[name] = {"error": str(e)}
            else:
                raise
    return results
```

---

## Changelog

### v0.1.0 (Draft)

- Initial parallelization specification
- Three patterns: parallel block, parallel regions, task spawning
- Spec-defined fallback semantics
- Extended MachineSnapshot for parallel state tracking
