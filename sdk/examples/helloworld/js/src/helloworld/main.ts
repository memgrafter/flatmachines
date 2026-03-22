#!/usr/bin/env node
import {
  FlatMachine,
  MachineHooks,
  HooksRegistry,
  setupLogging,
  getLogger,
} from '@memgrafter/flatmachines';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// Configure logging
setupLogging({ level: 'INFO' });
const logger = getLogger('helloworld');

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..', '..');
const configDir = join(rootDir, 'config');

/**
 * Hooks for the HelloWorld demo with append_char action.
 *
 * Uses HooksRegistry so the machine config can reference hooks by name
 * (hooks: "hello-world-hooks" in machine.yml).
 */
class HelloWorldHooks implements MachineHooks {
  onStateExit(state: string, context: Record<string, any>, output: any) {
    if (state === 'build_char' && output) {
      const nextChar: string | undefined =
        typeof output === 'string' ? output : (output.next_char ?? output.content);
      if (nextChar !== undefined && nextChar !== null) {
        const ch = String(nextChar)[0];
        const current: string = context.current ?? '';
        const expected: string | undefined = context.expected_char;
        const status = expected !== undefined && ch === expected ? 'match' : 'mismatch';
        console.log(`${current}${ch} (${status})`);
      }
    }
    return output;
  }

  onAction(action: string, context: Record<string, any>) {
    if (action === 'append_char') {
      const lastOutput = context.last_output ?? '';
      if (lastOutput) {
        context.current = (context.current ?? '') + String(lastOutput)[0];
      }
    }
    return context;
  }
}

async function main() {
  logger.info('--- Starting FlatMachine HelloWorld Demo ---');

  // Register hooks by name so machine.yml can reference them
  const hooksRegistry = new HooksRegistry();
  hooksRegistry.register('hello-world-hooks', HelloWorldHooks);

  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooksRegistry,
  });

  logger.info(`Machine: ${machine.config?.data?.name ?? 'unknown'}`);
  logger.info(`States: ${Object.keys(machine.config?.data?.states ?? {})}`);

  const target = 'Hello, World!';
  logger.info(`Target: '${target}'`);
  logger.info('Building character by character...');

  try {
    const result = await machine.execute({ target });

    logger.info('--- Execution Complete ---');
    logger.info(`Final: '${result?.result ?? ''}'`);

    if (result?.success) {
      logger.info('Success! The machine built the string correctly.');
    } else {
      logger.warning('Failure. The machine did not build the string correctly.');
    }

    logger.info('--- Execution Statistics ---');
    logger.info(`Total Cost: $${(machine as any).totalCost?.toFixed(4) ?? '0.0000'}`);
    logger.info(`Total API Calls: ${(machine as any).totalApiCalls ?? 0}`);
  } catch (error) {
    logger.error(`Error: ${error}`);
  }
}

main();
