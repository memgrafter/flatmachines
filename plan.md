# FlatMachine UI Visualization — Plan

## Goal
Provide a general-purpose UI adapter system for visualizing FlatMachine configs, with Mermaid as the first supported frontend.

## Architecture

```
FlatMachine YAML
       │
       ▼
  ┌─────────────┐
  │ extractGraph │  Parse states/transitions into neutral IR
  └─────────────┘
       │
       ▼
  MachineGraph (IR)
       │
       ├──► MermaidAdapter     → string (stateDiagram-v2 markdown)
       ├──► DotAdapter         → string (Graphviz DOT)
       ├──► ReactFlowAdapter   → { nodes[], edges[] }
       ├──► AsciiAdapter       → string (terminal box-drawing)
       └──► JSONAdapter        → serializable graph object
```

## File Layout

```
sdk/js/src/flatmachine/ui/
  graph.ts          # MachineGraph IR types + extractGraph(config)
  adapter.ts        # UIAdapter<T> interface
  mermaid.ts        # MermaidAdapter (first implementation)
  index.ts          # re-exports
```

---

## Intermediate Representation (IR)

### MachineGraph

```typescript
interface MachineGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: { name?: string; settings?: MachineSettings };
}
```

### GraphNode

```typescript
type NodeKind =
  | 'initial' | 'final'
  | 'agent' | 'machine' | 'parallel'
  | 'foreach' | 'launch' | 'wait_for' | 'action';

interface GraphNode {
  id: string;                          // state name
  kind: NodeKind;
  label: string;                       // display label (= id by default)
  detail?: {
    agent?: string;                    // agent name
    machines?: string[];               // machine names (parallel)
    execution?: ExecutionConfig;       // retry/parallel/mdap config
    channel?: string;                  // wait_for channel
    foreachExpr?: string;              // foreach expression
    foreachAs?: string;                // iteration variable
    launchTargets?: string[];          // launched machine names
    actionName?: string;               // action hook name
    onError?: string | Record<string, string>;
    output?: Record<string, any>;      // final state output
  };
}
```

### GraphEdge

```typescript
type EdgeKind = 'transition' | 'error' | 'fork' | 'join';

interface GraphEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;                      // condition text or "on_error"
}
```

---

## UIAdapter Interface

```typescript
interface UIAdapter<T> {
  render(graph: MachineGraph, options?: Record<string, any>): T;
}
```

Each adapter decides how to map `NodeKind`, `EdgeKind`, and `detail` to its output format. The IR is renderer-agnostic — adapters own all presentation decisions.

---

## extractGraph Algorithm

### Input
A parsed FlatMachine config (`MachineWrapper`).

### Steps

1. **Collect states** — iterate `data.states`
2. **Classify each state** into a `NodeKind`:
   - `type: initial` → `'initial'`
   - `type: final` → `'final'`
   - `machine` as `string[]` → `'parallel'`
   - `machine` as `string` → `'machine'`
   - `foreach` → `'foreach'`
   - `launch` → `'launch'`
   - `wait_for` → `'wait_for'`
   - `action` → `'action'`
   - `agent` → `'agent'`
   - (priority order — first match wins)
3. **Build detail** from state fields (agent name, execution config, channel, etc.)
4. **Build edges** from `transitions[]`:
   - Conditional: `{ from, to, kind: 'transition', label: condition }`
   - Default (no condition): `{ from, to, kind: 'transition' }`
5. **Build error edges** from `on_error`:
   - String: single `{ from, to: on_error, kind: 'error', label: 'on_error' }`
   - Record: one edge per error type
6. **Build fork/join edges** for parallel machines (`machine: [a,b,c]`):
   - Fork edges: `{ from: state, to: machine_i, kind: 'fork' }`
   - Join edges: `{ from: machine_i, to: state, kind: 'join' }`
7. **Return** `{ nodes, edges, metadata: { name: data.name, settings: data.settings } }`

---

## Mermaid Adapter — Node/Edge Mapping

### Node Rendering

| `NodeKind` | Mermaid Representation |
|---|---|
| `initial` | `[*] --> {id}` (start marker) |
| `final` | `{id} --> [*]` (end marker) |
| `agent` | `state {id} <<agent>>` + note |
| `machine` | `state {id} <<machine>>` + note |
| `parallel` | Composite state with fork/join children |
| `foreach` | `state {id} <<foreach>>` + note with expression |
| `launch` | `state {id} <<launch>>` + note (fire-and-forget) |
| `wait_for` | `state {id} <<wait_for>>` + note with channel |
| `action` | `state {id} <<action>>` + note |

### Edge Rendering

| `EdgeKind` | Mermaid Representation |
|---|---|
| `transition` | `from --> to : label` |
| `error` | `from --> to : on_error` (with `:::error` class) |
| `fork` | Inside composite: `[*] --> child` |
| `join` | Inside composite: `child --> [*]` |

### Notes

Detail fields rendered as `note right of {id}`:
- `agent: {name}` / `action: {name}` / `channel: {channel}`
- `retry: [{backoffs}]` / `parallel: n={n_samples}` / `mdap`
- `foreach: {expr}` / `launch: {targets}`

### MermaidOptions

```typescript
interface MermaidOptions {
  direction?: 'TB' | 'LR';            // Diagram direction (default: TB)
  showNotes?: boolean;                 // Show detail notes (default: true)
  showErrorEdges?: boolean;            // Show on_error edges (default: true)
  truncateConditions?: number;         // Max chars for condition labels
  highlightLoops?: boolean;            // Color self-loop edges
}
```

### Error Edge Styling

```
classDef error stroke:#f00,stroke-dasharray: 5 5
do_work --> handle_error : on_error
class handle_error error
```

---

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

---

## Edge Cases

- **Multiple final states** — each gets its own `→ [*]` (or equivalent per adapter)
- **Self-loops** — edge where `from == to`; IR captures this, adapters render per their format
- **No transitions** — final states naturally have none
- **Nested machines** — `machine` kind node; IR does NOT recurse into sub-machine configs (adapters can opt in)
- **launch + transitions** — launch is fire-and-forget; normal transitions still emitted
- **wait_for** — pause/checkpoint semantics; adapter decides visual treatment
- **Kind priority** — when a state has multiple features (e.g. `agent` + `machine`), classification uses priority order from the algorithm above

## Future Adapters

| Adapter | Output | Use Case |
|---|---|---|
| `DotAdapter` | Graphviz DOT string | PDF/SVG export, CI pipelines |
| `ReactFlowAdapter` | `{ nodes[], edges[] }` | Interactive web UI |
| `AsciiAdapter` | Box-drawing string | Terminal/CLI output |
| `JSONAdapter` | Serializable object | API responses, tooling integration |

Each adapter implements `UIAdapter<T>` and maps the same `MachineGraph` IR to its target format. Adding a new frontend = one new file, no changes to `extractGraph` or the IR.
