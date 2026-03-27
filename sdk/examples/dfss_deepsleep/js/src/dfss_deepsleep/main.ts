#!/usr/bin/env node
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FlatMachine,
  HooksRegistry,
  SQLiteCheckpointBackend,
  SQLiteSignalBackend,
  SQLiteWorkBackend,
} from '@memgrafter/flatmachines';
import { DeepSleepHooks } from './hooks.js';

type Args = {
  roots: number;
  resume: boolean;
  maxDepth: number;
  maxWorkers: number;
  maxActiveRoots: number;
  maxAttempts: number;
  batchSize: number;
  dbPath: string;
  seed: number;
  failRate: number;
  gateInterval: number;
  cleanup: boolean;
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Temporary ESM shim for SQLite backends that use dynamic require('node:sqlite').
if (!(globalThis as any).require) {
  (globalThis as any).require = createRequire(import.meta.url);
}

const exampleRoot = join(__dirname, '..', '..', '..');
const configDir = join(exampleRoot, 'config');

function parseArgs(argv: string[]): Args {
  const args: Args = {
    roots: 8,
    resume: false,
    maxDepth: 3,
    maxWorkers: 4,
    maxActiveRoots: 3,
    maxAttempts: 3,
    batchSize: 4,
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
    else if (arg === '--batch-size' && argv[i + 1]) args.batchSize = Number(argv[++i]);
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
    'DFSS deep sleep scheduler (JS)',
    '',
    'Usage:',
    '  node dist/dfss_deepsleep/main.js [options]',
    '',
    'Options:',
    '  --roots <N>               Number of roots (default 8)',
    '  --resume                  Resume a parked execution',
    '  --max-depth <N>           Max depth (default 3)',
    '  --max-active-roots <N>    Max admitted roots (default 3)',
    '  --max-attempts <N>        Max retries (default 3)',
    '  --batch-size <N>          Batch size (default 4)',
    '  --db-path <PATH>          SQLite db path (default data/dfss.sqlite)',
    '  --seed <N>                RNG seed (default 7)',
    '  --fail-rate <R>           Transient failure probability (default 0.15)',
    '  --gate-interval <SEC>     Slow gate toggle interval (default 0.8)',
    '  --cleanup                 Delete completed checkpoints at end',
  ].join('\n'));
}

async function run(args: Args): Promise<number> {
  const dbPath = resolve(exampleRoot, args.dbPath);
  mkdirSync(dirname(dbPath), { recursive: true });

  if (!args.resume && existsSync(dbPath)) {
    rmSync(dbPath);
  }

  const checkpointBackend = new SQLiteCheckpointBackend(dbPath);
  const signalBackend = new SQLiteSignalBackend(dbPath);
  const workBackend = new SQLiteWorkBackend(dbPath);

  const hooks = new DeepSleepHooks({
    maxDepth: args.maxDepth,
    failRate: args.failRate,
    seed: args.seed,
    maxAttempts: args.maxAttempts,
    gateInterval: args.gateInterval,
    poolName: 'tasks',
    workBackend,
    signalBackend,
    checkpointBackend,
  });

  const registry = new HooksRegistry();
  registry.register('deepsleep', () => hooks);

  const machine = new FlatMachine({
    config: join(configDir, 'scheduler_machine.yml'),
    configDir,
    hooksRegistry: registry,
    persistence: checkpointBackend,
    signalBackend,
  });

  const input = {
    pool_name: 'tasks',
    max_active_roots: args.maxActiveRoots,
    batch_size: args.batchSize,
    n_roots: args.roots,
    max_depth: args.maxDepth,
    resume: args.resume,
    cleanup: args.cleanup,
  };

  if (args.resume) {
    const waiting = await checkpointBackend.listExecutionIds({ waiting_channel: 'dfss/ready' });
    const allIds = await checkpointBackend.listExecutionIds();
    const completed = new Set(await checkpointBackend.listExecutionIds({ event: 'machine_end' }));
    const incomplete = allIds.filter((executionId) => !completed.has(executionId));

    const executionId = waiting[0] ?? incomplete[0];
    if (!executionId) {
      console.log('Nothing to resume.');
      return 0;
    }

    await signalBackend.send('dfss/ready', { reason: 'resume' });
    console.log(`Resuming execution ${executionId}`);
    const result = await machine.resume(executionId);

    if (result && typeof result === 'object' && result._waiting) {
      console.log(`Scheduler sleeping on channel: ${String(result._channel ?? 'unknown')}`);
      console.log('Resume with --resume');
    } else {
      console.log('Scheduler finished.');
    }

    return 0;
  }

  await signalBackend.send('dfss/ready', { reason: 'initial_seed' });
  const result = await machine.execute(input);

  if (result && typeof result === 'object' && result._waiting) {
    console.log(`Scheduler sleeping on channel: ${String(result._channel ?? 'unknown')}`);
    console.log('Resume with --resume');
  } else {
    console.log('Scheduler finished.');
  }

  return 0;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const code = await run(args);
  process.exit(code);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
