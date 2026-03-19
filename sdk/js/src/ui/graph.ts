import { MachineConfig, State } from '../types';

// ---------------------------------------------------------------------------
// IR types
// ---------------------------------------------------------------------------

export type NodeKind =
  | 'initial'
  | 'final'
  | 'agent'
  | 'machine'
  | 'parallel'
  | 'foreach'
  | 'launch'
  | 'wait_for'
  | 'action';

export type EdgeKind = 'transition' | 'error' | 'fork' | 'join';

export interface NodeDetail {
  agent?: string;
  machines?: string[];
  execution?: State['execution'];
  channel?: string;
  foreachExpr?: string;
  foreachAs?: string;
  launchTargets?: string[];
  actionName?: string;
  onError?: string | Record<string, string>;
  output?: Record<string, any>;
  mode?: 'settled' | 'any';
  timeout?: number;
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  detail: NodeDetail;
}

export interface GraphEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  label?: string;
}

export interface MachineGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata: {
    name?: string;
    settings?: MachineConfig['data']['settings'];
  };
}

// ---------------------------------------------------------------------------
// Classification — priority order determines kind when multiple fields present
// ---------------------------------------------------------------------------

function classifyState(state: State): NodeKind {
  if (state.type === 'initial') return 'initial';
  if (state.type === 'final') return 'final';
  if (state.foreach) return 'foreach';
  if (state.launch) return 'launch';
  if (state.wait_for) return 'wait_for';
  if (Array.isArray(state.machine)) return 'parallel';
  if (state.machine) return 'machine';
  if (state.action) return 'action';
  if (state.agent) return 'agent';
  // Fallback for bare routing states (initial without type annotation, etc.)
  return 'initial';
}

// ---------------------------------------------------------------------------
// Extract
// ---------------------------------------------------------------------------

export function extractGraph(config: MachineConfig): MachineGraph {
  const states = config.data.states;
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  for (const [id, state] of Object.entries(states)) {
    const kind = classifyState(state);

    // Build detail
    const detail: NodeDetail = {};
    if (state.agent) detail.agent = state.agent;
    if (state.action) detail.actionName = state.action;
    if (state.execution) detail.execution = state.execution;
    if (state.on_error) detail.onError = state.on_error;
    if (state.mode) detail.mode = state.mode;
    if (state.timeout) detail.timeout = state.timeout;
    if (state.output && kind === 'final') detail.output = state.output;

    if (state.wait_for) detail.channel = state.wait_for;

    if (state.foreach) {
      detail.foreachExpr = state.foreach;
      detail.foreachAs = state.as ?? 'item';
      // foreach always targets a machine
      if (typeof state.machine === 'string') detail.machines = [state.machine];
    }

    if (state.launch) {
      detail.launchTargets = Array.isArray(state.launch) ? state.launch : [state.launch];
    }

    if (Array.isArray(state.machine)) {
      detail.machines = state.machine.map(m =>
        typeof m === 'string' ? m : m.name
      );
    } else if (typeof state.machine === 'string' && !state.foreach) {
      detail.machines = [state.machine];
    }

    nodes.push({ id, kind, label: id, detail });

    // Transition edges
    if (state.transitions) {
      for (const t of state.transitions) {
        edges.push({
          from: id,
          to: t.to,
          kind: 'transition',
          ...(t.condition ? { label: t.condition } : {}),
        });
      }
    }

    // Error edges
    if (state.on_error) {
      if (typeof state.on_error === 'string') {
        edges.push({ from: id, to: state.on_error, kind: 'error', label: 'on_error' });
      } else {
        for (const [errType, target] of Object.entries(state.on_error)) {
          edges.push({ from: id, to: target, kind: 'error', label: errType === 'default' ? 'on_error' : errType });
        }
      }
    }

    // Fork/join edges for parallel machines
    if (kind === 'parallel' && detail.machines) {
      for (const m of detail.machines) {
        edges.push({ from: id, to: m, kind: 'fork' });
        edges.push({ from: m, to: id, kind: 'join' });
      }
    }
  }

  return {
    nodes,
    edges,
    metadata: {
      name: config.data.name,
      settings: config.data.settings,
    },
  };
}
