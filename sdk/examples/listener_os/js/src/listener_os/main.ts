#!/usr/bin/env node
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CheckpointManager,
  ConfigStoreResumer,
  FileTrigger,
  FlatMachine,
  NoOpTrigger,
  SQLiteCheckpointBackend,
  SQLiteSignalBackend,
  SocketTrigger,
  run_once,
  sendAndNotify,
} from '@memgrafter/flatmachines';

type Command = 'park' | 'send' | 'dispatch-once' | 'status' | 'reset';

type Args = {
  command: Command;
  taskId?: string;
  approved: boolean;
  reviewer: string;
  trigger: 'none' | 'file' | 'socket';
  triggerBase?: string;
  socketPath?: string;
  dbPath?: string;
  dataDir?: string;
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Temporary ESM shim for SQLite backends that use dynamic require('node:sqlite').
if (!(globalThis as any).require) {
  (globalThis as any).require = createRequire(import.meta.url);
}

const exampleRoot = join(__dirname, '..', '..', '..');

function defaultPaths() {
  const dataDir = join(exampleRoot, 'data');
  return {
    root: exampleRoot,
    dataDir,
    machine: join(exampleRoot, 'config', 'machine.yml'),
    db: join(dataDir, 'listener_os.sqlite'),
    triggerBase: join(dataDir, 'trigger'),
    socket: join(dataDir, 'trigger.sock'),
  };
}

function parseBool(value: string): boolean {
  const v = value.trim().toLowerCase();
  if (['1', 'true', 't', 'yes', 'y'].includes(v)) return true;
  if (['0', 'false', 'f', 'no', 'n'].includes(v)) return false;
  throw new Error(`invalid bool: ${value}`);
}

function parseArgs(argv: string[]): Args {
  if (argv.length === 0 || argv[0] === '--help' || argv[0] === '-h') {
    printUsage();
    process.exit(0);
  }

  const command = argv[0] as Command;
  if (!['park', 'send', 'dispatch-once', 'status', 'reset'].includes(command)) {
    throw new Error(`Unknown command: ${argv[0] ?? ''}`);
  }

  const args: Args = {
    command,
    approved: true,
    reviewer: 'demo-user',
    trigger: 'file',
  };

  for (let i = 1; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '--task-id' && argv[i + 1]) args.taskId = argv[++i];
    else if (arg === '--approved' && argv[i + 1]) args.approved = parseBool(argv[++i] ?? 'true');
    else if (arg === '--reviewer' && argv[i + 1]) args.reviewer = argv[++i] ?? args.reviewer;
    else if (arg === '--trigger' && argv[i + 1]) args.trigger = (argv[++i] as Args['trigger']) ?? args.trigger;
    else if (arg === '--trigger-base' && argv[i + 1]) args.triggerBase = argv[++i] ?? undefined;
    else if (arg === '--socket-path' && argv[i + 1]) args.socketPath = argv[++i] ?? undefined;
    else if (arg === '--db-path' && argv[i + 1]) args.dbPath = argv[++i] ?? undefined;
    else if (arg === '--data-dir' && argv[i + 1]) args.dataDir = argv[++i] ?? undefined;
    else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    }
  }

  return args;
}

function printUsage(): void {
  console.log([
    'Listener OS demo (JS)',
    '',
    'Usage:',
    '  node dist/listener_os/main.js park --task-id task-001 [--db-path PATH]',
    '  node dist/listener_os/main.js send --task-id task-001 --approved true --reviewer alice --trigger file',
    '  node dist/listener_os/main.js dispatch-once [--db-path PATH]',
    '  node dist/listener_os/main.js status [--db-path PATH]',
    '  node dist/listener_os/main.js reset [--data-dir PATH]',
  ].join('\n'));
}

function buildBackends(dbPathRaw?: string) {
  const paths = defaultPaths();
  const dbPath = resolve(dbPathRaw ?? paths.db);
  mkdirSync(dirname(dbPath), { recursive: true });
  const signalBackend = new SQLiteSignalBackend(dbPath);
  const persistence = new SQLiteCheckpointBackend(dbPath);
  return { dbPath, signalBackend, persistence };
}

async function pendingByChannel(signalBackend: SQLiteSignalBackend): Promise<Record<string, number>> {
  const channels = await signalBackend.channels();
  const out: Record<string, number> = {};
  for (const channel of channels) {
    out[channel] = (await signalBackend.peek(channel)).length;
  }
  return out;
}

async function cmdPark(args: Args): Promise<void> {
  if (!args.taskId) {
    throw new Error('park requires --task-id');
  }

  const paths = defaultPaths();
  const { signalBackend, persistence } = buildBackends(args.dbPath);

  const machine = new FlatMachine({
    config: paths.machine,
    configDir: join(paths.root, 'config'),
    signalBackend,
    persistence,
    configStore: persistence.configStore,
  });

  const result = await machine.execute({ task_id: args.taskId });
  console.log(JSON.stringify({ execution_id: machine.executionId, result }, null, 2));
}

async function cmdSend(args: Args): Promise<void> {
  if (!args.taskId) {
    throw new Error('send requires --task-id');
  }

  const paths = defaultPaths();
  const { signalBackend } = buildBackends(args.dbPath);
  const triggerBase = resolve(args.triggerBase ?? paths.triggerBase);
  const socketPath = resolve(args.socketPath ?? paths.socket);

  const triggerBackend = args.trigger === 'none'
    ? new NoOpTrigger()
    : args.trigger === 'file'
      ? new FileTrigger(triggerBase)
      : new SocketTrigger(socketPath);

  const channel = `approval/${args.taskId}`;
  const payload = {
    approved: args.approved,
    reviewer: args.reviewer,
  };

  const signalId = await sendAndNotify(signalBackend, triggerBackend, channel, payload);

  console.log(JSON.stringify({
    signal_id: signalId,
    channel,
    payload,
    trigger: args.trigger,
  }, null, 2));
}

async function cmdDispatchOnce(args: Args): Promise<void> {
  const { signalBackend, persistence } = buildBackends(args.dbPath);

  const pendingBefore = await pendingByChannel(signalBackend);
  const resumer = new ConfigStoreResumer({
    signalBackend,
    persistenceBackend: persistence,
    configStore: persistence.configStore,
  });

  const resumedByChannel = await run_once(signalBackend, persistence, { resumer });
  const pendingAfter = await pendingByChannel(signalBackend);
  const resumedTotal = Object.values(resumedByChannel).reduce((total, ids) => total + ids.length, 0);

  console.log(JSON.stringify({
    resumed_by_channel: resumedByChannel,
    resumed_total: resumedTotal,
    pending_before: pendingBefore,
    pending_after: pendingAfter,
  }, null, 2));
}

async function cmdStatus(args: Args): Promise<void> {
  const { dbPath, signalBackend, persistence } = buildBackends(args.dbPath);

  const channels = await signalBackend.channels();
  const pendingSignals: Record<string, number> = {};
  for (const channel of channels) {
    pendingSignals[channel] = (await signalBackend.peek(channel)).length;
  }

  const executionIds = await persistence.listExecutionIds();
  const waitingMachines: Record<string, string[]> = {};

  for (const executionId of executionIds) {
    const snapshot = await new CheckpointManager(persistence).restore(executionId);
    const channel = (snapshot as any)?.waiting_channel;
    if (channel) {
      if (!waitingMachines[channel]) {
        waitingMachines[channel] = [];
      }
      waitingMachines[channel].push(executionId);
    }
  }

  console.log(JSON.stringify({
    db_path: dbPath,
    pending_signals: pendingSignals,
    waiting_machines: waitingMachines,
  }, null, 2));
}

async function cmdReset(args: Args): Promise<void> {
  const paths = defaultPaths();
  const dataDir = resolve(args.dataDir ?? paths.dataDir);
  if (existsSync(dataDir)) {
    rmSync(dataDir, { recursive: true, force: true });
  }
  console.log(JSON.stringify({ removed: dataDir }, null, 2));
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  switch (args.command) {
    case 'park':
      await cmdPark(args);
      return;
    case 'send':
      await cmdSend(args);
      return;
    case 'dispatch-once':
      await cmdDispatchOnce(args);
      return;
    case 'status':
      await cmdStatus(args);
      return;
    case 'reset':
      await cmdReset(args);
      return;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
