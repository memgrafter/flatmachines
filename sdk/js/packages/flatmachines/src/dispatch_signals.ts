/**
 * Dispatch signals CLI / runtime.
 */

import { SignalBackend, MemorySignalBackend, SQLiteSignalBackend } from './signals';
import { PersistenceBackend } from './types';
import { MemoryBackend, LocalFileBackend } from './persistence';
import { SignalDispatcher } from './dispatcher';
import { SQLiteCheckpointBackend } from './persistence_sqlite';

// ─────────────────────────────────────────────────────────────────────────────
// run_once — single pass over all pending signals
// ─────────────────────────────────────────────────────────────────────────────

export async function run_once(
  signalBackend: SignalBackend,
  persistenceBackend: PersistenceBackend,
  resumeFnOrOpts?: ((executionId: string, signalData: any) => Promise<void>) | { resumer?: any; resumeFn?: (executionId: string, signalData: any) => Promise<void> },
): Promise<Record<string, string[]>> {
  let opts: { resumer?: any; resumeFn?: (eid: string, data: any) => Promise<void> } = {};
  if (typeof resumeFnOrOpts === 'function') {
    opts = { resumeFn: resumeFnOrOpts };
  } else if (resumeFnOrOpts) {
    // Support both camelCase and snake_case for Python parity
    const raw = resumeFnOrOpts as Record<string, any>;
    opts = {
      resumer: raw.resumer,
      resumeFn: raw.resumeFn ?? raw.resume_fn,
    };
  }
  const dispatcher = new SignalDispatcher(signalBackend, persistenceBackend, opts);
  return dispatcher.dispatchAll();
}

// ─────────────────────────────────────────────────────────────────────────────
// run_listen — drain then poll until stopEvent
// ─────────────────────────────────────────────────────────────────────────────

export async function run_listen(
  signalBackend: SignalBackend,
  persistenceBackend: PersistenceBackend,
  _socketPath: string,
  resumeFn?: (executionId: string, signalData: any) => Promise<void>,
  stopEvent?: { is_set(): boolean; set(): void },
): Promise<void> {
  const dispatcher = new SignalDispatcher(signalBackend, persistenceBackend, { resumeFn });

  // First drain pending signals
  await dispatcher.dispatchAll();

  // Then poll until stopped
  if (stopEvent && !stopEvent.is_set()) {
    while (!stopEvent.is_set()) {
      await new Promise(resolve => setTimeout(resolve, 50));
      await dispatcher.dispatchAll();
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// CLI parser (Python-compatible)
// ─────────────────────────────────────────────────────────────────────────────

interface ParsedArgs {
  once: boolean;
  listen: boolean;
  signal_backend: string;
  persistence_backend: string;
  db_path: string;
  checkpoints_dir: string;
  socket_path: string;
  verbose: boolean;
  quiet: boolean;
  allow_noop_resume: boolean;
  resumer?: string;
}

class SimpleArgParser {
  parse_args(argv: string[]): ParsedArgs {
    const args: ParsedArgs = {
      once: false,
      listen: false,
      signal_backend: 'sqlite',
      persistence_backend: 'sqlite',
      db_path: 'flatmachines.sqlite',
      checkpoints_dir: '.checkpoints',
      socket_path: '/tmp/flatmachines/trigger.sock',
      verbose: false,
      quiet: false,
      allow_noop_resume: false,
    };

    for (let i = 0; i < argv.length; i++) {
      const arg = argv[i];
      switch (arg) {
        case '--once': args.once = true; break;
        case '--listen': args.listen = true; break;
        case '--signal-backend': args.signal_backend = argv[++i]!; break;
        case '--persistence-backend': args.persistence_backend = argv[++i]!; break;
        case '--db-path': args.db_path = argv[++i]!; break;
        case '--checkpoints-dir': args.checkpoints_dir = argv[++i]!; break;
        case '--socket-path': args.socket_path = argv[++i]!; break;
        case '-v': case '--verbose': args.verbose = true; break;
        case '-q': case '--quiet': args.quiet = true; break;
        case '--allow-noop-resume': args.allow_noop_resume = true; break;
        case '--resumer': args.resumer = argv[++i]; break;
      }
    }

    if (args.once && args.listen) {
      throw new Error('--once and --listen are mutually exclusive');
    }
    if (!args.once && !args.listen) {
      throw new Error('One of --once or --listen is required');
    }

    return args;
  }
}

export function _build_parser(): SimpleArgParser {
  return new SimpleArgParser();
}

// ─────────────────────────────────────────────────────────────────────────────
// _async_main — CLI entrypoint
// ─────────────────────────────────────────────────────────────────────────────

export async function _async_main(args: ParsedArgs): Promise<number> {
  // Build signal backend
  let signalBackend: SignalBackend;
  if (args.signal_backend === 'memory') {
    signalBackend = new MemorySignalBackend();
  } else {
    signalBackend = new SQLiteSignalBackend(args.db_path);
  }

  // Build persistence backend
  let persistenceBackend: PersistenceBackend;
  if (args.persistence_backend === 'memory') {
    persistenceBackend = new MemoryBackend();
  } else if (args.persistence_backend === 'local') {
    persistenceBackend = new LocalFileBackend(args.checkpoints_dir);
  } else {
    persistenceBackend = new SQLiteCheckpointBackend(args.db_path);
  }

  // Determine resume strategy
  let resumeFn: ((executionId: string, signalData: any) => Promise<void>) | undefined;

  if (args.resumer === 'config-store') {
    // Noop for now — just acknowledge the signal
    resumeFn = async () => {};
  } else if (args.allow_noop_resume) {
    resumeFn = undefined; // SignalDispatcher handles this
  } else {
    // No resume strategy — return error
    return 2;
  }

  if (args.once) {
    await run_once(signalBackend, persistenceBackend, resumeFn);
    return 0;
  }

  // listen mode
  const stopEvent = { _stopped: false, is_set() { return this._stopped; }, set() { this._stopped = true; } };
  await run_listen(signalBackend, persistenceBackend, args.socket_path, resumeFn, stopEvent);
  return 0;
}