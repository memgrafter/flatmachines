#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import { CodingAgentHooks } from './hooks.js';

type Args = {
  task?: string;
  cwd: string;
  maxIterations: number;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    cwd: '.',
    maxIterations: 5,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--') && !args.task) {
      args.task = arg;
      continue;
    }

    if (arg === '--cwd' || arg === '-c') {
      if (argv[i + 1]) {
        args.cwd = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--max-iterations' || arg === '-m') {
      if (argv[i + 1]) {
        const parsed = Number(argv[i + 1]);
        if (!Number.isNaN(parsed)) {
          args.maxIterations = parsed;
        }
        i += 1;
      }
    }
  }

  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (!args.task) {
    console.error('Usage: node dist/coding_agent/main.js "task" [--cwd path] [--max-iterations 5]');
    process.exit(1);
  }

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');

  const workingDir = resolve(args.cwd);
  const userCwd = process.cwd();

  console.log('='.repeat(70));
  console.log('🤖 Coding Agent');
  console.log('='.repeat(70));
  console.log(`Machine: coding-agent`);
  console.log(`Task: ${args.task}`);
  console.log(`Working Dir: ${workingDir}`);
  console.log('-'.repeat(70));

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooks: new CodingAgentHooks(workingDir),
  });

  const result = await machine.execute({
    task: args.task,
    cwd: workingDir,
    user_cwd: userCwd,
    max_iterations: args.maxIterations,
  });

  console.log('='.repeat(70));
  console.log('📊 RESULTS');
  console.log('='.repeat(70));
  console.log(`Status: ${result?.status ?? 'unknown'}`);
  console.log(`Iterations: ${result?.iterations ?? 0}`);

  if (result?.changes && typeof result.changes === 'object') {
    const summary = result.changes.summary ?? '';
    const files = Array.isArray(result.changes.files) ? result.changes.files.length : 0;
    if (summary) {
      console.log(`Summary: ${summary}`);
    }
    if (files) {
      console.log(`Files affected: ${files}`);
    }
  }

  console.log('-'.repeat(70));
  const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
  const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
  console.log(`Total API calls: ${typeof totalApiCalls === 'number' ? totalApiCalls : 'n/a'}`);
  console.log(`Estimated cost: ${typeof totalCost === 'number' ? `$${totalCost.toFixed(4)}` : 'n/a'}`);
}

main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
