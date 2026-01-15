#!/usr/bin/env node
import { FlatMachine, MachineHooks } from 'flatagents';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import * as readline from 'node:readline';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..', '..');
const configDir = join(rootDir, 'config');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

class HumanInLoopHooks implements MachineHooks {
  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action !== 'human_review') {
      return context;
    }

    console.log('\n' + '='.repeat(60));
    console.log('HUMAN REVIEW REQUIRED');
    console.log('='.repeat(60));
    console.log(`\nRevision #${context.revision_count ?? 1}`);
    console.log('\nCurrent Draft:');
    console.log('-'.repeat(40));
    console.log(context.draft ?? '(No draft yet)');
    console.log('-'.repeat(40));

    const response = (await this.askQuestion(
      '\nApprove? (y/yes to approve, or enter feedback): '
    )).trim();

    if (response === '' || response.toLowerCase() === 'y' || response.toLowerCase() === 'yes') {
      context.human_approved = true;
      context.human_feedback = null;
      console.log('✓ Draft approved!');
    } else {
      context.human_approved = false;
      context.human_feedback = response;
      console.log('→ Feedback recorded. Requesting revision...');
    }

    console.log('='.repeat(60) + '\n');
    return context;
  }

  private askQuestion(question: string): Promise<string> {
    return new Promise((resolve) => {
      rl.question(question, resolve);
    });
  }
}

async function main() {
  const hooks = new HumanInLoopHooks();
  const machine = new FlatMachine({
    config: join(configDir, 'machine.yml'),
    configDir,
    hooks: hooks,
  });

  try {
    const result = await machine.execute({
      topic: 'the benefits of daily exercise',
      max_revisions: 3,
    });
    console.log('\n=== Final Result ===');
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error('Error:', error);
  } finally {
    rl.close();
  }
}

main();
