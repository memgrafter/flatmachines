#!/usr/bin/env node
import { FlatMachine, MemoryBackend, inMemoryResultBackend } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

async function main() {
  // Keep parity with Python golden example: run peering_demo.yml
  const persistenceBackend = new MemoryBackend();
  const resultBackend = inMemoryResultBackend;

  console.log('=== Peering Example ===');
  console.log('Launching peering demo machine...\n');

  const peeringDemo = new FlatMachine({
    config: join(configDir, 'peering_demo.yml'),
    configDir,
    persistence: persistenceBackend,
    resultBackend,
  });

  try {
    const result = await peeringDemo.execute();
    console.log('Demo result:', JSON.stringify(result, null, 2));

    console.log('\n=== Checkpoint/Resume Demo ===');
    if (peeringDemo.executionId) {
      console.log(`Execution ID: ${peeringDemo.executionId}`);
      console.log('Could resume from checkpoint using this ID');
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
