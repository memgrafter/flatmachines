import type { MachineHooks } from '@memgrafter/flatmachines';

export class CodexCliHooks implements MachineHooks {
  onStateEnter(state: string, context: Record<string, any>): Record<string, any> {
    console.log(`\n${'─'.repeat(60)}`);
    console.log(`  State: ${state}`);
    console.log(`${'─'.repeat(60)}`);
    return context;
  }

  onMachineEnd(context: Record<string, any>, output: any): any {
    const threadId = context?.thread_id;
    if (threadId) {
      console.log(`\nFinal thread: ${threadId}`);
    }
    return output;
  }
}
