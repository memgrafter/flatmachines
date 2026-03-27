#!/usr/bin/env node
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FlatMachine,
  HooksRegistry,
  SQLiteWorkBackend,
} from '@memgrafter/flatmachines';
import { DemoHooks } from './hooks.js';

type Command = 'seed' | 'checker' | 'worker' | 'reaper' | 'all';

type Args = {
  command: Command;
  count: number;
  maxWorkers: number;
  threshold: number;
  pool: string;
  workerId?: string;
  dbPath: string;
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Temporary ESM shim for SQLite backends that use dynamic require('node:sqlite').
if (!(globalThis as any).require) {
  (globalThis as any).require = createRequire(import.meta.url);
}

const exampleRoot = join(__dirname, '..', '..', '..');
const configDir = join(exampleRoot, 'config');
const defaultDbPath = join(exampleRoot, 'data', 'worker.sqlite');

function parseArgs(argv: string[]): Args {
  const args: Args = {
    command: 'seed',
    count: 5,
    maxWorkers: 3,
    threshold: 60,
    pool: 'default',
    dbPath: defaultDbPath,
  };

  let index = 0;
  if (argv[0] && !argv[0].startsWith('-')) {
    const cmd = argv[0] as Command;
    if (['seed', 'checker', 'worker', 'reaper', 'all'].includes(cmd)) {
      args.command = cmd;
      index = 1;
    }
  }

  for (let i = index; i < argv.length; i += 1) {
    const arg = argv[i];
    if ((arg === '--count' || arg === '-n') && argv[i + 1]) {
      args.count = Number(argv[++i]);
    } else if ((arg === '--max-workers' || arg === '-m') && argv[i + 1]) {
      args.maxWorkers = Number(argv[++i]);
    } else if ((arg === '--threshold' || arg === '-t') && argv[i + 1]) {
      args.threshold = Number(argv[++i]);
    } else if ((arg === '--pool' || arg === '-p') && argv[i + 1]) {
      args.pool = argv[++i] ?? args.pool;
    } else if ((arg === '--worker-id' || arg === '-w') && argv[i + 1]) {
      args.workerId = argv[++i] ?? undefined;
    } else if (arg === '--db' && argv[i + 1]) {
      args.dbPath = argv[++i] ?? args.dbPath;
    } else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
  }

  return args;
}

function printUsage(): void {
  console.log([
    'Distributed worker demo',
    '',
    'Usage:',
    '  node dist/distributed_worker/main.js [seed|checker|worker|reaper|all] [options]',
    '',
    'Options:',
    '  -n, --count <N>         Number of jobs to seed (default 5)',
    '  -m, --max-workers <N>   Max workers for checker (default 3)',
    '  -t, --threshold <SEC>   Stale threshold for reaper (default 60)',
    '  -p, --pool <ID>         Pool ID (default default)',
    '  -w, --worker-id <ID>    Worker ID override',
    '      --db <PATH>         SQLite DB path',
  ].join('\n'));
}

function buildRegistry(dbPath: string): HooksRegistry {
  const hooks = new DemoHooks(dbPath);
  const registry = new HooksRegistry();
  registry.register('distributed-worker', () => hooks);
  return registry;
}

async function runMachine(configName: string, input: Record<string, any>, dbPath: string): Promise<any> {
  const machine = new FlatMachine({
    config: join(configDir, configName),
    configDir,
    hooksRegistry: buildRegistry(dbPath),
  });
  return machine.execute(input);
}

async function seedJobs(count: number, pool: string, dbPath: string): Promise<void> {
  mkdirSync(dirname(dbPath), { recursive: true });
  const work = new SQLiteWorkBackend(dbPath);
  const workPool = work.pool(pool);

  console.log(`Seeding ${count} jobs into pool '${pool}'...`);
  for (let i = 0; i < count; i += 1) {
    const payload = {
      job_number: i + 1,
      message: `Hello from job ${i + 1}`,
      delay_seconds: 1,
    };
    const id = await workPool.push(payload, { max_retries: 3 });
    console.log(`  Created job ${id.slice(0, 8)}... (#${i + 1})`);
  }

  const size = await workPool.size();
  console.log(`\n✅ Done! Pool now has ${size} pending jobs.`);
}

async function runChecker(maxWorkers: number, pool: string, dbPath: string): Promise<void> {
  console.log(`Running parallelization checker (max_workers=${maxWorkers}, pool=${pool})`);
  const result = await runMachine('parallelization_checker.yml', {
    pool_id: pool,
    max_workers: maxWorkers,
  }, dbPath);

  console.log(`\n✅ Checker complete! Spawned ${result?.spawned ?? 0} worker(s).`);
}

async function runWorker(pool: string, workerId: string, dbPath: string): Promise<void> {
  console.log(`Starting worker ${workerId} (pool=${pool})`);
  const result = await runMachine('job_worker.yml', {
    pool_id: pool,
    worker_id: workerId,
  }, dbPath);

  const jobId = result?.job_id;
  if (typeof jobId === 'string' && jobId.length > 0) {
    console.log(`\n✅ Worker complete! Processed job ${jobId.slice(0, 8)}...`);
  } else {
    console.log(`\n⚠️ Worker complete: ${result?.status ?? 'unknown'}`);
  }
}

async function runReaper(threshold: number, pool: string, dbPath: string): Promise<void> {
  console.log(`Running stale worker reaper (threshold=${threshold}s, pool=${pool})`);
  const result = await runMachine('stale_worker_reaper.yml', {
    pool_id: pool,
    stale_threshold_seconds: threshold,
  }, dbPath);

  console.log(`\n✅ Reaper complete! Cleaned up ${result?.reaped_count ?? 0} stale worker(s).`);
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  switch (args.command) {
    case 'seed':
      await seedJobs(args.count, args.pool, args.dbPath);
      return;
    case 'checker':
      await runChecker(args.maxWorkers, args.pool, args.dbPath);
      return;
    case 'worker': {
      const workerId = args.workerId ?? `worker-${randomUUID().slice(0, 8)}`;
      await runWorker(args.pool, workerId, args.dbPath);
      return;
    }
    case 'reaper':
      await runReaper(args.threshold, args.pool, args.dbPath);
      return;
    case 'all': {
      const workerId = args.workerId ?? `worker-${randomUUID().slice(0, 8)}`;
      await seedJobs(args.count, args.pool, args.dbPath);
      console.log('');
      await runChecker(args.maxWorkers, args.pool, args.dbPath);
      console.log('');
      await runWorker(args.pool, workerId, args.dbPath);
      console.log('');
      await runReaper(args.threshold, args.pool, args.dbPath);
      return;
    }
  }
}

main().catch((error) => {
  console.error('Error:', error instanceof Error ? error.message : String(error));
  process.exit(1);
});
