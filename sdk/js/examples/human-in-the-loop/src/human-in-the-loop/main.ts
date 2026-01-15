#!/usr/bin/env node
import { FlatMachine, MachineHooks } from '../../src';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import * as readline from 'node:readline';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

class HumanInLoopHooks implements MachineHooks {
  async onStateEnter(state: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (state === 'approval') {
      console.log('\n=== Plan for Review ===');
      console.log(JSON.stringify(context.plan, null, 2));
      
      const approved = await this.askQuestion('Approve this plan? (yes/no): ');
      context.approved = approved.toLowerCase().startsWith('y');
    }
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
    config: join(__dirname, 'machine.yml'),
    configDir: __dirname,
    hooks: hooks,
  });

  try {
    const result = await machine.execute({
      request: 'Build a simple web application'
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