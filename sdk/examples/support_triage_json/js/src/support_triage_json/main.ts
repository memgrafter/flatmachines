#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

async function main() {
  const machine = new FlatMachine({
    config: join(configDir, 'machine.json'),
    configDir,
  });

  const inputData = {
    ticket_id: 'TCK-1042',
    customer_message: 'My account was charged twice for last month.',
    customer_tier: 'pro',
    preferred_tone: 'friendly',
  };

  try {
    console.log('='.repeat(60));
    console.log('Support Triage JSON Demo (FlatMachine)');
    console.log('='.repeat(60));
    console.log(`Machine: ${machine.config.data.name}`);
    console.log(`States: ${Object.keys(machine.config.data.states).join(', ')}`);
    console.log(`Input: ${JSON.stringify(inputData, null, 2)}`);
    console.log('-'.repeat(60));

    const result = await machine.execute(inputData);

    console.log('='.repeat(60));
    console.log('RESULT');
    console.log('='.repeat(60));
    console.log(JSON.stringify(result, null, 2));

    const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
    const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;

    console.log('--- Statistics ---');
    if (typeof totalApiCalls === 'number' || typeof totalCost === 'number') {
      if (typeof totalApiCalls === 'number') {
        console.log(`Total API calls: ${totalApiCalls}`);
      }
      if (typeof totalCost === 'number') {
        console.log(`Estimated cost: $${totalCost.toFixed(4)}`);
      }
    } else {
      console.log('Stats are not available in the JS SDK yet.');
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
