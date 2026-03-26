#!/usr/bin/env node
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CheckpointManager,
  FlatMachine,
  SQLiteCheckpointBackend,
  SQLiteWorkBackend,
} from '@memgrafter/flatmachines';
import { TaskHooks } from './hooks.js';
import {
  addCandidate,
  Candidate,
  recomputeRootMetrics,
  ResourcePool,
  RootState,
  runScheduler,
} from './scheduler.js';
import { taskConfig } from './task_machine.js';

if (!(globalThis as any).require) {
  (globalThis as any).require = createRequire(import.meta.url);
}

const POOL_NAME = 'tasks';
const WORKER_ID = 'scheduler';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const exampleRoot = resolve(__dirname, '..', '..', '..');

type Args = {
  roots: number;
  resume: boolean;
  maxDepth: number;
  maxWorkers: number;
  maxActiveRoots: number;
  maxAttempts: number;
  dbPath: string;
  seed: number;
  failRate: number;
  gateInterval: number;
  cleanup: boolean;
};

type StopToken = { isSet(): boolean; set(): void };

function createStopToken(): StopToken {
  let stopped = false;
  return {
    isSet: () => stopped,
    set: () => {
      stopped = true;
    },
  };
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    roots: 8,
    resume: false,
    maxDepth: 3,
    maxWorkers: 4,
    maxActiveRoots: 3,
    maxAttempts: 3,
    dbPath: 'data/dfss.sqlite',
    seed: 7,
    failRate: 0.15,
    gateInterval: 0.8,
    cleanup: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--roots' && argv[i + 1]) args.roots = Number(argv[++i]);
    else if (arg === '--resume') args.resume = true;
    else if (arg === '--max-depth' && argv[i + 1]) args.maxDepth = Number(argv[++i]);
    else if (arg === '--max-workers' && argv[i + 1]) args.maxWorkers = Number(argv[++i]);
    else if (arg === '--max-active-roots' && argv[i + 1]) args.maxActiveRoots = Number(argv[++i]);
    else if (arg === '--max-attempts' && argv[i + 1]) args.maxAttempts = Number(argv[++i]);
    else if (arg === '--db-path' && argv[i + 1]) args.dbPath = argv[++i] ?? args.dbPath;
    else if (arg === '--seed' && argv[i + 1]) args.seed = Number(argv[++i]);
    else if (arg === '--fail-rate' && argv[i + 1]) args.failRate = Number(argv[++i]);
    else if (arg === '--gate-interval' && argv[i + 1]) args.gateInterval = Number(argv[++i]);
    else if (arg === '--cleanup') args.cleanup = true;
    else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
  }

  return args;
}

function printUsage(): void {
  console.log([
    'DFSS pipeline demo (JS)',
    '',
    'Usage:',
    '  node dist/flatagent_dfss_pipeline/main.js [options]',
    '',
    'Options:',
    '  --roots <N>               number of root tasks (default 8)',
    '  --resume                  resume interrupted run',
    '  --max-depth <N>           max depth (default 3)',
    '  --max-workers <N>         worker concurrency (default 4)',
    '  --max-active-roots <N>    max admitted roots (default 3)',
    '  --max-attempts <N>        retries before poison (default 3)',
    '  --db-path <PATH>          sqlite path (default data/dfss.sqlite)',
    '  --seed <N>                RNG seed (default 7)',
    '  --fail-rate <R>           transient fail probability (default 0.15)',
    '  --gate-interval <SEC>     slow gate interval (default 0.8)',
    '  --cleanup                 delete completed checkpoints',
  ].join('\n'));
}

function rng(seed: number): () => number {
  let state = Math.max(1, seed >>> 0);
  return () => {
    let x = state;
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    state = x >>> 0;
    return state / 0x100000000;
  };
}

function randint(rand: () => number, min: number, max: number): number {
  return Math.floor(rand() * (max - min + 1)) + min;
}

function choose<T>(rand: () => number, values: T[]): T {
  return values[Math.floor(rand() * values.length)] as T;
}

function initialRootTask(rootId: string, maxDepth: number, rand: () => number): Record<string, any> {
  if (rootId === 'root-000') {
    return {
      task_id: 'root-000/0',
      root_id: 'root-000',
      depth: 0,
      resource_class: 'fast',
      has_expensive_descendant: true,
      distance_to_nearest_slow_descendant: 2,
    };
  }

  if (rootId === 'root-001') {
    return {
      task_id: 'root-001/0',
      root_id: 'root-001',
      depth: 0,
      resource_class: 'fast',
      has_expensive_descendant: true,
      distance_to_nearest_slow_descendant: 3,
    };
  }

  const resourceClass = choose(rand, ['fast', 'slow']);
  const hint = resourceClass === 'fast' && rand() < 0.35;
  const distance = resourceClass === 'slow'
    ? 0
    : (hint ? randint(rand, 1, Math.max(1, maxDepth)) : 10_000);

  return {
    task_id: `${rootId}/0`,
    root_id: rootId,
    depth: 0,
    resource_class: resourceClass,
    has_expensive_descendant: hint,
    distance_to_nearest_slow_descendant: distance,
  };
}

function poolDb(workBackend: SQLiteWorkBackend): any {
  return (workBackend as any).db;
}

function candidateFromRow(row: any): Candidate | null {
  try {
    const data = JSON.parse(String(row.data));
    if (!data || typeof data !== 'object') return null;
    if (!data.task_id || !data.root_id) return null;

    return {
      work_id: String(row.item_id),
      task_id: String(data.task_id),
      root_id: String(data.root_id),
      depth: Number(data.depth ?? 0),
      resource_class: String(data.resource_class ?? 'fast'),
      has_expensive_descendant: Boolean(data.has_expensive_descendant ?? false),
      distance_to_nearest_slow_descendant: Number(data.distance_to_nearest_slow_descendant ?? 10_000),
      attempts: Number(row.attempts ?? 0),
    };
  } catch {
    return null;
  }
}

function loadPendingCandidates(workBackend: SQLiteWorkBackend): Candidate[] {
  const rows = poolDb(workBackend).prepare(`
    SELECT item_id, data, attempts
    FROM work_pool
    WHERE pool_name = ? AND status = 'pending'
    ORDER BY created_at ASC
  `).all(POOL_NAME);

  const candidates: Candidate[] = [];
  for (const row of rows) {
    const c = candidateFromRow(row);
    if (c) candidates.push(c);
  }
  return candidates;
}

function loadPendingCandidateById(workBackend: SQLiteWorkBackend, workId: string): Candidate | null {
  const row = poolDb(workBackend).prepare(`
    SELECT item_id, data, attempts
    FROM work_pool
    WHERE pool_name = ? AND item_id = ? AND status = 'pending'
  `).get(POOL_NAME, workId);
  return row ? candidateFromRow(row) : null;
}

function claimSelectedCandidate(workBackend: SQLiteWorkBackend, workId: string): Candidate | null {
  const db = poolDb(workBackend);
  const now = new Date().toISOString();

  db.exec('BEGIN IMMEDIATE');
  try {
    const updated = db.prepare(`
      UPDATE work_pool
      SET status = 'claimed', claimed_by = ?, claimed_at = ?, attempts = attempts + 1
      WHERE pool_name = ? AND item_id = ? AND status = 'pending'
    `).run(WORKER_ID, now, POOL_NAME, workId);

    if (Number(updated.changes ?? 0) === 0) {
      db.exec('COMMIT');
      return null;
    }

    const row = db.prepare(`
      SELECT item_id, data, attempts
      FROM work_pool
      WHERE pool_name = ? AND item_id = ?
    `).get(POOL_NAME, workId);

    db.exec('COMMIT');
    return row ? candidateFromRow(row) : null;
  } catch (error) {
    db.exec('ROLLBACK');
    throw error;
  }
}

function unfinishedWorkCount(workBackend: SQLiteWorkBackend): number {
  const row = poolDb(workBackend).prepare(`
    SELECT COUNT(*) AS c
    FROM work_pool
    WHERE pool_name = ? AND status IN ('pending', 'claimed')
  `).get(POOL_NAME);

  return Number(row?.c ?? 0);
}

function rootTerminalFailures(workBackend: SQLiteWorkBackend): Record<string, number> {
  const rows = poolDb(workBackend).prepare(`
    SELECT data
    FROM work_pool
    WHERE pool_name = ? AND status = 'poisoned'
  `).all(POOL_NAME);

  const out: Record<string, number> = {};
  for (const row of rows) {
    try {
      const data = JSON.parse(String(row.data));
      const rootId = String(data.root_id ?? '');
      if (!rootId) continue;
      out[rootId] = (out[rootId] ?? 0) + 1;
    } catch {
      // ignore malformed rows
    }
  }
  return out;
}

function buildRootStates(rootIds: string[], candidates: Candidate[]): Record<string, RootState> {
  let ids = rootIds;
  if (ids.length === 0) {
    ids = [...new Set(candidates.map((c) => String(c.root_id)))].sort();
  }

  const roots: Record<string, RootState> = {};
  for (const rid of ids) {
    roots[rid] = new RootState(rid);
  }

  recomputeRootMetrics(roots, candidates);
  return roots;
}

async function resumeStatusReport(checkpointBackend: SQLiteCheckpointBackend): Promise<void> {
  const allExecs = new Set(await checkpointBackend.listExecutionIds());
  const completed = new Set(await checkpointBackend.listExecutionIds({ event: 'machine_end' }));
  const incomplete = [...allExecs].filter((id) => !completed.has(id)).sort();

  console.log(
    `Resume status: total executions=${allExecs.size}, completed=${completed.size}, incomplete=${incomplete.length}`,
  );

  for (const executionId of incomplete.slice(0, 10)) {
    const status = await new CheckpointManager(checkpointBackend, executionId).loadStatus();
    if (!status) {
      console.log(`  - ${executionId}: unknown`);
      continue;
    }
    const [event, state] = status;
    console.log(`  - ${executionId}: event=${event}, state=${state}`);
  }
}

async function postRunReport(checkpointBackend: SQLiteCheckpointBackend, cleanup: boolean): Promise<void> {
  const allExecs = await checkpointBackend.listExecutionIds();
  const completed = await checkpointBackend.listExecutionIds({ event: 'machine_end' });

  console.log(
    `Checkpoint summary: total=${allExecs.length}, completed=${completed.length}, incomplete=${allExecs.length - completed.length}`,
  );

  if (cleanup) {
    for (const executionId of completed) {
      await checkpointBackend.deleteExecution(executionId);
    }
    console.log(`Cleanup: deleted ${completed.length} completed checkpoints`);
  }
}

async function runPipeline(args: Args): Promise<number> {
  const dbPath = resolve(exampleRoot, args.dbPath);
  mkdirSync(dirname(dbPath), { recursive: true });

  if (!args.resume && existsSync(dbPath)) {
    rmSync(dbPath);
  }

  const checkpointBackend = new SQLiteCheckpointBackend(dbPath);
  const workBackend = new SQLiteWorkBackend(dbPath);
  const pool = workBackend.pool(POOL_NAME);

  let rootIds: string[] = [];
  let seedValue = args.seed;

  if (args.resume) {
    const released = await pool.releaseByWorker(WORKER_ID);
    console.log(`Resuming from ${dbPath} (released ${released} stale claims)`);
    await resumeStatusReport(checkpointBackend);
  } else {
    const rand = rng(args.seed);
    rootIds = Array.from({ length: args.roots }, (_, i) => `root-${String(i).padStart(3, '0')}`);

    for (const rid of rootIds) {
      await pool.push(initialRootTask(rid, args.maxDepth, rand), { max_retries: args.maxAttempts });
    }

    console.log(
      `Seeded roots=${args.roots}, max_depth=${args.maxDepth}, seed=${args.seed}, max_attempts=${args.maxAttempts}`,
    );
  }

  const candidates = loadPendingCandidates(workBackend);
  const roots = buildRootStates(rootIds, candidates);

  const resources: Record<string, ResourcePool> = {
    fast: new ResourcePool('fast', 4, true),
    slow: new ResourcePool('slow', 2, true),
  };

  const hooks = new TaskHooks(args.maxDepth, args.failRate, seedValue);
  const machineCfg = taskConfig();

  const announcedComplete = new Set<string>();
  const terminalByRoot = rootTerminalFailures(workBackend);
  for (const [rid, count] of Object.entries(terminalByRoot)) {
    if (roots[rid]) roots[rid].terminal_failures = count;
  }

  const stop = createStopToken();

  const onSignal = () => stop.set();
  process.on('SIGINT', onSignal);
  process.on('SIGTERM', onSignal);

  const refreshAndReportRoots = () => {
    recomputeRootMetrics(roots, candidates);
    for (const root of Object.values(roots)) {
      if (root.is_done && !announcedComplete.has(root.root_id)) {
        announcedComplete.add(root.root_id);
        const state = root.terminal_failures === 0 ? 'COMPLETE' : 'COMPLETE_WITH_TERMINAL_FAILURES';
        console.log(`  🏁 ${root.root_id} ${state}`);
      }
    }
  };

  const dispatch = async (item: Candidate): Promise<void> => {
    const claimed = claimSelectedCandidate(workBackend, String(item.work_id));
    if (!claimed) return;

    const rootId = String(claimed.root_id);
    const taskPayload = {
      task_id: claimed.task_id,
      root_id: claimed.root_id,
      depth: claimed.depth,
      resource_class: claimed.resource_class,
      has_expensive_descendant: claimed.has_expensive_descendant,
      distance_to_nearest_slow_descendant: claimed.distance_to_nearest_slow_descendant,
    };

    const machine = new FlatMachine({
      config: machineCfg as any,
      hooks,
      persistence: checkpointBackend,
      executionId: String(claimed.work_id),
    });

    let output: any;
    try {
      const latest = await checkpointBackend.load(`${String(claimed.work_id)}/latest`);
      if (latest) {
        output = await machine.resume(String(claimed.work_id));
      } else {
        output = await machine.execute(taskPayload);
      }
    } catch (error) {
      output = { error: error instanceof Error ? error.message : String(error) };
    }

    const runError = output && typeof output === 'object' ? output.error : 'unknown task failure';
    if (runError) {
      await pool.fail(String(claimed.work_id), String(runError));

      if (Number(claimed.attempts) >= args.maxAttempts) {
        if (roots[rootId]) roots[rootId].terminal_failures += 1;
        console.log(`  ✗ ${String(claimed.task_id).padEnd(24)} terminal after ${claimed.attempts} attempts: ${runError}`);
        return;
      }

      const pendingRetry = loadPendingCandidateById(workBackend, String(claimed.work_id));
      if (pendingRetry) addCandidate(candidates, pendingRetry);
      console.log(`  ⟳ ${String(claimed.task_id).padEnd(24)} retry ${claimed.attempts}/${args.maxAttempts}`);
      return;
    }

    await pool.complete(String(claimed.work_id), output);
    if (roots[rootId]) roots[rootId].completed += 1;

    const children = Array.isArray(output?.children) ? output.children : [];
    for (const child of children) {
      if (!child || typeof child !== 'object') continue;
      const workId = await pool.push(child, { max_retries: args.maxAttempts });
      addCandidate(candidates, {
        work_id: workId,
        task_id: child.task_id,
        root_id: child.root_id,
        depth: Number(child.depth ?? 0),
        resource_class: String(child.resource_class ?? 'fast'),
        has_expensive_descendant: Boolean(child.has_expensive_descendant ?? false),
        distance_to_nearest_slow_descendant: Number(child.distance_to_nearest_slow_descendant ?? 10_000),
        attempts: 0,
      });
    }

    const suffix = children.length > 0 ? `→ ${children.length} children` : '→ leaf';
    console.log(`  ✓ ${String(claimed.task_id).padEnd(24)} (d=${claimed.depth} ${claimed.resource_class}) ${suffix}`);
  };

  const gateLoop = (async () => {
    console.log('  ⚡ slow gate -> OPEN');
    while (!stop.isSet()) {
      await new Promise((resolve) => setTimeout(resolve, args.gateInterval * 1000));
      if (stop.isSet()) break;
      resources.slow.gate_open = !resources.slow.gate_open;
      console.log(`  ⚡ slow gate -> ${resources.slow.gate_open ? 'OPEN' : 'CLOSED'}`);
    }
  })();

  try {
    await runScheduler({
      candidates,
      roots,
      resources,
      dispatch,
      maxWorkers: args.maxWorkers,
      maxActiveRoots: args.maxActiveRoots,
      idlePoll: 0.05,
      stop,
      onTaskDone: refreshAndReportRoots,
    });
  } finally {
    stop.set();
    await gateLoop.catch(() => {});
    process.off('SIGINT', onSignal);
    process.off('SIGTERM', onSignal);
  }

  const remaining = unfinishedWorkCount(workBackend);
  if (remaining === 0) {
    console.log('✅ All work complete.');
  } else {
    console.log(`⚠ Run paused with ${remaining} unfinished tasks. Resume with --resume`);
  }

  await postRunReport(checkpointBackend, args.cleanup);
  return 0;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const code = await runPipeline(args);
  process.exit(code);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
