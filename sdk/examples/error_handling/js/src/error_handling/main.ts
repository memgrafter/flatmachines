#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

async function main() {
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    console.log(`Machine: ${machine.config.data.name}`);
    console.log(`States: ${Object.keys(machine.config.data.states).join(', ')}`);

    const result = await machine.execute({ task: 'Analyze market trends' });

    console.log('Result:');
    console.log(`  Success: ${result?.success}`);
    if (result?.success) {
      console.log(`  Result: ${result?.result}`);
    } else {
      console.log(`  Summary: ${result?.summary}`);
      console.log(`  Error: ${result?.error_type}`);
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
