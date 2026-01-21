#!/usr/bin/env node
import { FlatMachine } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

function parseArgs(argv: string[]) {
  const args = { product: 'a CLI tool for AI agents', maxRounds: 4, targetScore: 8 };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--product' && argv[i + 1]) {
      args.product = argv[i + 1];
      i += 1;
    } else if (arg === '--max-rounds' && argv[i + 1]) {
      const parsed = Number(argv[i + 1]);
      if (!Number.isNaN(parsed)) {
        args.maxRounds = parsed;
      }
      i += 1;
    } else if (arg === '--target-score' && argv[i + 1]) {
      const parsed = Number(argv[i + 1]);
      if (!Number.isNaN(parsed)) {
        args.targetScore = parsed;
      }
      i += 1;
    }
  }
  return args;
}

async function main() {
  const { product, maxRounds, targetScore } = parseArgs(process.argv.slice(2));

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
  });

  try {
    console.log(`Machine: ${machine.config.data.name}`);
    console.log(`States: ${Object.keys(machine.config.data.states).join(', ')}`);
    console.log(`Product: ${product}`);
    console.log(`Target Score: ${targetScore}/10`);
    console.log(`Max Rounds: ${maxRounds}`);
    console.log('-'.repeat(60));

    const result = await machine.execute({
      product,
      target_score: targetScore,
      max_rounds: maxRounds,
    });

    console.log('='.repeat(60));
    console.log('RESULTS');
    console.log('='.repeat(60));
    const scoreValue = Number(result?.score);
    const roundValue = Number(result?.rounds);
    console.log(`Final Tagline: "${result?.tagline ?? ''}"`);
    console.log(`Final Score: ${Number.isFinite(scoreValue) ? scoreValue : 0}/10`);
    console.log(`Rounds: ${Number.isFinite(roundValue) ? roundValue : 0}`);
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
