#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

async function runBasicParallel() {
  console.log('=== Basic Parallel Execution ===');
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    const result = await machine.execute({
      type: 'parallel_aggregation',
      texts: [
        'Machine learning is transforming technology',
        'Quantum computing promises exponential speedup',
        'AI assistants are becoming ubiquitous',
      ],
    });
    console.log('Parallel result:', JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Parallel error:', error);
  }
}

async function runForeach() {
  console.log('\n=== Dynamic Parallelism (foreach) ===');
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    const result = await machine.execute({
      type: 'foreach_sentiment',
      texts: [
        'I love this new feature!',
        'This is absolutely terrible.',
        "It's okay, nothing special.",
        'Amazing work, keep it up!',
      ],
    });
    console.log('Foreach result:', JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Foreach error:', error);
  }
}

async function runFireAndForget() {
  console.log('\n=== Fire-and-Forget Launches ===');
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    const result = await machine.execute({
      type: 'background_notifications',
      message: 'System maintenance scheduled',
    });
    console.log('Fire-and-forget result:', JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Fire-and-forget error:', error);
  }
}

async function main() {
  console.log('Starting FlatAgents Parallelism Demo');
  console.log('====================================');

  await runBasicParallel();
  await runForeach();
  await runFireAndForget();
}

main();
