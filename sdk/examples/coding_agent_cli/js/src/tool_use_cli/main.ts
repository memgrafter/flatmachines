#!/usr/bin/env node
import { FlatAgent, FlatMachine, Guardrails, MockLLMBackend, ToolLoopAgent } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { CLIToolHooks } from './hooks.js';
import { CLIToolProvider } from './tools.js';

type Args = {
  task?: string;
  workingDir: string;
  standalone: boolean;
  standaloneTask?: string;
  mock: boolean;
  help: boolean;
};

function usage(): string {
  return [
    'Usage:',
    '  node dist/tool_use_cli/main.js                              # REPL',
    '  node dist/tool_use_cli/main.js -p "list Python files"       # single-shot',
    '  node dist/tool_use_cli/main.js --standalone "task"          # standalone',
    '  node dist/tool_use_cli/main.js --standalone --mock "task"   # deterministic mock standalone',
    '',
    'Options:',
    '  -p, --print <TASK>        Run one task and exit',
    '  -w, --working-dir <PATH>  Working directory for tools (default: cwd)',
    '  -s, --standalone [TASK]   Run without interactive human review',
    '      --mock                Use MockLLMBackend (standalone only)',
    '  -h, --help                Show help',
  ].join('\n');
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    workingDir: process.cwd(),
    standalone: false,
    mock: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];

    if (arg === '-h' || arg === '--help') {
      args.help = true;
      continue;
    }

    if (arg === '--mock') {
      args.mock = true;
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

function configDirFromHere(): string {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  return join(rootDir, 'config');
}

async function runMachine(task: string, workingDir: string): Promise<any> {
  const configDir = configDirFromHere();

  const hooks = new CLIToolHooks(workingDir, false);
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooks,
  });

  return await machine.execute({
    task,
    working_dir: workingDir,
  });
}

function buildStandaloneMockBackend(): MockLLMBackend {
  return new MockLLMBackend([
    {
      content: 'I will inspect the workspace first.',
      raw: {
        text: 'I will inspect the workspace first.',
        finishReason: 'tool_calls',
        toolCalls: [
          {
            toolCallId: 'call_ls_1',
            toolName: 'bash',
            args: { command: 'ls' },
          },
        ],
      },
    },
    {
      content: 'I found files and can summarize the result.',
      raw: {
        text: 'I found files and can summarize the result.',
        finishReason: 'stop',
      },
    },
  ]);
}

async function runStandalone(task: string, workingDir: string, useMock: boolean): Promise<any> {
  const configDir = configDirFromHere();
  const provider = new CLIToolProvider(workingDir);

  const agent = useMock
    ? new FlatAgent({
        config: join(configDir, 'agent.yml'),
        llmBackend: buildStandaloneMockBackend(),
      })
    : new FlatAgent(join(configDir, 'agent.yml'));

  const loop = new ToolLoopAgent({
    agent,
    toolProvider: provider,
    guardrails: {
      max_turns: 30,
      max_tool_calls: 100,
      max_cost: 2.0,
      tool_timeout: 60,
      total_timeout: 600,
    } satisfies Guardrails,
  });

  const result = await loop.run({ task });

  console.log('='.repeat(60));
  console.log('DONE');
  console.log('='.repeat(60));
  console.log(`Stop reason: ${result.stop_reason}`);
  console.log(`Tool calls:  ${result.tool_calls_count}`);
  console.log(`LLM turns:   ${result.turns}`);
  console.log(`API calls:   ${result.usage.api_calls}`);
  console.log(`Cost:        $${result.usage.total_cost.toFixed(4)}`);
  console.log();

  if (result.error) {
    console.log(`Error: ${result.error}`);
  }
  if (result.content) {
    console.log(result.content);
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

  let interruptCount = 0;
  let shouldExit = false;

  const onSigint = () => {
    interruptCount += 1;
    if (interruptCount >= 2) {
      shouldExit = true;
      console.log();
    } else {
      console.log();
    }
  };

  process.on('SIGINT', onSigint);

  try {
    while (!shouldExit) {
      const task = await prompt('> ');
      if (task === null) {
        console.log();
        break;
      }

      if (shouldExit) {
        break;
      }

      if (!task) {
        continue;
      }

      interruptCount = 0;

      try {
        await runMachine(task, workingDir);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.log(`Error: ${message}`);
      }

      console.log();
    }
  } finally {
    process.off('SIGINT', onSigint);
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
    await runStandalone(task, workingDir, args.mock);
    return;
  }

  if (args.mock) {
    console.error('--mock is only supported with --standalone');
    process.exit(2);
    return;
  }

  if (args.task) {
    await runMachine(args.task, workingDir);
    return;
  }

  await repl(workingDir);
}

main().catch(error => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
