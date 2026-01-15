#!/usr/bin/env node
import { FlatMachine } from '../../src';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function main() {
  console.log('=== Parallel Machines Example ===');
  const parallelMachine = new FlatMachine({
    config: join(__dirname, 'main_machine.yml'),
    configDir: __dirname,
  });

  try {
    const result = await parallelMachine.execute();
    console.log('Parallel result:', JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Parallel error:', error);
  }

  console.log('\n=== ForEach Example ===');
  const foreachMachine = new FlatMachine({
    config: join(__dirname, 'foreach_machine.yml'),
    configDir: __dirname,
  });

  try {
    const result = await foreachMachine.execute();
    console.log('Foreach result:', JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Foreach error:', error);
  }
}

main();