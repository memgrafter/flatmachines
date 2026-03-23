#!/usr/bin/env node
import { AgentAdapterRegistry, FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { CLIToolHooks } from './hooks.js';
import { CodexAwareFlatAgentAdapter } from './codex_backend.js';

type Args = {
  task?: string;
  workingDir: string;
  standalone: boolean;
  standaloneTask?: string;
  help: boolean;
};

function usage(): string {
  return [
    'Usage:',
    '  node dist/tool_use_cli/main.js                              # REPL',
    '  node dist/tool_use_cli/main.js -p "list Python files"       # single-shot',
    '  node dist/tool_use_cli/main.js --standalone "task"          # standalone, auto-approve',
    '  node dist/tool_use_cli/main.js -p "task" --standalone       # standalone with -p task',
    '',
    'Options:',
    '  -p, --print <TASK>        Run one task and exit',
    '  -w, --working-dir <PATH>  Working directory for tools (default: cwd)',
    '  -s, --standalone [TASK]   Run without interactive human review',
    '  -h, --help                Show help',
  ].join('\n');
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    workingDir: process.cwd(),
    standalone: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '-h' || arg === '--help') {
      args.help = true;
      continue;
    }

    if (arg === '-p' || arg === '--print') {
      if (!argv[i + 1]) {
        throw new Error('Missing value for --print');
      }
      args.task = argv[i + 1];
      i += 1;
      continue;
    }

    if (arg === '-w' || arg === '--working-dir') {
      if (!argv[i + 1]) {
        throw new Error('Missing value for --working-dir');
      }
      args.workingDir = argv[i + 1];
      i += 1;
      continue;
    }

    if (arg === '-s' || arg === '--standalone') {
      args.standalone = true;
      if (argv[i + 1] && !argv[i + 1].startsWith('-')) {
        args.standaloneTask = argv[i + 1];
        i += 1;
      }
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

function pathsFromHere(): { configDir: string; profilesFile: string } {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  return {
    configDir: join(rootDir, 'config'),
    profilesFile: join(rootDir, 'js', 'profiles.yml'),
  };
}

async function runMachine(task: string, workingDir: string, humanReview = true): Promise<any> {
  const { configDir, profilesFile } = pathsFromHere();

  const hooks = new CLIToolHooks(workingDir, !humanReview);
  const agentRegistry = new AgentAdapterRegistry();
  agentRegistry.register(new CodexAwareFlatAgentAdapter());

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    profilesFile,
    hooks,
    agentRegistry,
  });

  return await machine.execute({
    task,
    working_dir: workingDir,
  });
}

async function runStandalone(task: string, workingDir: string): Promise<any> {
  const result = await runMachine(task, workingDir, false);

  console.log('='.repeat(60));
  console.log('DONE');
  console.log('='.repeat(60));

  if (result && typeof result === 'object' && typeof result.result === 'string' && result.result) {
    console.log(result.result);
  }

  return result;
}

async function prompt(question: string): Promise<string | null> {
  const rl = createInterface({ input, output });
  try {
    const answer = await rl.question(question);
    return answer.trim();
  } catch {
    return null;
  } finally {
    rl.close();
  }
}

async function repl(workingDir: string): Promise<void> {
  console.log(`Tool Use CLI — ${workingDir}`);
  console.log();

  while (true) {
    const task = await prompt('> ');
    if (task === null) {
      console.log();
      break;
    }

    if (!task) {
      continue;
    }

    try {
      await runMachine(task, workingDir, true);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.log(`Error: ${message}`);
    }

    console.log();
  }
}

async function main(): Promise<void> {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(message);
    console.error();
    console.error(usage());
    process.exit(2);
    return;
  }

  if (args.help) {
    console.log(usage());
    return;
  }

  const workingDir = resolve(args.workingDir);

  if (args.standalone) {
    const task = args.standaloneTask ?? args.task;
    if (!task) {
      console.error('--standalone requires a task (--standalone "task" or -p "task" --standalone)');
      process.exit(2);
      return;
    }
    await runStandalone(task, workingDir);
    return;
  }

  if (args.task) {
    await runMachine(args.task, workingDir, true);
    return;
  }

  await repl(workingDir);
}

main().catch(error => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
