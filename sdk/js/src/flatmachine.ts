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
import { CheckpointManager } from './persistence';

export class FlatMachine {
  public config: MachineConfig;
  public executionId: string = randomUUID();
  private agents = new Map<string, FlatAgent>();
  private context: Record<string, any> = {};
  private hooks?: MachineHooks;
  private checkpointManager?: CheckpointManager;
  private resultBackend?: ResultBackend;
  private configDir: string;

  constructor(options: MachineOptions) {
    this.config = typeof options.config === "string"
      ? yaml.parse(readFileSync(options.config, "utf-8")) as MachineConfig
      : options.config;
    this.hooks = options.hooks;
    this.resultBackend = options.resultBackend;
    this.configDir = options.configDir ?? process.cwd();
    if (options.persistence) {
      this.checkpointManager = new CheckpointManager(options.persistence);
    }
  }

  async execute(input?: Record<string, any>): Promise<any> {
    // Initialize context from config + input
    this.context = this.render(this.config.data.context ?? {}, { input: input ?? {} });
    this.context = await this.hooks?.onMachineStart?.(this.context) ?? this.context;

    let state = this.findInitialState();
    let steps = 0;
    const maxSteps = 100;

    while (steps++ < maxSteps) {
      const def = this.config.data.states[state];
      this.context = await this.hooks?.onStateEnter?.(state, this.context) ?? this.context;
      await this.checkpoint(state, steps);

      // Final state - return output
      if (def.type === "final") {
        const output = this.render(def.output ?? {}, { context: this.context });
        await this.resultBackend?.write(`flatagents://${this.executionId}/result`, output);
        return await this.hooks?.onMachineEnd?.(this.context, output) ?? output;
      }

      // Execute agent or machine
      let output: any;
      const executor = getExecutionType(def.execution);

      try {
        if (def.agent) {
          output = await executor.execute(() => this.executeAgent(def));
        } else if (def.machine) {
          output = await this.executeMachine(def);
        }
      } catch (err) {
        const recovery = await this.hooks?.onError?.(state, err as Error, this.context);
        if (recovery) { state = recovery; continue; }
        if (def.on_error) { this.context.lastError = (err as Error).message; state = def.on_error; continue; }
        throw err;
      }

      // Map output to context
      if (def.output_to_context && output) {
        Object.assign(this.context, this.render(def.output_to_context, { context: this.context, output }));
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
      const agentPath = this.config.data.agents?.[def.agent!] ?? def.agent!;
      agent = new FlatAgent(`${this.configDir}/${agentPath}`);
      this.agents.set(def.agent!, agent);
    }
    const input = this.render(def.input ?? {}, { context: this.context });
    const result = await agent.call(input);
    return result.output;
  }

  private async executeMachine(def: State): Promise<any> {
    const machines = Array.isArray(def.machine) ? def.machine : [def.machine!];

    // foreach - dynamic parallelism
    if (def.foreach) {
      const items = this.render({ items: def.foreach }, { context: this.context }).items as any[];
      const varName = def.as ?? "item";
      const results = await Promise.all(items.map(async (item, i) => {
        const input = this.render(def.input ?? {}, { context: this.context, [varName]: item });
        const machine = new FlatMachine({ config: `${this.configDir}/${machines[0]}`, configDir: this.configDir });
        return machine.execute(input);
      }));
      return results;
    }

    // Parallel machines
    if (machines.length > 1) {
      const results: Record<string, any> = {};
      await Promise.all(machines.map(async (name) => {
        const input = this.render(def.input ?? {}, { context: this.context });
        const machine = new FlatMachine({ config: `${this.configDir}/${name}`, configDir: this.configDir });
        results[name] = await machine.execute(input);
      }));
      return results;
    }

    // Single machine
    const input = this.render(def.input ?? {}, { context: this.context });
    const machine = new FlatMachine({ config: `${this.configDir}/${machines[0]}`, configDir: this.configDir });
    return machine.execute(input);
  }

  private async launchMachines(def: State): Promise<void> {
    const machines = Array.isArray(def.launch) ? def.launch : [def.launch!];
    for (const name of machines) {
      const input = this.render(def.launch_input ?? {}, { context: this.context });
      const machine = new FlatMachine({
        config: `${this.configDir}/${name}`,
        configDir: this.configDir,
        resultBackend: this.resultBackend,
      });
      // Fire and forget
      machine.execute(input).catch(() => {});
    }
  }

  private evaluateTransitions(def: State, output: any): string {
    if (!def.transitions?.length) throw new Error("No transitions defined");
    for (const t of def.transitions) {
      if (!t.condition || evaluate(t.condition, { context: this.context, input: {}, output })) {
        return t.to;
      }
    }
    throw new Error("No matching transition");
  }

  private async checkpoint(state: string, step: number): Promise<void> {
    if (!this.checkpointManager) return;
    await this.checkpointManager.checkpoint({
      executionId: this.executionId,
      machineName: this.config.data.name ?? "unnamed",
      currentState: state,
      context: this.context,
      step,
      createdAt: new Date().toISOString(),
    });
  }

  private render(template: any, vars: Record<string, any>): any {
    if (typeof template === "string") {
      const rendered = nunjucks.renderString(template, vars);
      try { return JSON.parse(rendered); } catch { return rendered; }
    }
    if (Array.isArray(template)) return template.map(t => this.render(t, vars));
    if (typeof template === "object" && template !== null) {
      return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, this.render(v, vars)]));
    }
    return template;
  }
}