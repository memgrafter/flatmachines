#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { join } from 'path';

async function main() {
  const machine = new FlatMachine({
    config: join(process.cwd(), 'config/machine.yml'),
    configDir: join(process.cwd(), 'config'),
  });

  try {
    const target = "Hello, World!";
    console.log(`Target: '${target}'`);
    console.log('Building character by character...');
    
    const result = await machine.execute({ input: { target } });
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