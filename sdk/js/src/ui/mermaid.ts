import { MachineGraph, GraphNode, GraphEdge, NodeKind } from './graph';
import { UIAdapter } from './adapter';

export interface MermaidOptions {
  direction?: 'TB' | 'LR';
  showNotes?: boolean;
  showErrorEdges?: boolean;
  truncateConditions?: number;
  highlightLoops?: boolean;
}

const DEFAULTS: Required<MermaidOptions> = {
  direction: 'TB',
  showNotes: true,
  showErrorEdges: true,
  truncateConditions: 60,
  highlightLoops: true,
};

export class MermaidAdapter implements UIAdapter<string> {
  render(graph: MachineGraph, options?: MermaidOptions): string {
    const opts = { ...DEFAULTS, ...options };
    const lines: string[] = [];
    const indent = '    ';

    lines.push('stateDiagram-v2');
    if (opts.direction === 'LR') {
      lines.push(`${indent}direction LR`);
    }

    // Error class definition
    if (opts.showErrorEdges && graph.edges.some(e => e.kind === 'error')) {
      lines.push(`${indent}classDef error stroke:#f44,stroke-dasharray:5 5`);
    }

    lines.push('');

    // Start marker
    const initial = graph.nodes.find(n => n.kind === 'initial');
    if (initial) {
      lines.push(`${indent}[*] --> ${initial.id}`);
      lines.push('');
    }

    // Group edges by source for ordered output
    const edgesBySource = new Map<string, GraphEdge[]>();
    for (const edge of graph.edges) {
      const list = edgesBySource.get(edge.from) ?? [];
      list.push(edge);
      edgesBySource.set(edge.from, list);
    }

    // Render each node + its outgoing edges
    for (const node of graph.nodes) {
      this.renderNode(node, graph, opts, lines, indent);

      // Transition edges
      const outEdges = edgesBySource.get(node.id) ?? [];
      for (const edge of outEdges) {
        if (edge.kind === 'fork' || edge.kind === 'join') continue; // handled inside composite
        if (edge.kind === 'error' && !opts.showErrorEdges) continue;

        const label = this.formatLabel(edge, opts);
        const arrow = edge.kind === 'error' ? '-->' : '-->';
        if (label) {
          lines.push(`${indent}${edge.from} ${arrow} ${edge.to} : ${label}`);
        } else {
          lines.push(`${indent}${edge.from} ${arrow} ${edge.to}`);
        }
      }

      // Apply error class to error-target nodes
      if (opts.showErrorEdges) {
        for (const edge of outEdges) {
          if (edge.kind === 'error') {
            lines.push(`${indent}class ${edge.to} error`);
          }
        }
      }

      lines.push('');
    }

    // End markers for final states
    const finals = graph.nodes.filter(n => n.kind === 'final');
    for (const f of finals) {
      lines.push(`${indent}${f.id} --> [*]`);
    }

    return lines.join('\n').trimEnd() + '\n';
  }

  private renderNode(
    node: GraphNode,
    graph: MachineGraph,
    opts: Required<MermaidOptions>,
    lines: string[],
    indent: string,
  ): void {
    const { id, kind, detail } = node;

    if (kind === 'initial' || kind === 'final') {
      // No stereotype needed — start/end markers handle these
      return;
    }

    if (kind === 'parallel' && detail.machines?.length) {
      // Composite state with fork/join
      const stereotype = this.stereotype(kind);
      lines.push(`${indent}state ${id} ${stereotype}`);
      lines.push(`${indent}state ${id} {`);
      for (const m of detail.machines) {
        lines.push(`${indent}${indent}[*] --> ${m}`);
      }
      for (const m of detail.machines) {
        lines.push(`${indent}${indent}${m} --> [*]`);
      }
      lines.push(`${indent}}`);
    } else {
      const stereotype = this.stereotype(kind);
      lines.push(`${indent}state ${id} ${stereotype}`);
    }

    // Notes
    if (opts.showNotes) {
      const noteLines = this.buildNoteLines(node);
      if (noteLines.length > 0) {
        lines.push(`${indent}note right of ${id} : ${noteLines.join('\\n')}`);
      }
    }
  }

  private stereotype(kind: NodeKind): string {
    const map: Partial<Record<NodeKind, string>> = {
      agent: '<<agent>>',
      machine: '<<machine>>',
      parallel: '<<parallel>>',
      foreach: '<<foreach>>',
      launch: '<<launch>>',
      wait_for: '<<wait_for>>',
      action: '<<action>>',
    };
    return map[kind] ?? '';
  }

  private buildNoteLines(node: GraphNode): string[] {
    const { kind, detail } = node;
    const parts: string[] = [];

    if (detail.agent) parts.push(`agent: ${detail.agent}`);
    if (detail.actionName) parts.push(`action: ${detail.actionName}`);
    if (detail.channel) parts.push(`channel: ${detail.channel}`);

    if (detail.execution) {
      const ex = detail.execution;
      if (ex.type === 'retry' && ex.backoffs) {
        parts.push(`retry: [${ex.backoffs.join(',')}]`);
      } else if (ex.type === 'parallel') {
        parts.push(`parallel: n=${ex.n_samples ?? '?'}`);
      } else if (ex.type === 'mdap_voting') {
        parts.push(`mdap_voting: k=${ex.k_margin ?? '?'}`);
      }
    }

    if (kind === 'foreach') {
      parts.push(`foreach: ${detail.foreachExpr}`);
      if (detail.machines?.length) parts.push(`machine: ${detail.machines[0]}`);
    }

    if (kind === 'launch' && detail.launchTargets?.length) {
      parts.push(`launch: ${detail.launchTargets.join(', ')}`);
      parts.push('(fire-and-forget)');
    }

    if (kind === 'machine' && detail.machines?.length) {
      parts.push(`machine: ${detail.machines[0]}`);
    }

    if (detail.mode && detail.mode !== 'settled') parts.push(`mode: ${detail.mode}`);
    if (detail.timeout) parts.push(`timeout: ${detail.timeout}s`);

    return parts;
  }

  private formatLabel(edge: GraphEdge, opts: Required<MermaidOptions>): string | undefined {
    if (!edge.label) return undefined;
    const max = opts.truncateConditions;
    if (edge.label.length > max) {
      return edge.label.slice(0, max - 3) + '...';
    }
    return edge.label;
  }
}

/**
 * Convenience function: config → mermaid string.
 */
export { extractGraph } from './graph';
import { extractGraph } from './graph';
import { MachineConfig } from '../types';

export function toMermaid(config: MachineConfig, options?: MermaidOptions): string {
  const graph = extractGraph(config);
  return new MermaidAdapter().render(graph, options);
}
