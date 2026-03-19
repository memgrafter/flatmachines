# FlatMachine Mermaid Diagram Visualization — Plan

## Goal
Generate Mermaid `stateDiagram-v2` diagrams from FlatMachine YAML configs, capturing all state types, transitions, parallel execution, error handling, and special nodes.

## Node Shape Mapping

| State Feature | Mermaid Representation |
|---|---|
| `type: initial` | `[*] -->` (start marker) |
| `type: final` | `--> [*]` (end marker) |
| `agent:` | State with `<<agent>>` stereotype note |
| `machine:` (single) | State with `<<machine>>` stereotype |
| `machine: [a,b,c]` | Fork/join with parallel sub-states |
| `foreach:` | State with `<<foreach>>` stereotype + note showing expression |
| `launch:` | State with `<<launch>>` stereotype (dashed-style note) |
| `wait_for:` | State with `<<wait_for>>` stereotype + channel name note |
| `action:` | State with `<<action>>` stereotype |
| `execution.type: retry` | Note: "retry [2,8,16]" |
| `on_error:` | Dashed/red transition to error state |

## Transition Rendering

- Conditional transitions: edge label = condition expression (truncated if long)
- Default transition (no condition): unlabeled edge
- Self-loops: transition where `to` == current state name

## Diagram Structure

```
stateDiagram-v2
    [*] --> start

    start --> build_char : current != target
    start --> done : current == target

    state build_char {
        note: agent=builder, retry[2,8,16]
    }
    build_char --> append_char : output matches
    build_char --> build_char : retry

    append_char --> done : complete
    append_char --> build_char : continue

    done --> [*]
```

## Concrete Examples

### Example 1: Hello World Loop (`helloworld/config/machine.yml`)

```mermaid
stateDiagram-v2
    [*] --> start

    start --> done : current == target
    start --> build_char

    state build_char <<agent>>
    note right of build_char : agent: builder\nretry: [2,8,16,35]
    build_char --> append_char : output[0] == expected
    build_char --> build_char

    state append_char <<action>>
    note right of append_char : action: append_char
    append_char --> done : current == target
    append_char --> build_char

    done --> [*]
```

### Example 2: Parallelism Demo (`parallelism/config/machine.yml`)

```mermaid
stateDiagram-v2
    [*] --> start

    start --> parallel_aggregate : type == parallel_aggregation
    start --> foreach_analysis : type == foreach_sentiment
    start --> launch_notifications : type == background_notifications
    start --> done

    state parallel_aggregate <<fork>>
    state parallel_aggregate {
        [*] --> summarizer_machine
        [*] --> sentiment_machine
        summarizer_machine --> [*]
        sentiment_machine --> [*]
    }
    parallel_aggregate --> aggregate_results

    state aggregate_results <<agent>>
    aggregate_results --> extract_aggregated

    state extract_aggregated <<agent>>
    note right of extract_aggregated : retry: [2,8,16,35]
    extract_aggregated --> done

    state foreach_analysis <<foreach>>
    note right of foreach_analysis : foreach: context.texts\nmachine: sentiment_machine
    foreach_analysis --> done

    state launch_notifications <<launch>>
    note right of launch_notifications : launch: notification_machine\n(fire-and-forget)
    launch_notifications --> done

    done --> [*]
```

### Example 3: Error Handling (`error_handling/config/machine.yml`)

```mermaid
stateDiagram-v2
    [*] --> start

    start --> do_work

    state do_work <<agent>>
    note right of do_work : agent: broken
    do_work --> extract_result
    do_work --> handle_error : on_error

    state extract_result <<agent>>
    note right of extract_result : agent: result_extractor\nretry: [2,8,16,35]
    extract_result --> done

    state handle_error <<agent>>
    note right of handle_error : agent: cleanup\nretry: [2,8,16,35]
    handle_error --> extract_summary

    state extract_summary <<agent>>
    extract_summary --> failed

    state done <<final>>
    done --> [*]

    state failed <<final>>
    failed --> [*]
```

### Example 4: Writer-Critic Loop (from d.ts docstring)

```mermaid
stateDiagram-v2
    [*] --> start

    start --> write

    state write <<agent>>
    note right of write : agent: writer\nretry: [2,8,16,35]
    write --> review
    write --> error_state : on_error

    state review <<agent>>
    note right of review : agent: critic
    review --> done : score >= 8
    review --> write

    done --> [*]
```

## Generation Algorithm

### Input
A parsed FlatMachine YAML config (the `data` field).

### Steps

1. **Collect states** — iterate `data.states`
2. **Identify initial/final** — `type: initial` / `type: final`
3. **Emit start marker** — `[*] --> {initial_state}`
4. **For each state**, emit:
   - State declaration with stereotype based on primary feature:
     - `agent` → `<<agent>>`
     - `machine` (string) → `<<machine>>`
     - `machine` (array) → composite state with fork/join
     - `foreach` → `<<foreach>>`
     - `launch` → `<<launch>>`
     - `wait_for` → `<<wait_for>>`
     - `action` → `<<action>>`
   - Note with details (agent name, execution config, channel, etc.)
   - If `on_error` exists → dashed edge to error state(s)
5. **For each transition**, emit:
   - `source --> target : condition` (if condition present)
   - `source --> target` (if no condition — default)
6. **Emit end markers** — `{final_state} --> [*]` for each final state

### Parallel Machine Handling (`machine: [a,b,c]`)

Render as a composite state with fork/join:
```
state state_name {
    [*] --> machine_a
    [*] --> machine_b
    machine_a --> [*]
    machine_b --> [*]
}
```

### Error Edge Styling

Use `:::error` class or note:
```
classDef error stroke:#f00,stroke-dasharray: 5 5
do_work --> handle_error : on_error
class handle_error error
```

## Implementation Location

**File:** `sdk/js/src/flatmachine/mermaid.ts` (or `sdk/python/flatmachines/mermaid.py`)

**Public API:**
```typescript
function toMermaid(config: MachineWrapper): string
```

**Options (stretch):**
```typescript
interface MermaidOptions {
  direction?: 'TB' | 'LR';          // Top-bottom or left-right
  showNotes?: boolean;               // Show detail notes (default: true)
  showErrorEdges?: boolean;          // Show on_error edges (default: true)
  truncateConditions?: number;       // Max chars for condition labels
  highlightLoops?: boolean;          // Color self-loop edges
}
```

## Edge Cases

- **Multiple final states** — each gets `→ [*]`
- **Self-loops** — `state --> state` (valid in mermaid)
- **No transitions** — final states naturally have none
- **Nested machines** — show as `<<machine>>` node (don't recurse into sub-machine by default)
- **launch + transitions** — launch is fire-and-forget, transitions still happen normally
- **wait_for** — show as a special "pause" node with channel annotation
