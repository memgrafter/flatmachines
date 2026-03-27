import type { MachineHooks, HooksFactory, HooksRef } from './types';
import { getLogger } from '@memgrafter/flatagents';

const logger = getLogger('flatmachines.hooks');

export class WebhookHooks implements MachineHooks {
  constructor(private url: string) {}

  private async send(event: string, data: Record<string, any>) {
    try {
      const seen = new WeakSet();
      const body = JSON.stringify({ event, ...data, timestamp: new Date().toISOString() }, (_key, value) => {
        if (typeof value === 'object' && value !== null) {
          if (seen.has(value)) return '[Circular]';
          seen.add(value);
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

  async onAction(action: string, context: Record<string, any>) {
    await this.send("action", { action, context });
    return context;
  }

  async onError(state: string, error: Error, context: Record<string, any>) {
    await this.send("error", { state, error: { message: error.message, name: error.name }, context });
    return null;
  }

  async onCheckpoint(snapshot: any) {
    await this.send("checkpoint", { snapshot: { execution_id: snapshot.execution_id, event: snapshot.event, state: snapshot.current_state } });
  }
}

export class CompositeHooks implements MachineHooks {
  public hooks: MachineHooks[];

  constructor(hooks: MachineHooks[]) {
    this.hooks = hooks;
    // Bind tool-loop hooks so they work when extracted from the instance
    this.on_tool_calls = this.on_tool_calls.bind(this);
    this.on_tool_result = this.on_tool_result.bind(this);
    this.get_tool_provider = this.get_tool_provider.bind(this);
  }

  async onMachineStart(context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.onMachineStart) {
        try {
          result = await hook.onMachineStart(result);
        } catch (e) {
          logger.warning(`Hook onMachineStart failed: ${e instanceof Error ? e.message : String(e)}`);
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
        } catch (e) {
          logger.warning(`Hook onMachineEnd failed: ${e instanceof Error ? e.message : String(e)}`);
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
        } catch (e) {
          logger.warning(`Hook onStateEnter failed in state '${state}': ${e instanceof Error ? e.message : String(e)}`);
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
        } catch (e) {
          logger.warning(`Hook onStateExit failed in state '${state}': ${e instanceof Error ? e.message : String(e)}`);
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
        } catch (e) {
          logger.warning(`Hook onTransition failed (${from} → ${to}): ${e instanceof Error ? e.message : String(e)}`);
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
        } catch (e) {
          logger.warning(`Hook onError failed in state '${state}': ${e instanceof Error ? e.message : String(e)}`);
        }
      }
    }
    return result;
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.onAction) {
        try {
          result = await hook.onAction(action, result);
        } catch (e) {
          logger.warning(`Hook onAction failed for '${action}': ${e instanceof Error ? e.message : String(e)}`);
        }
      }
    }
    return result;
  }

  async on_tool_calls(state: string, toolCalls: any[], context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.on_tool_calls) {
        try {
          const hookResult = await hook.on_tool_calls(state, toolCalls, result);
          if (hookResult && typeof hookResult === 'object') {
            result = hookResult as Record<string, any>;
          }
        } catch (e) {
          logger.warning(`Hook on_tool_calls failed in state '${state}': ${e instanceof Error ? e.message : String(e)}`);
        }
      }
    }
    return result;
  }

  async on_tool_result(state: string, toolResult: any, context: Record<string, any>): Promise<Record<string, any>> {
    let result = context;
    for (const hook of this.hooks) {
      if (hook.on_tool_result) {
        try {
          const hookResult = await hook.on_tool_result(state, toolResult, result);
          if (hookResult && typeof hookResult === 'object') {
            result = hookResult as Record<string, any>;
          }
        } catch (e) {
          logger.warning(`Hook on_tool_result failed in state '${state}': ${e instanceof Error ? e.message : String(e)}`);
        }
      }
    }
    return result;
  }

  get_tool_provider(state: string, context: Record<string, any>): any {
    for (const hook of this.hooks) {
      if (hook.get_tool_provider) {
        const provider = hook.get_tool_provider(state, context);
        if (provider) return provider;
      }
    }
    return null;
  }

  async get_steering_messages(state: string, context: Record<string, any>): Promise<any[]> {
    const messages: any[] = [];
    for (const hook of this.hooks) {
      if (hook.get_steering_messages) {
        const hookMsgs = await hook.get_steering_messages(state, context);
        if (hookMsgs?.length) messages.push(...hookMsgs);
      }
    }
    return messages;
  }
}

/**
 * Logging hooks — logs hook events for debugging.
 *
 * Tool-loop hooks (`on_tool_calls`, `on_tool_result`) pass through the context
 * unchanged, matching the Python SDK's LoggingHooks behavior.
 */
export class LoggingHooks implements MachineHooks {
  async onMachineStart(context: Record<string, any>): Promise<Record<string, any>> {
    logger.info('machine_start');
    return context;
  }

  async onMachineEnd(context: Record<string, any>, output: any): Promise<any> {
    logger.info('machine_end');
    return output;
  }

  async onStateEnter(state: string, context: Record<string, any>): Promise<Record<string, any>> {
    logger.info(`state_enter: ${state}`);
    return context;
  }

  async onStateExit(state: string, context: Record<string, any>, output: any): Promise<any> {
    logger.info(`state_exit: ${state}`);
    return output;
  }

  async onTransition(from: string, to: string, context: Record<string, any>): Promise<string> {
    logger.info(`transition: ${from} → ${to}`);
    return to;
  }

  async onError(state: string, error: Error, _context: Record<string, any>): Promise<string | null> {
    logger.error(`error in ${state}: ${error.message}`);
    return null;
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    logger.info(`action: ${action}`);
    return context;
  }

  on_tool_calls(_state: string, _toolCalls: any[], context: Record<string, any>): Record<string, any> {
    logger.info('on_tool_calls');
    return context;
  }

  on_tool_result(_state: string, _toolResult: any, context: Record<string, any>): Record<string, any> {
    logger.info('on_tool_result');
    return context;
  }
}

/**
 * Name-based registry for resolving hooks from machine config.
 *
 * Machine configs reference hooks by name (e.g., hooks: "my-hooks").
 * The registry maps names to factory classes/functions and resolves
 * them at runtime, keeping configs language-agnostic.
 */
export class HooksRegistry {
  private factories = new Map<string, HooksFactory>();

  register(name: string, factory: HooksFactory): void {
    this.factories.set(name, factory);
  }

  has(name: string): boolean {
    return this.factories.has(name);
  }

  resolve(ref: HooksRef): MachineHooks {
    if (Array.isArray(ref)) {
      const hooks = ref.map((entry) => this.resolveSingle(entry));
      return new CompositeHooks(hooks);
    }
    return this.resolveSingle(ref);
  }

  private resolveSingle(ref: string | { name: string; args?: Record<string, any> }): MachineHooks {
    const name = typeof ref === 'string' ? ref : ref.name;
    const args = typeof ref === 'string' ? undefined : ref.args;
    const factory = this.factories.get(name);
    if (!factory) {
      throw new Error(
        `No hooks registered for name '${name}'. Registered: [${[...this.factories.keys()].join(', ')}]`
      );
    }
    // Try as constructor, fall back to function call
    try {
      return new (factory as any)(args);
    } catch {
      return (factory as Function)(args);
    }
  }
}