import { MachineHooks } from './types';

export class WebhookHooks implements MachineHooks {
  constructor(private url: string) {}

  private async send(event: string, data: Record<string, any>) {
    await fetch(this.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, ...data, timestamp: new Date().toISOString() }),
    });
  }

  async onMachineStart(context: Record<string, any>) { 
    await this.send("machine_start", { context }); 
    return context; 
  }
  
  async onMachineEnd(context: Record<string, any>, output: any) { 
    await this.send("machine_end", { context, output }); 
    return output; 
  }
  
  async onStateEnter(state: string, context: Record<string, any>) { 
    await this.send("state_enter", { state, context }); 
    return context; 
  }
  
  async onStateExit(state: string, context: Record<string, any>, output: any) { 
    await this.send("state_exit", { state, context, output }); 
    return output; 
  }
}

export class CompositeHooks implements MachineHooks {
  constructor(private hooks: MachineHooks[]) {}

  async onMachineStart(context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.onMachineStart) {
        result = await hook.onMachineStart(result);
      }
    }
    return result;
  }

  async onMachineEnd(context: Record<string, any>, output: any): Promise<any> {
    let result = output;
    for (const hook of this.hooks) {
      if (hook.onMachineEnd) {
        result = await hook.onMachineEnd(context, result);
      }
    }
    return result;
  }

  async onStateEnter(state: string, context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.onStateEnter) {
        result = await hook.onStateEnter(state, result);
      }
    }
    return result;
  }

  async onStateExit(state: string, context: Record<string, any>, output: any): Promise<any> {
    let result = output;
    for (const hook of this.hooks) {
      if (hook.onStateExit) {
        result = await hook.onStateExit(state, context, result);
      }
    }
    return result;
  }

  async onTransition(from: string, to: string, context: Record<string, any>): Promise<string> {
    let result = to;
    for (const hook of this.hooks) {
      if (hook.onTransition) {
        result = await hook.onTransition(from, result, context);
      }
    }
    return result;
  }

  async onError(state: string, error: Error, context: Record<string, any>): Promise<string | null> {
    let result: string | null = null;
    for (const hook of this.hooks) {
      if (hook.onError) {
        const hookResult = await hook.onError(state, error, context);
        if (hookResult !== null) result = hookResult;
      }
    }
    return result;
  }
}