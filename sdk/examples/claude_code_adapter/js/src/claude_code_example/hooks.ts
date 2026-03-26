import type { MachineHooks } from '@memgrafter/flatmachines';

function bold(text: string): string {
  return `\u001b[1m${text}\u001b[0m`;
}

export class ClaudeCodeHooks implements MachineHooks {
  onStateEnter(state: string, context: Record<string, any>): Record<string, any> {
    console.log(`\n${'─'.repeat(60)}`);
    console.log(`  State: ${bold(state)}`);
    console.log(`${'─'.repeat(60)}`);
    return context;
  }

  onMachineEnd(context: Record<string, any>, output: any): any {
    const sessionId = context?.session_id;
    if (sessionId) {
      console.log(`\nSession: ${sessionId}`);
    }
    return output;
  }
}
