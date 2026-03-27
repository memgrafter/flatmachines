#!/usr/bin/env node
import { FlatMachine, HooksRegistry } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { readFileSync, existsSync } from 'fs';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { RLMHooks } from './hooks.js';

type Args = {
  file?: string;
  task?: string;
  chunkSize: number;
  maxExplorationRounds: number;
  interactive: boolean;
  demo: boolean;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    chunkSize: 16000,
    maxExplorationRounds: 5,
    interactive: false,
    demo: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--file' || arg === '-f') {
      if (argv[i + 1]) {
        args.file = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--task' || arg === '-t') {
      if (argv[i + 1]) {
        args.task = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--chunk-size' || arg === '-c') {
      if (argv[i + 1]) {
        const parsed = Number(argv[i + 1]);
        if (!Number.isNaN(parsed)) {
          args.chunkSize = parsed;
        }
        i += 1;
      }
    } else if (arg === '--max-exploration-rounds' || arg === '-r') {
      if (argv[i + 1]) {
        const parsed = Number(argv[i + 1]);
        if (!Number.isNaN(parsed)) {
          args.maxExplorationRounds = parsed;
        }
        i += 1;
      }
    } else if (arg === '--interactive') {
      args.interactive = true;
    } else if (arg === '--demo') {
      args.demo = true;
    }
  }

  return args;
}

async function runRlm(context: string, task: string, maxChunkSize: number, maxExplorationRounds: number) {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');

  const hooksRegistry = new HooksRegistry();
  hooksRegistry.register('rlm', RLMHooks);

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooksRegistry,
  });

  console.log(`Starting RLM with context of ${context.length} characters`);
  console.log(`Task: ${task}`);

  const result = await machine.execute({
    context,
    task,
    max_chunk_size: maxChunkSize,
    max_exploration_rounds: maxExplorationRounds,
  });

  const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
  const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
  console.log(`RLM completed. API calls: ${typeof totalApiCalls === 'number' ? totalApiCalls : 'n/a'}, Cost: ${typeof totalCost === 'number' ? `$${totalCost.toFixed(4)}` : 'n/a'}`);

  return result;
}

async function runFromFile(filePath: string, task: string, chunkSize: number, rounds: number) {
  if (!existsSync(filePath)) {
    throw new Error(`File not found: ${filePath}`);
  }

  const context = readFileSync(filePath, 'utf8');
  console.log(`Loaded ${context.length} characters from ${filePath}`);

  return runRlm(context, task, chunkSize, rounds);
}

async function interactiveMode() {
  console.log('='.repeat(60));
  console.log('RLM Interactive Mode');
  console.log('Based on arXiv:2512.24601 - Recursive Language Models');
  console.log('='.repeat(60));
  console.log('Enter your task/question:');

  const rl = createInterface({ input, output });
  const task = (await rl.question('> ')).trim();

  if (!task) {
    console.log('No task provided. Exiting.');
    rl.close();
    return;
  }

  console.log('\nPaste context, then type "__END__" on its own line to finish:');
  const lines: string[] = [];
  for await (const line of rl) {
    if (line.trim() === '__END__') {
      break;
    }
    lines.push(line);
  }
  rl.close();

  const context = lines.join('\n');
  if (!context.trim()) {
    console.log('No context provided. Exiting.');
    return;
  }

  console.log(`\nContext loaded: ${context.length} characters`);
  console.log('-'.repeat(40));

  const result = await runRlm(context, task, 16000, 5);

  console.log(`\n${'='.repeat(60)}`);
  console.log('RESULT');
  console.log('='.repeat(60));
  console.log(`\nAnswer: ${result?.answer ?? 'No answer'}`);
  console.log(`\nConfidence: ${result?.confidence ?? 'unknown'}`);
  console.log(`\nMethod: ${result?.method ?? 'unknown'}`);

  if (result?.reasoning) {
    console.log(`\nReasoning: ${result.reasoning}`);
  }

  if (result?.caveats) {
    console.log(`\nCaveats: ${Array.isArray(result.caveats) ? result.caveats.join(', ') : result.caveats}`);
  }

  console.log(`\nExploration rounds: ${result?.exploration_rounds ?? 0}`);
  console.log(`Sub-tasks processed: ${result?.sub_tasks_processed ?? 0}`);
}

async function demo() {
  const sections: string[] = [];
  for (let i = 0; i < 5; i += 1) {
    sections.push(`
## Section ${i + 1}: Topic Alpha-${i}

This is the content of section ${i + 1}. It contains various information
about topic Alpha-${i}. The key finding in this section is that the value
for metric X is ${(i * 17) % 100}.

Additional details include:
- Point A: ${i * 3}
- Point B: ${i * 7}
- Point C: ${i * 11}

${i === 2 ? `IMPORTANT: The secret code is RLM-${42 + i}` : ''}
`);
  }

  const context = sections.join('\n');
  const task = 'What is the secret code mentioned in the document?';

  console.log('='.repeat(60));
  console.log('RLM Demo');
  console.log('='.repeat(60));
  console.log(`Context: ${context.length} characters (~${Math.floor(context.length / 4)} tokens)`);
  console.log(`Task: ${task}`);
  console.log('='.repeat(60));

  const result = await runRlm(context, task, 16000, 5);

  console.log(`\n${'='.repeat(60)}`);
  console.log('RESULT');
  console.log('='.repeat(60));
  console.log(`Answer: ${result?.answer ?? 'No answer'}`);
  console.log(`Method: ${result?.method ?? 'unknown'}`);
  console.log(`Exploration rounds: ${result?.exploration_rounds ?? 0}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.demo) {
    await demo();
    return;
  }

  if (args.interactive) {
    await interactiveMode();
    return;
  }

  if (!args.file || !args.task) {
    console.error('Usage: node dist/rlm/main.js --file <path> --task "question" [--chunk-size N] [--max-exploration-rounds N]');
    console.error('       node dist/rlm/main.js --interactive');
    console.error('       node dist/rlm/main.js --demo');
    process.exit(1);
  }

  const result = await runFromFile(args.file, args.task, args.chunkSize, args.maxExplorationRounds);

  console.log(`\n${'='.repeat(60)}`);
  console.log('RESULT');
  console.log('='.repeat(60));
  console.log(`Answer: ${result?.answer ?? 'No answer'}`);
  console.log(`Confidence: ${result?.confidence ?? 'unknown'}`);
  console.log(`Method: ${result?.method ?? 'unknown'}`);
}

main().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
