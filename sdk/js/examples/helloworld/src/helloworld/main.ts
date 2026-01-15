#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..');
const configDir = join(rootDir, 'config');

async function main() {
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    const target = "Hello, World!";
    console.log(`Target: '${target}'`);
    console.log('Building character by character...');
    
    const result = await machine.execute({ target });
    console.log('Result:', JSON.stringify(result, null, 2));
    
    if (result?.success) {
      console.log('✅ Success! The machine built the string correctly.');
    } else {
      console.log('❌ Failure. The machine did not build the string correctly.');
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
