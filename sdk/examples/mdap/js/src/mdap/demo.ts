#!/usr/bin/env node
import { FlatAgent } from '@memgrafter/flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { MDAPOrchestrator } from './mdap.js';

async function run() {
  console.log('='.repeat(60));
  console.log('MDAP - Tower of Hanoi Demo');
  console.log('='.repeat(60));

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configPath = join(rootDir, 'config', 'hanoi.yml');

  console.log(`Loading agent from: ${configPath}`);

  const agent = new FlatAgent({ config: configPath, configDir: join(rootDir, 'config') });
  const agentConfig = (agent as any).config ?? {};

  console.log(`Agent: ${agentConfig?.data?.name ?? 'unknown'}`);
  console.log(`Model: ${agentConfig?.data?.model ?? 'unknown'}`);

  const orchestrator = new MDAPOrchestrator(agent);

  console.log('MDAP Config:');
  console.log(`  k_margin: ${orchestrator.config.k_margin}`);
  console.log(`  max_candidates: ${orchestrator.config.max_candidates}`);
  console.log(`  max_steps: ${orchestrator.config.max_steps}`);

  const metadata = agentConfig.metadata ?? {};
  const hanoiConfig = metadata.hanoi ?? {};
  const initialPegs = (hanoiConfig.initial_pegs as number[][] | undefined) ?? [[4, 3, 2, 1], [], []];
  const goalPegs = (hanoiConfig.goal_pegs as number[][] | undefined) ?? [[], [4, 3, 2, 1], []];

  const pegs: number[][] = initialPegs.map((peg: number[]) => [...peg]);
  let previousMove: number[] | null = null;
  let moveCount = 0;

  console.log(`Initial state: ${JSON.stringify(pegs)}`);
  console.log(`Goal: ${JSON.stringify(goalPegs)}`);
  console.log('-'.repeat(60));
  console.log('Starting MDAP execution...');

  const trace: Array<{ pegs: number[][]; move_count: number; previous_move: number[] | null }> = [
    { pegs: pegs.map((peg: number[]) => [...peg]), move_count: 0, previous_move: null },
  ];

  for (let step = 1; step <= orchestrator.config.max_steps; step += 1) {
    if (JSON.stringify(pegs) === JSON.stringify(goalPegs)) {
      console.log(`Solved after ${step - 1} steps`);
      break;
    }

    console.log(`Step ${step}: ${JSON.stringify(pegs)}`);

    const inputData = {
      pegs,
      previous_move: previousMove,
    };

    const { result, samples } = await orchestrator.firstToAheadByK(inputData);
    orchestrator.metrics.samples_per_step.push(samples);

    if (!result) {
      console.log(`Step ${step} failed - no valid response`);
      break;
    }

    console.log(`Step ${step} result: ${JSON.stringify(result)} (samples: ${samples})`);

    pegs.splice(0, pegs.length, ...(result.predicted_state as number[][]));
    previousMove = result.move as number[];
    moveCount += 1;

    trace.push({
      pegs: pegs.map((peg: number[]) => [...peg]),
      move_count: moveCount,
      previous_move: previousMove,
    });
  }

  console.log('-'.repeat(60));
  console.log('Execution Complete!');
  console.log('-'.repeat(60));

  console.log('Execution trace:');
  trace.forEach((state, index) => {
    console.log(`  Step ${index}: ${JSON.stringify(state.pegs)}`);
  });

  const finalPegs = trace[trace.length - 1]?.pegs ?? pegs;
  const solved = JSON.stringify(finalPegs) === JSON.stringify(goalPegs);

  console.log(`Final state: ${JSON.stringify(finalPegs)}`);
  console.log(`Solved: ${solved}`);
  console.log(`Total moves: ${moveCount}`);

  console.log('-'.repeat(60));
  console.log('Statistics');
  console.log('-'.repeat(60));
  console.log(`Total samples: ${orchestrator.metrics.total_samples}`);
  console.log(`Samples per step: ${JSON.stringify(orchestrator.metrics.samples_per_step)}`);
  if (orchestrator.metrics.samples_per_step.length) {
    const avg = orchestrator.metrics.samples_per_step.reduce((a, b) => a + b, 0) / orchestrator.metrics.samples_per_step.length;
    console.log(`Avg samples/step: ${avg.toFixed(1)}`);
  }

  console.log('Red-flag metrics:');
  console.log(`  Total red-flagged: ${orchestrator.metrics.total_red_flags}`);
  const redFlags = orchestrator.metrics.red_flags_by_reason;
  for (const [reason, count] of Object.entries(redFlags)) {
    console.log(`    ${reason}: ${count}`);
  }

  if (solved) {
    const numDisks = initialPegs[0]?.filter((disk: number) => disk > 0).length ?? 0;
    const optimalMoves = Math.pow(2, numDisks) - 1;
    console.log(`Optimal moves for ${numDisks} disks: ${optimalMoves}`);
    if (moveCount === optimalMoves) {
      console.log('Perfect! Solved in optimal number of moves.');
    } else {
      console.log(`Solved in ${moveCount} moves (${moveCount - optimalMoves} extra)`);
    }
  } else {
    console.log('Failed to solve the puzzle.');
  }

  console.log('='.repeat(60));
}

run().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
