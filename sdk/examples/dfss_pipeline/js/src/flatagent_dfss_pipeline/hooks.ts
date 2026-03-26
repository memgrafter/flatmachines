import type { MachineHooks } from '@memgrafter/flatmachines';

const DESIGNED_TREE: Record<string, Array<[string, boolean, number]>> = {
  'root-000/0': [
    ['fast', true, 1],
    ['fast', false, 10_000],
  ],
  'root-000/0.0': [
    ['slow', false, 0],
    ['slow', false, 0],
  ],
  'root-000/0.1': [
    ['fast', false, 10_000],
  ],
  'root-001/0': [
    ['fast', true, 2],
  ],
  'root-001/0.0': [
    ['fast', true, 1],
  ],
  'root-001/0.0.0': [
    ['slow', false, 0],
  ],
};

export class TaskHooks implements MachineHooks {
  maxDepth: number;
  failRate: number;
  private rngState: number;

  constructor(maxDepth = 3, failRate = 0.15, seed = 7) {
    this.maxDepth = maxDepth;
    this.failRate = failRate;
    this.rngState = Math.max(1, seed >>> 0);
  }

  private random(): number {
    let x = this.rngState;
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    this.rngState = x >>> 0;
    return this.rngState / 0x100000000;
  }

  private randint(min: number, max: number): number {
    return Math.floor(this.random() * (max - min + 1)) + min;
  }

  private choose<T>(arr: T[]): T {
    const idx = this.randint(0, arr.length - 1);
    return arr[idx] as T;
  }

  private designedChildren(context: Record<string, any>): Array<Record<string, any>> {
    const taskId = String(context.task_id ?? '');
    const rootId = String(context.root_id ?? '');
    const depth = Number(context.depth ?? 0);

    const specs = DESIGNED_TREE[taskId] ?? [];
    return specs.map(([resourceClass, hasExpensiveDescendant, distance], idx) => ({
      task_id: `${taskId}.${idx}`,
      root_id: rootId,
      depth: depth + 1,
      resource_class: resourceClass,
      has_expensive_descendant: hasExpensiveDescendant,
      distance_to_nearest_slow_descendant: distance,
    }));
  }

  private randomChildren(context: Record<string, any>): Array<Record<string, any>> {
    const taskId = String(context.task_id ?? '');
    const rootId = String(context.root_id ?? '');
    const depth = Number(context.depth ?? 0);

    if (depth >= this.maxDepth) return [];

    const nChildren = this.randint(0, 2);
    const children: Array<Record<string, any>> = [];

    for (let i = 0; i < nChildren; i += 1) {
      const resourceClass = this.choose(['fast', 'slow']);
      const hint = resourceClass === 'fast' && this.random() < 0.25;
      const distance = resourceClass === 'slow'
        ? 0
        : (hint ? this.randint(1, Math.max(1, this.maxDepth - depth)) : 10_000);

      children.push({
        task_id: `${taskId}.${i}`,
        root_id: rootId,
        depth: depth + 1,
        resource_class: resourceClass,
        has_expensive_descendant: hint,
        distance_to_nearest_slow_descendant: distance,
      });
    }

    return children;
  }

  onAction(action: string, context: Record<string, any>): Record<string, any> {
    if (action !== 'run_task') return context;

    if (this.random() < this.failRate) {
      throw new Error(`transient failure in ${String(context.task_id ?? 'unknown')}`);
    }

    const taskId = String(context.task_id ?? 'unknown');
    const rootId = String(context.root_id ?? '');

    const children = (rootId === 'root-000' || rootId === 'root-001')
      ? this.designedChildren(context)
      : this.randomChildren(context);

    context.children = children;
    context.result = `ok:${taskId}`;
    return context;
  }
}
