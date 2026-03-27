#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { OTFAgentHooks } from './hooks.js';

type Args = {
  task: string;
  styleHints: string;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    task: 'Write a haiku about the beauty of mountain sunrises',
    styleHints: '',
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--style' && argv[i + 1]) {
      args.styleHints = argv[i + 1];
      i += 1;
    } else if (!arg.startsWith('--') && !args.task) {
      args.task = arg;
    } else if (!arg.startsWith('--') && args.task === 'Write a haiku about the beauty of mountain sunrises') {
      args.task = arg;
    }
  }

  return args;
}

async function main() {
  const { task, styleHints } = parseArgs(process.argv.slice(2));

  console.log(`\n${'='.repeat(70)}`);
  console.log('DYNAMIC AGENT - On-The-Fly Agent Generation');
  console.log('='.repeat(70));
  console.log(`\nTask: ${task}`);
  if (styleHints) {
    console.log(`Style hints: ${styleHints}`);
  }
  console.log('\n');

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');

  const hooks = new OTFAgentHooks(configDir);

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooks,
  });

  try {
    const result = await machine.execute({
      task,
      style_hints: styleHints,
    });

    console.log(`\n${'='.repeat(70)}`);
    console.log('FINAL RESULT');
    console.log('='.repeat(70));

    if (result?.error) {
      console.log(`\n❌ Error: ${result.error}`);
      if (result?.last_concerns) {
        console.log(`Last concerns: ${result.last_concerns}`);
      }
    } else {
      console.log(`\n📝 Content:\n${result?.content ?? '(none)'}`);
      console.log(`\n📊 Attempts: ${result?.attempts ?? 'N/A'}`);
    }

    console.log('\n📈 Metrics:');
    const metrics = hooks.getMetrics();
    for (const [key, value] of Object.entries(metrics)) {
      console.log(`   ${key}: ${value}`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.toLowerCase().includes('cancelled')) {
      console.log('\n\nExecution cancelled by user.');
      process.exit(0);
    }
    console.error('Error:', error);
  }
}

main();
