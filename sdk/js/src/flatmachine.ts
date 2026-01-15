import * as nunjucks from "nunjucks";
import * as yaml from "yaml";
import { readFileSync } from "fs";
import { randomUUID } from "node:crypto";
import { 
  MachineConfig, 
  MachineOptions, 
  MachineHooks, 
  PersistenceBackend, 
  ResultBackend, 
  State, 
  MachineSnapshot 
} from './types';
import { FlatAgent } from './flatagent';
import { getExecutionType } from './execution';
import { evaluate } from './expression';
import { CheckpointManager, LocalFileBackend, MemoryBackend } from './persistence';

export class FlatMachine {
  public config: MachineConfig;
  public executionId: string = randomUUID();
  private agents = new Map<string, FlatAgent>();
  private context: Record<string, any> = {};
  private input: Record<string, any> = {};
  private hooks?: MachineHooks;
  private checkpointManager?: CheckpointManager;
  private resultBackend?: ResultBackend;
  private configDir: string;
  private checkpointEvents = new Set<string>();

  constructor(options: MachineOptions) {
    this.config = typeof options.config === "string"
      ? yaml.parse(readFileSync(options.config, "utf-8")) as MachineConfig
      : options.config;
    this.hooks = options.hooks;
    this.resultBackend = options.resultBackend;
    this.configDir = options.configDir ?? process.cwd();
    if (options.persistence) {
      this.checkpointManager = new CheckpointManager(options.persistence);
    } else if (this.config.data.persistence?.enabled) {
      const backend = this.createPersistenceBackend(this.config.data.persistence);
      this.checkpointManager = new CheckpointManager(backend);
    }
    if (this.checkpointManager) {
      const configEvents = this.config.data.persistence?.checkpoint_on;
      const events = configEvents?.length ? configEvents : ["execute"];
      this.checkpointEvents = new Set(events);
    }
  }

  async execute(input?: Record<string, any>): Promise<any> {
    if (this.config.data.expression_engine === "cel") {
      throw new Error("expression_engine 'cel' is not supported in the JS SDK yet");
    }

    // Initialize context from config + input
    this.input = input ?? {};
    this.context = this.render(this.config.data.context ?? {}, { input: this.input });
    this.context = await this.hooks?.onMachineStart?.(this.context) ?? this.context;

    let state = this.findInitialState();
    let steps = 0;
    const maxSteps = this.config.data.settings?.max_steps ?? 100;

    if (this.shouldCheckpoint("machine_start")) {
      await this.checkpoint(state, steps, "machine_start");
    }

    while (steps++ < maxSteps) {
      const def = this.config.data.states[state];
      this.context = await this.hooks?.onStateEnter?.(state, this.context) ?? this.context;
      if (this.shouldCheckpoint("execute")) {
        await this.checkpoint(state, steps, "execute");
      }

      // Final state - return output
      if (def.type === "final") {
        const output = this.render(def.output ?? {}, { context: this.context, input: this.input });
        await this.resultBackend?.write(`flatagents://${this.executionId}/result`, output);
        if (this.shouldCheckpoint("machine_end")) {
          await this.checkpoint(state, steps, "machine_end", output);
        }
        return await this.hooks?.onMachineEnd?.(this.context, output) ?? output;
      }

      // Execute agent or machine
      let output: any;
      const executor = getExecutionType(def.execution);

      try {
        if (def.action) {
          const actionResult = await this.hooks?.onAction?.(def.action, this.context);
          if (actionResult !== undefined) {
            this.context = actionResult;
            output = actionResult;
          }
        }
        if (def.agent) {
          output = await executor.execute(() => this.executeAgent(def));
        } else if (def.machine) {
          output = await this.executeMachine(def);
        }
      } catch (err) {
        this.context.last_error = (err as Error).message;
        this.context.last_error_type = (err as Error).name || (err as Error).constructor?.name;
        const recovery = await this.hooks?.onError?.(state, err as Error, this.context);
        if (recovery) { state = recovery; continue; }
        if (def.on_error) {
          if (typeof def.on_error === "string") {
            state = def.on_error;
            continue;
          }
          const errorKey = this.context.last_error_type;
          const nextState = def.on_error[errorKey] ?? def.on_error.default;
          if (nextState) {
            state = nextState;
            continue;
          }
        }
        throw err;
      }

      // Map output to context
      if (def.output_to_context) {
        Object.assign(this.context, this.render(def.output_to_context, { context: this.context, input: this.input, output }));
      }

      // Fire-and-forget launches
      if (def.launch) await this.launchMachines(def);

      output = await this.hooks?.onStateExit?.(state, this.context, output) ?? output;
      const next = this.evaluateTransitions(def, output);
      state = await this.hooks?.onTransition?.(state, next, this.context) ?? next;
    }

    throw new Error("Max steps exceeded");
  }

  async resume(executionId: string): Promise<any> {
    const snapshot = await this.checkpointManager?.restore(executionId);
    if (!snapshot) throw new Error(`No checkpoint for ${executionId}`);
    this.executionId = snapshot.executionId;
    this.context = snapshot.context;
    // Continue from snapshot.currentState...
    // This is a simplified implementation - in the full version, 
    // we'd continue execution from the checkpoint point
    return this.execute();
  }

  private findInitialState(): string {
    for (const [name, state] of Object.entries(this.config.data.states)) {
      if (state.type === "initial") return name;
    }
    return Object.keys(this.config.data.states)[0];
  }

  private async executeAgent(def: State): Promise<any> {
    let agent = this.agents.get(def.agent!);
    if (!agent) {
      // Resolve agent name from agents map, or use directly as path
      const agentRef = this.config.data.agents?.[def.agent!] ?? def.agent!;
      agent = this.createAgent(agentRef);
      this.agents.set(def.agent!, agent);
    }
    const input = this.render(def.input ?? {}, { context: this.context, input: this.input });
    const result = await agent.call(input);
    return result.output;
  }

  private async executeMachine(def: State): Promise<any> {
    const machineDefs = Array.isArray(def.machine) ? def.machine : [def.machine!];
    const mode = def.mode ?? "settled";
    const timeoutMs = def.timeout && def.timeout > 0 ? def.timeout * 1000 : undefined;

    // foreach - dynamic parallelism
    if (def.foreach) {
      const items = this.render({ items: def.foreach }, { context: this.context, input: this.input }).items as any[];
      const varName = def.as ?? "item";
      const tasks = items.map(async (item, index) => {
        const input = this.render(def.input ?? {}, { context: this.context, input: this.input, [varName]: item });
        const machine = this.createMachine(machineDefs[0]);
        const result = await machine.execute(input);
        const keyValue = def.key
          ? this.render(def.key, { context: this.context, input: this.input, [varName]: item, output: result })
          : undefined;
        return { index, key: keyValue, result };
      });
      const output = await this.awaitWithMode(tasks, mode, timeoutMs);
      if (mode === "any") {
        const picked = output as { key?: any; result: any };
        if (def.key) return { [String(picked.key)]: picked.result };
        return picked.result;
      }
      const settled = output as { index: number; key?: any; result: any }[];
      if (def.key) {
        const keyed: Record<string, any> = {};
        for (const entry of settled) {
          keyed[String(entry.key)] = entry.result;
        }
        return keyed;
      }
      const ordered: any[] = new Array(items.length);
      for (const entry of settled) {
        ordered[entry.index] = entry.result;
      }
      return ordered;
    }

    // Parallel machines
    if (machineDefs.length > 1 || (machineDefs.length === 1 && typeof machineDefs[0] === "object" && "name" in machineDefs[0])) {
      const tasks = machineDefs.map(async (entry) => {
        const name = typeof entry === "string" ? entry : entry.name;
        const baseInput = this.render(def.input ?? {}, { context: this.context, input: this.input });
        const entryInput = typeof entry === "string" ? {} : this.render(entry.input ?? {}, { context: this.context, input: this.input });
        const mergedInput = { ...baseInput, ...entryInput };
        const machine = this.createMachine(entry);
        const result = await machine.execute(mergedInput);
        return { name, result };
      });
      const output = await this.awaitWithMode(tasks, mode, timeoutMs);
      if (mode === "any") {
        const picked = output as { name: string; result: any };
        return { [picked.name]: picked.result };
      }
      const settled = output as { name: string; result: any }[];
      return settled.reduce((acc, entry) => {
        acc[entry.name] = entry.result;
        return acc;
      }, {} as Record<string, any>);
    }

    // Single machine
    const input = this.render(def.input ?? {}, { context: this.context, input: this.input });
    const machine = this.createMachine(machineDefs[0]);
    return machine.execute(input);
  }

  private async launchMachines(def: State): Promise<void> {
    const machines = Array.isArray(def.launch) ? def.launch : [def.launch!];
    for (const name of machines) {
      const input = this.render(def.launch_input ?? {}, { context: this.context, input: this.input });
      const machine = this.createMachine(name);
      // Fire and forget
      machine.execute(input).catch(() => {});
    }
  }

  private evaluateTransitions(def: State, output: any): string {
    if (!def.transitions?.length) throw new Error("No transitions defined");
    for (const t of def.transitions) {
      if (!t.condition || evaluate(t.condition, { context: this.context, input: this.input, output })) {
        return t.to;
      }
    }
    throw new Error("No matching transition");
  }

  private async checkpoint(state: string, step: number, event?: string, output?: any): Promise<void> {
    if (!this.checkpointManager) return;
    await this.checkpointManager.checkpoint({
      executionId: this.executionId,
      machineName: this.config.data.name ?? "unnamed",
      currentState: state,
      context: this.context,
      step,
      createdAt: new Date().toISOString(),
      event,
      output,
    });
  }

  private render(template: any, vars: Record<string, any>): any {
    if (typeof template === "string") {
      const directValue = this.renderDirectValue(template, vars);
      if (directValue !== undefined) return directValue;
      const rendered = nunjucks.renderString(template, vars);
      try { return JSON.parse(rendered); } catch { return rendered; }
    }
    if (Array.isArray(template)) return template.map(t => this.render(t, vars));
    if (typeof template === "object" && template !== null) {
      return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, this.render(v, vars)]));
    }
    return template;
  }

  private renderDirectValue(template: string, vars: Record<string, any>): any | undefined {
    const match = template.match(/^\s*{{\s*([^}]+)\s*}}\s*$/);
    if (!match) return undefined;
    const expr = match[1].trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$/.test(expr)) return undefined;
    return this.resolvePath(vars, expr);
  }

  private resolvePath(vars: Record<string, any>, expr: string): any {
    return expr.split(".").reduce((obj, part) => (obj ? obj[part] : undefined), vars);
  }

  private shouldCheckpoint(event: string): boolean {
    return this.checkpointManager ? this.checkpointEvents.has(event) : false;
  }

  private createPersistenceBackend(config: NonNullable<MachineConfig["data"]["persistence"]>) {
    if (config.backend === "memory") return new MemoryBackend();
    if (config.backend === "local") return new LocalFileBackend();
    throw new Error(`Unsupported persistence backend: ${config.backend}`);
  }

  private createAgent(agentRef: any): FlatAgent {
    if (agentRef && typeof agentRef === "object") {
      if (agentRef.spec === "flatagent" && agentRef.data) {
        return new FlatAgent(agentRef);
      }
      if (agentRef.path) {
        return new FlatAgent(`${this.configDir}/${agentRef.path}`);
      }
    }
    return new FlatAgent(`${this.configDir}/${agentRef}`);
  }

  private createMachine(machineRef: any): FlatMachine {
    const resolved = this.resolveMachineRef(machineRef);
    return new FlatMachine({
      config: resolved.config,
      configDir: resolved.configDir,
      resultBackend: this.resultBackend,
    });
  }

  private resolveMachineRef(machineRef: any): { config: MachineConfig | string; configDir: string } {
    if (typeof machineRef === "object" && machineRef) {
      if ("spec" in machineRef && "data" in machineRef) {
        return { config: machineRef as MachineConfig, configDir: this.configDir };
      }
      if ("path" in machineRef && machineRef.path) {
        return { config: `${this.configDir}/${machineRef.path}`, configDir: this.configDir };
      }
      if ("inline" in machineRef && machineRef.inline) {
        return { config: machineRef.inline as MachineConfig, configDir: this.configDir };
      }
      if ("name" in machineRef) {
        return this.resolveMachineRef(machineRef.name);
      }
    }
    const name = String(machineRef);
    const entry = this.config.data.machines?.[name];
    if (entry && typeof entry === "object") {
      if ("path" in entry && entry.path) {
        return { config: `${this.configDir}/${entry.path}`, configDir: this.configDir };
      }
      if ("inline" in entry && entry.inline) {
        return { config: entry.inline as MachineConfig, configDir: this.configDir };
      }
      if ("spec" in entry && "data" in entry) {
        return { config: entry as MachineConfig, configDir: this.configDir };
      }
    }
    if (typeof entry === "string") {
      return { config: `${this.configDir}/${entry}`, configDir: this.configDir };
    }
    return { config: `${this.configDir}/${name}`, configDir: this.configDir };
  }

  private async awaitWithMode<T>(tasks: Promise<T>[], mode: string, timeoutMs?: number): Promise<T | T[]> {
    if (tasks.length === 0) {
      return mode === "any" ? (undefined as T) : ([] as T[]);
    }
    const runner: Promise<T | T[]> = mode === "any" ? this.firstCompleted(tasks) : Promise.all(tasks);
    if (!timeoutMs) return runner;
    return this.withTimeout(runner, timeoutMs);
  }

  private async firstCompleted<T>(tasks: Promise<T>[]): Promise<T> {
    return new Promise((resolve, reject) => {
      let pending = tasks.length;
      let settled = false;
      const errors: any[] = [];
      for (const task of tasks) {
        task.then((value) => {
          if (settled) return;
          settled = true;
          resolve(value);
        }).catch((err) => {
          errors.push(err);
          pending -= 1;
          if (pending === 0 && !settled) {
            reject(errors[0]);
          }
        });
      }
    });
  }

  private withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Operation timed out")), timeoutMs);
      promise.then((value) => {
        clearTimeout(timer);
        resolve(value);
      }).catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
    });
  }

  private pickFirstKeyedResult(results: Record<string, any>): Record<string, any> {
    const firstKey = Object.keys(results)[0];
    if (!firstKey) return {};
    return { [firstKey]: results[firstKey] };
  }
}
