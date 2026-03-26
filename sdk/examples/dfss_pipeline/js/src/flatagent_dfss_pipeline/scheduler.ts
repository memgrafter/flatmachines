export type Candidate = Record<string, any>;

export class RootState {
  root_id: string;
  admitted = false;
  in_flight = 0;
  pending = 0;
  completed = 0;
  terminal_failures = 0;
  has_pending_expensive = false;

  constructor(rootId: string) {
    this.root_id = rootId;
  }

  get is_done(): boolean {
    return this.pending <= 0 && this.in_flight <= 0;
  }
}

export class ResourcePool {
  name: string;
  capacity: number;
  in_flight = 0;
  gate_open = true;

  constructor(name: string, capacity: number, gateOpen = true) {
    this.name = name;
    this.capacity = capacity;
    this.gate_open = gateOpen;
  }

  get available(): number {
    if (!this.gate_open) return 0;
    return Math.max(0, this.capacity - this.in_flight);
  }
}

export function addCandidate(candidates: Candidate[], item: Candidate): void {
  const workId = item.work_id;
  if (workId && candidates.some((c) => c.work_id === workId)) return;
  candidates.push(item);
}

export function removeCandidate(candidates: Candidate[], workId: string): Candidate | null {
  const idx = candidates.findIndex((c) => c.work_id === workId);
  if (idx < 0) return null;
  const [item] = candidates.splice(idx, 1);
  return item ?? null;
}

export function refreshExpensivePendingFlag(
  root: RootState,
  candidates: Iterable<Candidate>,
  inFlightItems: Iterable<Candidate> | null = null,
): void {
  let expensivePending = [...candidates].some(
    (c) => c.root_id === root.root_id && c.resource_class === 'slow',
  );
  if (!expensivePending && inFlightItems) {
    expensivePending = [...inFlightItems].some(
      (c) => c.root_id === root.root_id && c.resource_class === 'slow',
    );
  }
  root.has_pending_expensive = expensivePending;
}

export function recomputeRootMetrics(
  roots: Record<string, RootState>,
  candidates: Iterable<Candidate>,
  inFlightItems: Iterable<Candidate> | null = null,
): void {
  const counts: Record<string, number> = {};
  for (const c of candidates) {
    const rid = c.root_id;
    if (!rid) continue;
    counts[rid] = (counts[rid] ?? 0) + 1;
  }

  for (const [rid, root] of Object.entries(roots)) {
    root.pending = (counts[rid] ?? 0) + Math.max(0, root.in_flight);
    refreshExpensivePendingFlag(root, candidates, inFlightItems);
  }
}

export function score(item: Candidate, root: RootState, isActive: boolean): number {
  const depth = Number(item.depth ?? 0);
  const pending = Number(Math.max(root.pending, 0));

  let s = 0;
  s += isActive ? 300 : 0;
  s += depth * 18;
  s += Math.max(0, 60 - (pending * 6));
  s += item.resource_class === 'slow' ? 120 : 0;

  if (item.has_expensive_descendant) s += 80;

  const distance = item.distance_to_nearest_slow_descendant;
  if (distance != null) {
    const d = Number(distance);
    if (Number.isFinite(d) && d < 10_000) {
      s += Math.max(0, 36 - (6 * d));
    }
  }

  if (root.has_pending_expensive) s += 20;

  return s;
}

export function pickNext(
  candidates: Candidate[],
  roots: Record<string, RootState>,
  resources: Record<string, ResourcePool>,
  maxActiveRoots: number,
): Candidate | null {
  const activeRootIds = new Set(
    Object.values(roots)
      .filter((r) => r.admitted && !r.is_done)
      .map((r) => r.root_id),
  );

  const runnable = candidates.filter((item) => {
    const pool = resources[String(item.resource_class ?? '')];
    if (!pool) return false;
    if (pool.available <= 0) return false;
    return Boolean(roots[String(item.root_id ?? '')]);
  });

  if (runnable.length === 0) return null;

  const active = runnable.filter((c) => activeRootIds.has(String(c.root_id)));
  const inactive = runnable.filter((c) => !activeRootIds.has(String(c.root_id)));

  let pool = active;
  if (pool.length === 0) {
    if (activeRootIds.size >= maxActiveRoots) return null;
    pool = inactive;
  }

  if (pool.length === 0) return null;

  return pool.reduce((best, c) => {
    if (!best) return c;
    const bestScore = score(best, roots[String(best.root_id)], activeRootIds.has(String(best.root_id)));
    const curScore = score(c, roots[String(c.root_id)], activeRootIds.has(String(c.root_id)));
    if (curScore > bestScore) return c;
    if (curScore === bestScore && String(c.task_id ?? '') > String(best.task_id ?? '')) return c;
    return best;
  }, null as Candidate | null);
}

export async function runScheduler(opts: {
  candidates: Candidate[];
  roots: Record<string, RootState>;
  resources: Record<string, ResourcePool>;
  dispatch: (candidate: Candidate) => Promise<void>;
  maxWorkers: number;
  maxActiveRoots: number;
  idlePoll?: number;
  stop: { isSet(): boolean };
  onTaskDone?: () => void;
}): Promise<void> {
  const {
    candidates,
    roots,
    resources,
    dispatch,
    maxWorkers,
    maxActiveRoots,
    idlePoll = 0.05,
    stop,
    onTaskDone,
  } = opts;

  const active = new Set<Promise<void>>();
  const itemByTask = new Map<Promise<void>, Candidate>();

  while (true) {
    const stopping = stop.isSet();

    while (!stopping && active.size < maxWorkers) {
      const item = pickNext(candidates, roots, resources, maxActiveRoots);
      if (!item) break;

      const removed = removeCandidate(candidates, String(item.work_id ?? ''));
      if (!removed) continue;

      const root = roots[String(item.root_id)];
      root.admitted = true;
      root.in_flight += 1;

      const resourceName = String(item.resource_class);
      resources[resourceName].in_flight += 1;

      const task = dispatch(item)
        .catch(() => {})
        .finally(() => {
          const doneItem = itemByTask.get(task);
          if (!doneItem) return;

          const doneRoot = roots[String(doneItem.root_id)];
          doneRoot.in_flight = Math.max(0, doneRoot.in_flight - 1);

          const doneResourceName = String(doneItem.resource_class);
          resources[doneResourceName].in_flight = Math.max(0, resources[doneResourceName].in_flight - 1);

          active.delete(task);
          itemByTask.delete(task);

          if (onTaskDone) onTaskDone();
        });

      active.add(task);
      itemByTask.set(task, item);
    }

    if (active.size === 0) {
      if (candidates.length === 0 || stopping) return;
      await new Promise((resolve) => setTimeout(resolve, idlePoll * 1000));
      continue;
    }

    await Promise.race([...active]);
  }
}
