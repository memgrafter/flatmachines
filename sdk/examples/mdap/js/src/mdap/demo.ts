#!/usr/bin/env node
import { FlatAgent, FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

async function run() {
  console.log('='.repeat(60));
  console.log('MDAP - Tower of Hanoi Demo (FlatMachine)');
  console.log('='.repeat(60));

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');

  const machinePath = join(configDir, 'machine.yml');
  console.log(`Loading machine from: ${machinePath}`);

  const machine = new FlatMachine({
    config: machinePath,
    configDir,
  });

  console.log(`Machine: ${machine.config?.data?.name ?? 'unknown'}`);
  console.log(`States: ${Object.keys(machine.config?.data?.states ?? {}).join(', ')}`);

  // Read hanoi metadata for initial/goal settings (same as Python demo)
  const agent = new FlatAgent({ config: join(configDir, 'hanoi.yml'), configDir });
  const agentConfig = (agent as any).config ?? {};
  const metadata = agentConfig.metadata ?? {};
  const hanoiConfig = metadata.hanoi ?? {};
  const initialPegs = (hanoiConfig.initial_pegs as number[][] | undefined) ?? [[3, 2, 1], [], []];
  const goalPegs = (hanoiConfig.goal_pegs as number[][] | undefined) ?? [[], [3, 2, 1], []];

  const solveStep = machine.config?.data?.states?.solve_step ?? {};
  const execution = solveStep.execution ?? {};
  console.log('Execution Config (from machine.yml):');
  console.log(`  type: ${execution.type ?? 'default'}`);
  console.log(`  k_margin: ${execution.k_margin ?? 'N/A'}`);
  console.log(`  max_candidates: ${execution.max_candidates ?? 'N/A'}`);

  console.log(`Initial state: ${JSON.stringify(initialPegs)}`);
  console.log(`Goal: ${JSON.stringify(goalPegs)}`);
  console.log('-'.repeat(60));
  console.log('Starting FlatMachine execution...');

  const result = await machine.execute({
    initial_pegs: initialPegs,
    goal_pegs: goalPegs,
  });

  console.log('-'.repeat(60));
  console.log('Execution Complete!');
  console.log('-'.repeat(60));
  console.log(`Final state: ${JSON.stringify(result?.pegs)}`);
  console.log(`Solved: ${Boolean(result?.solved)}`);
  console.log(`Total steps: ${result?.steps ?? 0}`);

  const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
  const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
  console.log(`Total API calls: ${typeof totalApiCalls === 'number' ? totalApiCalls : 'n/a'}`);
  console.log(`Estimated cost: ${typeof totalCost === 'number' ? `$${totalCost.toFixed(4)}` : 'n/a'}`);
  console.log('='.repeat(60));
}

run().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
