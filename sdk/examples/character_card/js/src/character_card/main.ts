#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync } from 'fs';
import { CharacterCardHooks } from './hooks.js';

type Args = {
  cardPath?: string;
  userName: string;
  userPersona?: string;
  personaFile?: string;
  messagesFile?: string;
  noSystemPrompt: boolean;
  autoUser: boolean;
  maxTurns?: number;
};

function parseArgs(argv: string[]): Args {
  const args: Args = {
    userName: 'User',
    noSystemPrompt: false,
    autoUser: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--') && !args.cardPath) {
      args.cardPath = arg;
      continue;
    }

    if (arg === '--user' || arg === '-u') {
      if (argv[i + 1]) {
        args.userName = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--persona' || arg === '-p') {
      if (argv[i + 1]) {
        args.userPersona = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--persona-file') {
      if (argv[i + 1]) {
        args.personaFile = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--messages-file' || arg === '-m') {
      if (argv[i + 1]) {
        args.messagesFile = argv[i + 1];
        i += 1;
      }
    } else if (arg === '--no-system-prompt') {
      args.noSystemPrompt = true;
    } else if (arg === '--auto-user' || arg === '-a') {
      args.autoUser = true;
    } else if (arg === '--max-turns' || arg === '-t') {
      if (argv[i + 1]) {
        const parsed = Number(argv[i + 1]);
        if (!Number.isNaN(parsed)) {
          args.maxTurns = parsed;
        }
        i += 1;
      }
    }
  }

  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (!args.cardPath) {
    console.error('Usage: node dist/character_card/main.js <card.png|card.json> [options]');
    process.exit(1);
  }

  if (!existsSync(args.cardPath)) {
    console.error(`Card file not found: ${args.cardPath}`);
    process.exit(1);
  }

  if (args.autoUser && args.maxTurns === undefined) {
    args.maxTurns = 1;
  }

  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const rootDir = join(__dirname, '..', '..', '..');
  const configDir = join(rootDir, 'config');

  const hooks = new CharacterCardHooks({
    cardPath: args.cardPath,
    userName: args.userName,
    userPersona: args.userPersona ?? null,
    personaFile: args.personaFile ?? null,
    messagesFile: args.messagesFile ?? null,
    noSystemPrompt: args.noSystemPrompt,
    autoUser: args.autoUser,
    maxTurns: args.maxTurns ?? null,
    configDir,
  });

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooks,
  });

  console.log('\nType \'/quit\' to exit.\n');

  try {
    const result = await machine.execute({});

    console.log('='.repeat(60));
    console.log('Chat ended');
    console.log(`Character: ${result?.character ?? 'Unknown'}`);
    console.log(`Messages: ${result?.turns ?? 0}`);

    const totalApiCalls = (machine as any).total_api_calls ?? (machine as any).totalApiCalls;
    const totalCost = (machine as any).total_cost ?? (machine as any).totalCost;
    console.log(`API calls: ${typeof totalApiCalls === 'number' ? totalApiCalls : 'n/a'}`);
    console.log(`Cost: ${typeof totalCost === 'number' ? `$${totalCost.toFixed(4)}` : 'n/a'}`);
    console.log('='.repeat(60));
  } catch (error) {
    console.error('Error:', error);
  }
}

main();
