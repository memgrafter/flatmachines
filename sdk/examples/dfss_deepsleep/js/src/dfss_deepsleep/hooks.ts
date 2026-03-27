import type { MachineHooks, SQLiteCheckpointBackend, SQLiteSignalBackend, SQLiteWorkBackend } from '@memgrafter/flatmachines';

const NO_SLOW_DISTANCE = 10_000;
const WORKER_ID = 'scheduler';

type RootState = {
  admitted: boolean;
  in_flight: number;
  pending: number;
  completed: number;
  terminal_failures: number;
  has_pending_expensive: boolean;
};

type Candidate = {
  work_id: string;
  task_id: string;
  root_id: string;
  depth: number;
  resource_class: 'fast' | 'slow' | string;
  has_expensive_descendant: boolean;
  distance_to_nearest_slow_descendant: number;
  attempts: number;
};

export class DeepSleepHooks implements MachineHooks {
  maxDepth: number;
  failRate: number;
  maxAttempts: number;
  gateInterval: number;
  poolName: string;

  private workBackend: SQLiteWorkBackend;
  private signalBackend: SQLiteSignalBackend;
  private checkpointBackend?: SQLiteCheckpointBackend;
  private rngState: number;

  constructor(opts: {
    maxDepth: number;
    failRate: number;
    seed: number;
    maxAttempts: number;
    gateInterval: number;
    poolName: string;
    workBackend: SQLiteWorkBackend;
    signalBackend: SQLiteSignalBackend;
    checkpointBackend?: SQLiteCheckpointBackend;
  }) {
    this.maxDepth = opts.maxDepth;
    this.failRate = opts.failRate;
    this.maxAttempts = opts.maxAttempts;
    this.gateInterval = opts.gateInterval;
    this.poolName = opts.poolName;
    this.workBackend = opts.workBackend;
    this.signalBackend = opts.signalBackend;
    this.checkpointBackend = opts.checkpointBackend;
    this.rngState = Math.max(1, opts.seed >>> 0);
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    switch (action) {
      case 'seed_work':
        return this.seedWork(context);
      case 'hydrate_candidates':
        return this.hydrateCandidates(context);
      case 'pick_batch':
        return this.pickBatch(context);
      case 'claim_batch':
        return this.claimBatch(context);
      case 'settle_results':
        return this.settleResults(context);
      case 'check_done':
        return this.checkDone(context);
      case 'release_stale':
        return this.releaseStale(context);
      case 'report_and_cleanup':
        return this.reportAndCleanup(context);
      case 'run_task':
        return this.runTask(context);
      case 'signal_ready':
        return this.signalReady(context);
      default:
        return context;
    }
  }

  onStateExit(state: string, context: Record<string, any>, output: any): any {
    // Temporary parity workaround for single-segment output mapping ("output").
    if (state === 'dispatch') {
      context.batch_results = output;
    }
    return output;
  }

  private random(): number {
    // xorshift32
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

  private db(): any {
    return (this.workBackend as any).db;
  }

  private pool() {
    return this.workBackend.pool(this.poolName);
  }

  private normalizeRoot(input: any): RootState {
    return {
      admitted: Boolean(input?.admitted ?? false),
      in_flight: Number(input?.in_flight ?? 0),
      pending: Number(input?.pending ?? 0),
      completed: Number(input?.completed ?? 0),
      terminal_failures: Number(input?.terminal_failures ?? 0),
      has_pending_expensive: Boolean(input?.has_pending_expensive ?? false),
    };
  }

  private rootsFromContext(context: Record<string, any>): Record<string, RootState> {
    const roots = context.roots;
    if (!roots || typeof roots !== 'object') {
      return {};
    }
    const normalized: Record<string, RootState> = {};
    for (const [key, value] of Object.entries(roots)) {
      normalized[key] = this.normalizeRoot(value);
    }
    return normalized;
  }

  private rootDone(root: RootState): boolean {
    return root.pending <= 0 && root.in_flight <= 0;
  }

  private initialRootTask(rootId: string, maxDepth: number): Record<string, any> {
    if (rootId === 'root-000') {
      return {
        task_id: 'root-000/0',
        root_id: rootId,
        depth: 0,
        resource_class: 'fast',
        has_expensive_descendant: true,
        distance_to_nearest_slow_descendant: Math.min(2, maxDepth),
      };
    }

    const resourceClass = this.random() < 0.4 ? 'slow' : 'fast';
    const hint = resourceClass === 'fast' && this.random() < 0.35;
    const distance = resourceClass === 'slow'
      ? 0
      : (hint ? this.randint(1, Math.max(1, maxDepth)) : NO_SLOW_DISTANCE);

    return {
      task_id: `${rootId}/0`,
      root_id: rootId,
      depth: 0,
      resource_class: resourceClass,
      has_expensive_descendant: hint,
      distance_to_nearest_slow_descendant: distance,
    };
  }

  private candidateFromRow(row: any): Candidate | null {
    try {
      const data = JSON.parse(String(row.data));
      if (!data || typeof data !== 'object') {
        return null;
      }
      if (!data.task_id || !data.root_id) {
        return null;
      }
      return {
        work_id: String(row.item_id),
        task_id: String(data.task_id),
        root_id: String(data.root_id),
        depth: Number(data.depth ?? 0),
        resource_class: String(data.resource_class ?? 'fast'),
        has_expensive_descendant: Boolean(data.has_expensive_descendant ?? false),
        distance_to_nearest_slow_descendant: Number(data.distance_to_nearest_slow_descendant ?? NO_SLOW_DISTANCE),
        attempts: Number(row.attempts ?? 0),
      };
    } catch {
      return null;
    }
  }

  private loadPendingCandidates(): Candidate[] {
    const rows = this.db().prepare(`
      SELECT item_id, data, attempts
      FROM work_pool
      WHERE pool_name = ? AND status = 'pending'
      ORDER BY created_at ASC
    `).all(this.poolName);

    const out: Candidate[] = [];
    for (const row of rows) {
      const item = this.candidateFromRow(row);
      if (item) {
        out.push(item);
      }
    }
    return out;
  }

  private claimById(workId: string): Candidate | null {
    const now = new Date().toISOString();
    this.db().exec('BEGIN IMMEDIATE');
    try {
      const updated = this.db().prepare(`
        UPDATE work_pool
        SET status = 'claimed', claimed_by = ?, claimed_at = ?, attempts = attempts + 1
        WHERE pool_name = ? AND item_id = ? AND status = 'pending'
      `).run(WORKER_ID, now, this.poolName, workId);

      if (Number(updated.changes ?? 0) === 0) {
        this.db().exec('COMMIT');
        return null;
      }

      const row = this.db().prepare('SELECT item_id, data, attempts FROM work_pool WHERE item_id = ?').get(workId);
      this.db().exec('COMMIT');
      return row ? this.candidateFromRow(row) : null;
    } catch (error) {
      this.db().exec('ROLLBACK');
      throw error;
    }
  }

  private unfinishedCount(): number {
    const row = this.db().prepare(`
      SELECT COUNT(*) AS c
      FROM work_pool
      WHERE pool_name = ? AND status IN ('pending', 'claimed')
    `).get(this.poolName);
    return Number(row?.c ?? 0);
  }

  private rootTerminalFailures(): Record<string, number> {
    const rows = this.db().prepare(`
      SELECT data
      FROM work_pool
      WHERE pool_name = ? AND status = 'poisoned'
    `).all(this.poolName);

    const out: Record<string, number> = {};
    for (const row of rows) {
      try {
        const data = JSON.parse(String(row.data));
        const rootId = String(data.root_id ?? '');
        if (!rootId) {
          continue;
        }
        out[rootId] = (out[rootId] ?? 0) + 1;
      } catch {
        // ignore bad rows
      }
    }
    return out;
  }

  private recomputeRootMetrics(
    roots: Record<string, RootState>,
    candidates: Candidate[],
    inFlightItems: Candidate[] = [],
  ): void {
    const counts: Record<string, number> = {};

    for (const item of candidates) {
      counts[item.root_id] = (counts[item.root_id] ?? 0) + 1;
    }

    for (const [rootId, root] of Object.entries(roots)) {
      root.pending = (counts[rootId] ?? 0) + Math.max(0, root.in_flight);

      let expensivePending = candidates.some((c) => c.root_id === rootId && c.resource_class === 'slow');
      if (!expensivePending) {
        expensivePending = inFlightItems.some((c) => c.root_id === rootId && c.resource_class === 'slow');
      }
      root.has_pending_expensive = expensivePending;
    }
  }

  private score(item: Candidate, root: RootState, isActive: boolean): number {
    let score = 0;
    score += isActive ? 300 : 0;
    score += item.depth * 18;
    score += Math.max(0, 60 - (Math.max(root.pending, 0) * 6));
    score += item.resource_class === 'slow' ? 120 : 0;

    if (item.has_expensive_descendant) {
      score += 80;
    }

    if (item.distance_to_nearest_slow_descendant < NO_SLOW_DISTANCE) {
      score += Math.max(0, 36 - (6 * item.distance_to_nearest_slow_descendant));
    }

    if (root.has_pending_expensive) {
      score += 20;
    }

    return score;
  }

  private maybeToggleGate(context: Record<string, any>): void {
    const resources = context.resources;
    if (!resources || typeof resources !== 'object' || !resources.slow) {
      return;
    }

    const now = Date.now() / 1000;
    const last = Number(context._last_gate_toggle ?? now);
    if ((now - last) >= this.gateInterval) {
      resources.slow.gate_open = !Boolean(resources.slow.gate_open);
      context._last_gate_toggle = now;
      console.log(`  ⚡ slow gate -> ${resources.slow.gate_open ? 'OPEN' : 'CLOSED'}`);
    }
  }

  private async seedWork(context: Record<string, any>): Promise<Record<string, any>> {
    const nRoots = Number(context.n_roots ?? 8);
    const maxDepth = Number(context.max_depth ?? this.maxDepth);
    const rootIds = Array.from({ length: nRoots }, (_, i) => `root-${String(i).padStart(3, '0')}`);

    for (const rootId of rootIds) {
      await this.pool().push(this.initialRootTask(rootId, maxDepth), { max_retries: this.maxAttempts });
    }

    context.root_ids = rootIds;
    context.roots = Object.fromEntries(rootIds.map((rid) => [rid, this.normalizeRoot({})]));
    context.resources = {
      fast: { capacity: 4, in_flight: 0, gate_open: true },
      slow: { capacity: 2, in_flight: 0, gate_open: true },
    };
    context._last_gate_toggle = Date.now() / 1000;

    console.log(`Seeded roots=${nRoots}, max_depth=${maxDepth}, max_attempts=${this.maxAttempts}`);
    return context;
  }

  private async hydrateCandidates(context: Record<string, any>): Promise<Record<string, any>> {
    const candidates = this.loadPendingCandidates();
    context._candidates = candidates;

    const roots = this.rootsFromContext(context);
    const rootIds = Array.isArray(context.root_ids) ? context.root_ids : [];

    for (const rootId of rootIds) {
      if (!roots[rootId]) {
        roots[rootId] = this.normalizeRoot({});
      }
    }

    for (const candidate of candidates) {
      if (!roots[candidate.root_id]) {
        roots[candidate.root_id] = this.normalizeRoot({});
      }
    }

    const terminalFailures = this.rootTerminalFailures();
    for (const [rootId, count] of Object.entries(terminalFailures)) {
      if (roots[rootId]) {
        roots[rootId].terminal_failures = count;
      }
    }

    this.recomputeRootMetrics(roots, candidates);
    context.roots = roots;

    return context;
  }

  private pickBatch(context: Record<string, any>): Record<string, any> {
    const rawCandidates = Array.isArray(context._candidates) ? context._candidates : [];
    const candidates: Candidate[] = rawCandidates.filter((c: any) => c && typeof c === 'object');

    const batchSize = Math.max(0, Number(context.batch_size ?? 4));
    const maxActiveRoots = Math.max(1, Number(context.max_active_roots ?? 3));

    const roots = this.rootsFromContext(context);
    const resources = context.resources && typeof context.resources === 'object'
      ? context.resources
      : {
          fast: { capacity: 4, in_flight: 0, gate_open: true },
          slow: { capacity: 2, in_flight: 0, gate_open: true },
        };

    this.maybeToggleGate(context);

    this.recomputeRootMetrics(roots, candidates);

    const available = [...candidates];
    const batch: Candidate[] = [];

    for (let i = 0; i < batchSize; i += 1) {
      const activeRootIds = new Set(
        Object.entries(roots)
          .filter(([, root]) => root.admitted && !this.rootDone(root))
          .map(([rootId]) => rootId),
      );

      const runnable = available.filter((candidate) => {
        const resource = resources[candidate.resource_class];
        if (!resource) return false;
        if (!resource.gate_open) return false;
        return Number(resource.in_flight ?? 0) < Number(resource.capacity ?? 0);
      });

      if (runnable.length === 0) {
        break;
      }

      const active = runnable.filter((candidate) => activeRootIds.has(candidate.root_id));
      const inactive = runnable.filter((candidate) => !activeRootIds.has(candidate.root_id));

      let pool = active;
      if (pool.length === 0) {
        if (activeRootIds.size >= maxActiveRoots) {
          break;
        }
        pool = inactive;
      }

      if (pool.length === 0) {
        break;
      }

      const picked = pool.reduce((best, candidate) => {
        if (!best) return candidate;
        const candidateScore = this.score(candidate, roots[candidate.root_id], activeRootIds.has(candidate.root_id));
        const bestScore = this.score(best, roots[best.root_id], activeRootIds.has(best.root_id));
        if (candidateScore > bestScore) return candidate;
        if (candidateScore === bestScore && candidate.task_id > best.task_id) return candidate;
        return best;
      }, null as Candidate | null);

      if (!picked) {
        break;
      }

      const idx = available.findIndex((c) => c.work_id === picked.work_id);
      if (idx >= 0) {
        available.splice(idx, 1);
      }

      roots[picked.root_id] = roots[picked.root_id] ?? this.normalizeRoot({});
      roots[picked.root_id].admitted = true;
      roots[picked.root_id].in_flight += 1;

      if (resources[picked.resource_class]) {
        resources[picked.resource_class].in_flight = Number(resources[picked.resource_class].in_flight ?? 0) + 1;
      }

      batch.push(picked);
      this.recomputeRootMetrics(roots, available, batch);
    }

    context.batch = batch;
    context._candidates = available;
    context.roots = roots;
    context.resources = resources;
    context.all_done = available.length === 0 && batch.length === 0 && Object.values(roots).every((root) => this.rootDone(root));

    return context;
  }

  private async claimBatch(context: Record<string, any>): Promise<Record<string, any>> {
    const batch = Array.isArray(context.batch) ? context.batch as Candidate[] : [];
    const claimed: Candidate[] = [];

    for (const item of batch) {
      const result = this.claimById(item.work_id);
      if (result) {
        claimed.push(result);
        continue;
      }

      const resources = context.resources ?? {};
      if (resources[item.resource_class]) {
        resources[item.resource_class].in_flight = Math.max(0, Number(resources[item.resource_class].in_flight ?? 0) - 1);
      }

      const roots = this.rootsFromContext(context);
      if (roots[item.root_id]) {
        roots[item.root_id].in_flight = Math.max(0, roots[item.root_id].in_flight - 1);
        context.roots = roots;
      }
    }

    context.claimed_batch = claimed;
    return context;
  }

  private async settleResults(context: Record<string, any>): Promise<Record<string, any>> {
    const roots = this.rootsFromContext(context);
    const resources = context.resources ?? {};
    const claimedBatch = Array.isArray(context.claimed_batch) ? context.claimed_batch as Candidate[] : [];

    const rawResults = context.batch_results;
    const orderedResults: any[] = Array.isArray(rawResults)
      ? rawResults
      : (rawResults && typeof rawResults === 'object')
        ? claimedBatch.map((_, i) => rawResults[i])
        : [];

    const announced = new Set<string>(Array.isArray(context._announced_complete) ? context._announced_complete : []);

    for (let i = 0; i < orderedResults.length; i += 1) {
      const result = orderedResults[i];
      if (!result || typeof result !== 'object') {
        continue;
      }

      const claimed = claimedBatch[i];
      const workId = claimed?.work_id;
      const rootId = String(result.root_id ?? claimed?.root_id ?? '');
      const resourceClass = String(result.resource_class ?? claimed?.resource_class ?? 'fast');
      const attempts = Number(result.attempts ?? claimed?.attempts ?? 0);
      const taskId = String(result.task_id ?? claimed?.task_id ?? '?');

      if (!roots[rootId]) {
        roots[rootId] = this.normalizeRoot({});
      }

      if (resources[resourceClass]) {
        resources[resourceClass].in_flight = Math.max(0, Number(resources[resourceClass].in_flight ?? 0) - 1);
      }

      roots[rootId].in_flight = Math.max(0, roots[rootId].in_flight - 1);

      const error = result.error ?? result._error;
      if (error) {
        if (workId) {
          try {
            await this.pool().fail(workId, String(error));
          } catch {
            // ignore missing rows
          }
        }

        if (attempts >= this.maxAttempts) {
          roots[rootId].terminal_failures += 1;
          console.log(`  ✗ ${taskId.padEnd(24)} terminal after ${attempts} attempts: ${String(error)}`);
        } else {
          console.log(`  ⟳ ${taskId.padEnd(24)} retry ${attempts}/${this.maxAttempts}`);
        }
      } else {
        if (workId) {
          try {
            await this.pool().complete(workId, result);
          } catch {
            // ignore missing rows
          }
        }

        roots[rootId].completed += 1;

        const children = Array.isArray(result.children) ? result.children : [];
        for (const child of children) {
          if (child && typeof child === 'object') {
            await this.pool().push(child, { max_retries: this.maxAttempts });
          }
        }

        const depth = Number(result.depth ?? 0);
        const suffix = children.length > 0 ? `→ ${children.length} children` : '→ leaf';
        console.log(`  ✓ ${taskId.padEnd(24)} (d=${depth} ${resourceClass}) ${suffix}`);
      }
    }

    for (const [rootId, root] of Object.entries(roots)) {
      if (root.admitted && this.rootDone(root) && !announced.has(rootId)) {
        announced.add(rootId);
        const state = root.terminal_failures === 0 ? 'COMPLETE' : 'COMPLETE_WITH_TERMINAL_FAILURES';
        console.log(`  🏁 ${rootId} ${state}`);
      }
    }

    context.roots = roots;
    context.resources = resources;
    context._announced_complete = [...announced];
    context.batch = [];
    context.claimed_batch = [];
    context.batch_results = [];

    return context;
  }

  private async checkDone(context: Record<string, any>): Promise<Record<string, any>> {
    context.all_done = this.unfinishedCount() === 0;
    return context;
  }

  private async releaseStale(context: Record<string, any>): Promise<Record<string, any>> {
    const released = await this.pool().releaseByWorker(WORKER_ID);
    console.log(`Released ${released} stale claims`);

    if (!context.resources || typeof context.resources !== 'object') {
      context.resources = {
        fast: { capacity: 4, in_flight: 0, gate_open: true },
        slow: { capacity: 2, in_flight: 0, gate_open: true },
      };
      context._last_gate_toggle = Date.now() / 1000;
    }

    return context;
  }

  private async reportAndCleanup(context: Record<string, any>): Promise<Record<string, any>> {
    const remaining = this.unfinishedCount();

    if (remaining === 0) {
      console.log('✅ All work complete.');
    } else {
      console.log(`⚠ Run paused with ${remaining} unfinished tasks. Resume with --resume`);
    }

    if (this.checkpointBackend) {
      const allExecs = await this.checkpointBackend.listExecutionIds();
      const completed = await this.checkpointBackend.listExecutionIds({ event: 'machine_end' });
      console.log(`Checkpoint summary: total=${allExecs.length}, completed=${completed.length}, incomplete=${allExecs.length - completed.length}`);

      if (context.cleanup) {
        for (const executionId of completed) {
          await this.checkpointBackend.deleteExecution(executionId);
        }
        console.log(`Cleanup: deleted ${completed.length} completed checkpoints`);
      }
    }

    context.summary = { remaining };
    return context;
  }

  private async runTask(context: Record<string, any>): Promise<Record<string, any>> {
    if (this.random() < this.failRate) {
      throw new Error(`transient failure in ${String(context.task_id ?? 'unknown-task')}`);
    }

    const taskId = String(context.task_id ?? '');
    const rootId = String(context.root_id ?? '');
    const depth = Number(context.depth ?? 0);

    context.children = this.generateChildren(taskId, rootId, depth);
    context.result = `ok:${taskId}`;
    return context;
  }

  private async signalReady(context: Record<string, any>): Promise<Record<string, any>> {
    await this.signalBackend.send('dfss/ready', { reason: 'task_complete' });
    return context;
  }

  private generateChildren(taskId: string, rootId: string, depth: number): Record<string, any>[] {
    if (depth >= this.maxDepth) {
      return [];
    }

    const nChildren = this.randint(0, 2);
    const children: Record<string, any>[] = [];

    for (let i = 0; i < nChildren; i += 1) {
      const resourceClass = this.random() < 0.4 ? 'slow' : 'fast';
      const hint = resourceClass === 'fast' && this.random() < 0.25;

      const distance = resourceClass === 'slow'
        ? 0
        : (hint ? this.randint(1, Math.max(1, this.maxDepth - depth)) : NO_SLOW_DISTANCE);

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
}
