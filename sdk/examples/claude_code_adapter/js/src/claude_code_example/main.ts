#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import { ClaudeCodeHooks } from './hooks.js';

type Args = {
  task?: string;
  workingDir: string;
  multiState: boolean;
  configName?: string;
  help: boolean;
};

function usage(): string {
  return [
    'Claude Code adapter example (JS)',
    '',
    'Usage:',
    '  node dist/claude_code_example/main.js -p "add a /health endpoint"',
    '  node dist/claude_code_example/main.js -p "task" --multi-state',
    '  node dist/claude_code_example/main.js -p "task" --config machine_with_refs.yml',
    '',
    'Options:',
    '  -p, --print <TASK>        Task to execute',
    '  -w, --working-dir <PATH>  Working directory for Claude Code',
    '      --multi-state         Use plan→implement→test machine',
    '      --config <FILE>       Config filename from config/',
    '  -h, --help                Show this help',
  ].join('\n');
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    workingDir: process.cwd(),
    multiState: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '-h' || arg === '--help') {
      args.help = true;
      continue;
    }

    if (arg === '-p' || arg === '--print') {
      if (!argv[i + 1]) throw new Error('Missing value for --print');
      args.task = argv[++i];
      continue;
    }

    if (arg === '-w' || arg === '--working-dir') {
      if (!argv[i + 1]) throw new Error('Missing value for --working-dir');
      args.workingDir = argv[++i] ?? args.workingDir;
      continue;
    }

    if (arg === '--multi-state') {
      args.multiState = true;
      continue;
    }

    if (arg === '--config') {
      if (!argv[i + 1]) throw new Error('Missing value for --config');
      args.configName = argv[++i] ?? undefined;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const configDir = join(__dirname, '..', '..', '..', 'config');

function configPath(name: string): string {
  return join(configDir, name);
}

async function run(task: string, workingDir: string, multiState: boolean, configName?: string): Promise<any> {
  const hooks = new ClaudeCodeHooks();

  const configFile = configName
    ? configPath(configName)
    : multiState
      ? configPath('machine_multi_state.yml')
      : configPath('machine.yml');

  const machine = new FlatMachine({
    config: configFile,
    configDir,
    hooks,
  });

  const usesFeature = multiState || Boolean(configName && configName.includes('ref'));
  const inputData: Record<string, any> = {
    working_dir: workingDir,
  };
  if (usesFeature) inputData.feature = task;
  else inputData.task = task;

  const result = await machine.execute(inputData);

  console.log();
  console.log('='.repeat(60));
  console.log('DONE');
  console.log('='.repeat(60));

  const content = (result && typeof result === 'object')
    ? (result.result ?? result.review ?? '')
    : result;

  if (content) {
    const text = String(content).replaceAll('<<AGENT_EXIT>>', '').trim();
    console.log(text);
  }

  return result;
}

async function main(): Promise<void> {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    console.error();
    console.error(usage());
    process.exit(2);
    return;
  }

  if (args.help) {
    console.log(usage());
    return;
  }

  if (!args.task) {
    console.error('Task is required. Use -p/--print "..."');
    process.exit(2);
    return;
  }

  await run(args.task, resolve(args.workingDir), args.multiState, args.configName);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
