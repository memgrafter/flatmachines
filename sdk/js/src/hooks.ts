import { MachineHooks } from './types';

export class WebhookHooks implements MachineHooks {
  constructor(private url: string) {}

  private async send(event: string, data: Record<string, any>) {
    try {
      const body = JSON.stringify({ event, ...data, timestamp: new Date().toISOString() }, (key, value) => {
        if (typeof value === 'object' && value !== null) {
          const seen = new WeakSet();
          return JSON.parse(JSON.stringify(value, (k, v) => {
            if (typeof v === 'object' && v !== null) {
              if (seen.has(v)) return '[Circular]';
              seen.add(v);
            }
            return v;
          }));
        }
        return value;
      });
      await fetch(this.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
    } catch {
      // Silently ignore webhook errors - hooks should not break the machine
    }
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
        try {
          result = await hook.onMachineStart(result);
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }

  async onMachineEnd(context: Record<string, any>, output: any): Promise<any> {
    let result = output;
    for (const hook of this.hooks) {
      if (hook.onMachineEnd) {
        try {
          result = await hook.onMachineEnd(context, result);
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }

  async onStateEnter(state: string, context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.onStateEnter) {
        try {
          result = await hook.onStateEnter(state, result);
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }

  async onStateExit(state: string, context: Record<string, any>, output: any): Promise<any> {
    let result = output;
    for (const hook of this.hooks) {
      if (hook.onStateExit) {
        try {
          result = await hook.onStateExit(state, context, result);
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }

  async onTransition(from: string, to: string, context: Record<string, any>): Promise<string> {
    let result = to;
    for (const hook of this.hooks) {
      if (hook.onTransition) {
        try {
          result = await hook.onTransition(from, result, context);
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }

  async onError(state: string, error: Error, context: Record<string, any>): Promise<string | null> {
    let result: string | null = null;
    for (const hook of this.hooks) {
      if (hook.onError) {
        try {
          const hookResult = await hook.onError(state, error, context);
          if (hookResult !== null) result = hookResult;
        } catch {
          // Continue with next hook on error
        }
      }
    }
    return result;
  }
}
