#!/usr/bin/env node
import { FlatMachine } from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { CodexCliHooks } from './hooks.js';

const EXPECTED: Record<string, string> = {
  '68B201E19CB8F6B8': 'build hash',
  'TRIDENT-APEX-9047': 'authorization code',
  'moonshot-cardinal-7': 'cluster name',
};

type Args = {
  testCache: boolean;
  testFanoutCache: boolean;
  help: boolean;
};

function usage(): string {
  return [
    'Codex CLI Adapter — Cache Demos',
    '',
    'Usage:',
    '  node dist/codex_cli_example/main.js --test-cache',
    '  node dist/codex_cli_example/main.js --test-fanout-cache',
  ].join('\n');
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    testCache: false,
    testFanoutCache: false,
    help: false,
  };

  for (const arg of argv) {
    if (arg === '--test-cache') args.testCache = true;
    else if (arg === '--test-fanout-cache') args.testFanoutCache = true;
    else if (arg === '--help' || arg === '-h') args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  if (!args.help && args.testCache === args.testFanoutCache) {
    throw new Error('Choose exactly one: --test-cache or --test-fanout-cache');
  }

  return args;
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const configDir = join(__dirname, '..', '..', '..', 'config');

function configPath(name: string): string {
  return join(configDir, name);
}

async function run(configName: string): Promise<number> {
  const machine = new FlatMachine({
    config: configPath(configName),
    configDir,
    hooks: new CodexCliHooks(),
  });

  const result = await machine.execute({});

  console.log();
  console.log('='.repeat(60));

  if (!result || typeof result !== 'object') {
    console.log(`Unexpected result type: ${typeof result}`);
    return 1;
  }

  let failures = 0;
  const verify = (result as any).verify_result;
  if (verify) {
    const ok = String(verify).toUpperCase().includes('68B201E19CB8F6B8');
    console.log(`${ok ? '✅ PASS' : '❌ FAIL'} — verify_result: ${verify}`);
    if (!ok) failures += 1;
  }

  const fanoutRaw = (result as any).fanout_results;
  if (fanoutRaw) {
    const answers: Record<string, string> = {};

    let fanout: any = fanoutRaw;
    if (typeof fanoutRaw === 'string') {
      try {
        fanout = JSON.parse(fanoutRaw);
      } catch {
        fanout = fanoutRaw;
      }
    }

    if (Array.isArray(fanout)) {
      for (const item of fanout) {
        if (item && typeof item === 'object') {
          answers[String((item as any).question ?? '?')] = String((item as any).answer ?? '');
        }
      }
    } else if (typeof fanout === 'object') {
      for (const [key, value] of Object.entries(fanout as Record<string, any>)) {
        if (value && typeof value === 'object') {
          answers[String((value as any).question ?? key)] = String((value as any).answer ?? '');
        } else {
          answers[key] = String(value ?? '');
        }
      }
    }

    for (const [expectedValue, label] of Object.entries(EXPECTED)) {
      const found = Object.values(answers).some((answer) => answer.toLowerCase().includes(expectedValue.toLowerCase()));
      console.log(`${found ? '✅ PASS' : '❌ FAIL'} — ${label}: expected '${expectedValue}' in answers`);
      if (!found) failures += 1;
    }

    if (Object.keys(answers).length === 0) {
      console.log('❌ FAIL — no answers extracted from fanout_results');
      failures += 1;
    }
  }

  console.log('='.repeat(60));
  console.log(failures ? `❌ ${failures} validation(s) failed` : '✅ All validations passed');

  return failures;
}

async function main(): Promise<void> {
  let args: Args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    console.error();
    console.error(usage());
    process.exit(2);
    return;
  }

  if (args.help) {
    console.log(usage());
    return;
  }

  const config = args.testFanoutCache ? 'machine_fanout_cache_demo.yml' : 'machine_cache_demo.yml';
  const failures = await run(config);
  process.exit(failures);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
