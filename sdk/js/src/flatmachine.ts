import * as yaml from "yaml";
import { readFileSync, existsSync } from "fs";
import { dirname, resolve } from "path";
import { randomUUID } from "node:crypto";
import {
  MachineConfig,
  MachineOptions,
  MachineHooks,
  PersistenceBackend,
  ResultBackend,
  ExecutionLock,
  State,
  MachineSnapshot,
  LaunchIntent,
  BackendConfig
} from './types';
import { FlatAgent } from './flatagent';
import { getExecutionType } from './execution';
import { evaluate } from './expression';
import { CheckpointManager, LocalFileBackend, MemoryBackend } from './persistence';
import { inMemoryResultBackend } from './results';
import { LocalFileLock, NoOpLock } from './locking';
import { renderTemplate } from './templating';


export class FlatMachine {
  public config: MachineConfig;
  public executionId: string = randomUUID();
  private agents = new Map<string, FlatAgent>();
  private context: Record<string, any> = {};
  private input: Record<string, any> = {};
  private hooks?: MachineHooks;
  private checkpointManager?: CheckpointManager;
  private resultBackend?: ResultBackend;
  private executionLock: ExecutionLock;
  private configDir: string;
  private profilesFile?: string;
  private checkpointEvents = new Set<string>();
  private parentExecutionId?: string;
  private pendingLaunches: LaunchIntent[] = [];
  private currentState?: string;
  private currentStep = 0;

  constructor(options: MachineOptions) {
    this.config = typeof options.config === "string"
      ? yaml.parse(readFileSync(options.config, "utf-8")) as MachineConfig
      : options.config;
    this.hooks = options.hooks;
    this.configDir = options.configDir ?? process.cwd();
    this.profilesFile = this.resolveProfilesFile(options.profilesFile);
    this.executionId = options.executionId ?? this.executionId;
    this.parentExecutionId = options.parentExecutionId;

    const backendConfig = this.config.data.settings?.backends;
    this.resultBackend = options.resultBackend ?? this.createResultBackend(backendConfig);
    this.executionLock = options.executionLock ?? this.createExecutionLock(backendConfig);

    if (options.persistence) {
      this.checkpointManager = new CheckpointManager(options.persistence);
    } else if (this.config.data.persistence?.enabled) {
      const backend = this.createPersistenceBackend(this.config.data.persistence);
      this.checkpointManager = new CheckpointManager(backend);
    } else if (backendConfig?.persistence) {
      const backend = this.createSettingsPersistenceBackend(backendConfig.persistence);
      this.checkpointManager = new CheckpointManager(backend);
    }
    if (this.checkpointManager) {
      const configEvents = this.config.data.persistence?.checkpoint_on;
      const events = configEvents?.length ? configEvents : ["execute"];
      this.checkpointEvents = new Set(events);
    }
  }

  async execute(input?: Record<string, any>, resumeSnapshot?: MachineSnapshot): Promise<any> {
    if (this.config.data.expression_engine === "cel") {
      // TODO: CEL expression engine is not implemented in the JS SDK yet.
      throw new Error("expression_engine 'cel' is not supported in the JS SDK yet");
    }

    // Acquire execution lock
    const lockKey = resumeSnapshot?.execution_id ?? this.executionId;
    const lockAcquired = await this.executionLock.acquire(lockKey);
    if (!lockAcquired) {
      throw new Error(`Execution ${lockKey} is already running`);
    }

    try {
      return await this.executeInternal(input, resumeSnapshot);
    } finally {
      await this.executionLock.release(lockKey);
    }
  }

  private async executeInternal(input?: Record<string, any>, resumeSnapshot?: MachineSnapshot): Promise<any> {
    let state: string;
    let steps: number;

    if (resumeSnapshot) {
      // Resume from checkpoint - restore state instead of reinitializing
      this.executionId = resumeSnapshot.execution_id;
      this.parentExecutionId = resumeSnapshot.parent_execution_id;
      this.context = resumeSnapshot.context;
      state = resumeSnapshot.current_state;
      steps = resumeSnapshot.step;
      this.pendingLaunches = resumeSnapshot.pending_launches ?? [];
      if (this.pendingLaunches.length) {
        await this.resumePendingLaunches();
      }
      // Don't call onMachineStart when resuming
    } else {
      // Fresh execution - initialize context from config + input
      this.input = input ?? {};
      this.context = this.render(this.config.data.context ?? {}, { input: this.input });
      this.context = await this.hooks?.onMachineStart?.(this.context) ?? this.context;
      state = this.findInitialState();
      steps = 0;
      this.pendingLaunches = [];

      if (this.shouldCheckpoint("machine_start")) {
        await this.checkpoint(state, steps, "machine_start");
      }
    }

    const maxSteps = this.config.data.settings?.max_steps ?? 100;

    while (steps++ < maxSteps) {
      const def = this.config.data.states[state];
      this.currentState = state;
      this.currentStep = steps;
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
    // Pass snapshot to execute so it resumes from that state instead of reinitializing
    return this.execute(undefined, snapshot);
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
        const result = await this.invokeMachineSingle(machineDefs[0], input, timeoutMs);
        const keyValue = def.key
          ? this.render(def.key, { context: this.context, input: this.input, [varName]: item, output: result })
          : undefined;
        return { index, key: keyValue, result };
      });
      const output = await this.awaitWithMode(tasks, mode);
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
        const name = this.getMachineName(entry);
        const baseInput = this.render(def.input ?? {}, { context: this.context, input: this.input });
        const entryInput = typeof entry === "string" ? {} : this.render(entry.input ?? {}, { context: this.context, input: this.input });
        const mergedInput = { ...baseInput, ...entryInput };
        const result = await this.invokeMachineSingle(entry, mergedInput, timeoutMs);
        return { name, result };
      });
      const output = await this.awaitWithMode(tasks, mode);
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
    return this.invokeMachineSingle(machineDefs[0], input, timeoutMs);
  }

  private async launchMachines(def: State): Promise<void> {
    const machines = Array.isArray(def.launch) ? def.launch : [def.launch!];
    const input = this.render(def.launch_input ?? {}, { context: this.context, input: this.input });
    await Promise.all(machines.map((machineRef) => this.launchFireAndForget(machineRef, input)));
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
      execution_id: this.executionId,
      machine_name: this.config.data.name ?? "unnamed",
      spec_version: this.config.spec_version ?? "0.4.0",
      current_state: state,
      context: this.context,
      step,
      created_at: new Date().toISOString(),
      event,
      output,
      parent_execution_id: this.parentExecutionId,
      pending_launches: this.pendingLaunches.length ? this.pendingLaunches : undefined,
    });
  }

  private render(template: any, vars: Record<string, any>): any {
    if (typeof template === "string") {
      const directValue = this.renderDirectValue(template, vars);
      if (directValue !== undefined) return directValue;
      const rendered = renderTemplate(template, vars, "flatmachine");
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

  private createResultBackend(config?: BackendConfig): ResultBackend {
    if (!config?.results || config.results === "memory") return inMemoryResultBackend;
    throw new Error(`Unsupported result backend: ${config.results}`);
  }

  private createExecutionLock(config?: BackendConfig): ExecutionLock {
    if (!config?.locking || config.locking === "none") return new NoOpLock();
    if (config.locking === "local") return new LocalFileLock();
    throw new Error(`Unsupported execution lock backend: ${config.locking}`);
  }

  private createSettingsPersistenceBackend(setting: BackendConfig["persistence"]): PersistenceBackend {
    if (setting === "memory") return new MemoryBackend();
    if (setting === "local") return new LocalFileBackend();
    throw new Error(`Unsupported persistence backend: ${setting}`);
  }

  private createPersistenceBackend(config: NonNullable<MachineConfig["data"]["persistence"]>) {
    if (config.backend === "memory") return new MemoryBackend();
    if (config.backend === "local") return new LocalFileBackend();
    throw new Error(`Unsupported persistence backend: ${config.backend}`);
  }

  private createAgent(agentRef: any): FlatAgent {
    if (agentRef && typeof agentRef === "object") {
      if (agentRef.spec === "flatagent" && agentRef.data) {
        return new FlatAgent({ config: agentRef, profilesFile: this.profilesFile });
      }
      if (agentRef.path) {
        return new FlatAgent({
          config: `${this.configDir}/${agentRef.path}`,
          profilesFile: this.profilesFile,
        });
      }
    }
    return new FlatAgent({
      config: `${this.configDir}/${agentRef}`,
      profilesFile: this.profilesFile,
    });
  }

  private createMachine(
    machineRef: any,
    overrides?: { executionId?: string; parentExecutionId?: string }
  ): FlatMachine {
    const resolved = this.resolveMachineConfig(machineRef);
    return new FlatMachine({
      config: resolved.config,
      configDir: resolved.configDir,
      resultBackend: this.resultBackend,
      hooks: this.hooks,
      executionId: overrides?.executionId,
      parentExecutionId: overrides?.parentExecutionId,
      profilesFile: this.profilesFile,
    });
  }

  private resolveMachineConfig(machineRef: any): { config: MachineConfig | string; configDir: string } {
    if (typeof machineRef === "object" && machineRef) {
      if ("spec" in machineRef && "data" in machineRef) {
        return { config: machineRef as MachineConfig, configDir: this.configDir };
      }
      if ("path" in machineRef && machineRef.path) {
        return this.resolveMachinePath(String(machineRef.path));
      }
      if ("inline" in machineRef && machineRef.inline) {
        return { config: machineRef.inline as MachineConfig, configDir: this.configDir };
      }
      if ("name" in machineRef) {
        return this.resolveMachineConfig(machineRef.name);
      }
    }
    const name = String(machineRef);
    const entry = this.config.data.machines?.[name];
    if (entry && typeof entry === "object") {
      if ("path" in entry && entry.path) {
        return this.resolveMachinePath(String(entry.path));
      }
      if ("inline" in entry && entry.inline) {
        return { config: entry.inline as MachineConfig, configDir: this.configDir };
      }
      if ("spec" in entry && "data" in entry) {
        return { config: entry as MachineConfig, configDir: this.configDir };
      }
    }
    if (typeof entry === "string") {
      return this.resolveMachinePath(entry);
    }
    return this.resolveMachinePath(name);
  }

  private resolveMachinePath(pathRef: string): { config: string; configDir: string } {
    // Align with Python SDK: child machine config_dir is the directory containing its config file.
    const resolved = resolve(this.configDir, pathRef);
    return { config: resolved, configDir: dirname(resolved) };
  }

  private resolveProfilesFile(explicitPath?: string): string | undefined {
    const configProfiles = (this.config as any)?.data?.profiles;
    if (typeof configProfiles === "string" && configProfiles.trim().length > 0) {
      return resolve(this.configDir, configProfiles);
    }

    const discovered = resolve(this.configDir, "profiles.yml");
    if (existsSync(discovered)) return discovered;

    return explicitPath;
  }

  private getMachineName(machineRef: any): string {
    if (typeof machineRef === "string") return machineRef;
    if (machineRef?.name) return String(machineRef.name);
    if (machineRef?.path) return String(machineRef.path);
    if (machineRef?.inline?.data?.name) return String(machineRef.inline.data.name);
    if (machineRef?.spec === "flatmachine" && machineRef.data?.name) return String(machineRef.data.name);
    return "machine";
  }

  private makeResultUri(executionId: string): string {
    return `flatagents://${executionId}/result`;
  }

  private async addPendingLaunch(executionId: string, machine: string, input: Record<string, any>): Promise<void> {
    this.pendingLaunches.push({ execution_id: executionId, machine, input, launched: false });
    if (this.currentState && this.shouldCheckpoint("execute")) {
      await this.checkpoint(this.currentState, this.currentStep, "execute");
    }
  }

  private markLaunched(executionId: string): void {
    for (const intent of this.pendingLaunches) {
      if (intent.execution_id === executionId) {
        intent.launched = true;
        return;
      }
    }
  }

  private clearPendingLaunch(executionId: string): void {
    this.pendingLaunches = this.pendingLaunches.filter(intent => intent.execution_id !== executionId);
  }

  private async resumePendingLaunches(): Promise<void> {
    if (!this.resultBackend) return;
    for (const intent of this.pendingLaunches) {
      if (intent.launched) continue;
      const uri = this.makeResultUri(intent.execution_id);
      const exists = await this.resultBackend.exists(uri);
      if (exists) continue;
      const launchPromise = this.launchAndWrite(intent.machine, intent.execution_id, intent.input);
      this.markLaunched(intent.execution_id);
      launchPromise
        .then(() => this.clearPendingLaunch(intent.execution_id))
        .catch(() => {});
    }
  }

  private async launchAndWrite(machineRef: any, executionId: string, input: Record<string, any>): Promise<any> {
    const machine = this.createMachine(machineRef, {
      executionId,
      parentExecutionId: this.executionId,
    });
    try {
      const result = await machine.execute(input);
      if (this.resultBackend) {
        await this.resultBackend.write(this.makeResultUri(executionId), result);
      }
      return result;
    } catch (err) {
      if (this.resultBackend) {
        const error = err as Error;
        await this.resultBackend.write(this.makeResultUri(executionId), {
          _error: error.message,
          _error_type: error.name || error.constructor?.name,
        });
      }
      throw err;
    }
  }

  private normalizeMachineResult(result: any): any {
    if (result && typeof result === "object" && "_error" in result) {
      const error = new Error(String(result._error ?? "Machine execution failed"));
      error.name = String((result as Record<string, any>)._error_type ?? "Error");
      throw error;
    }
    return result;
  }

  private async invokeMachineSingle(machineRef: any, input: Record<string, any>, timeoutMs?: number): Promise<any> {
    const childId = randomUUID();
    const machineName = this.getMachineName(machineRef);
    await this.addPendingLaunch(childId, machineName, input);
    const launchPromise = this.launchAndWrite(machineRef, childId, input);

    let shouldClear = false;
    try {
      if (!this.resultBackend) {
        const result = await launchPromise;
        shouldClear = true;
        return result;
      }
      const result = await this.resultBackend.read(this.makeResultUri(childId), {
        block: true,
        timeout: timeoutMs,
      });
      shouldClear = true;
      return this.normalizeMachineResult(result);
    } catch (err) {
      if ((err as Error).name !== "TimeoutError") {
        shouldClear = true;
      }
      throw err;
    } finally {
      this.markLaunched(childId);
      if (shouldClear) {
        this.clearPendingLaunch(childId);
      }
      launchPromise.catch(() => {});
    }
  }

  private async launchFireAndForget(machineRef: any, input: Record<string, any>): Promise<void> {
    const childId = randomUUID();
    const machineName = this.getMachineName(machineRef);
    await this.addPendingLaunch(childId, machineName, input);
    const launchPromise = this.launchAndWrite(machineRef, childId, input);
    this.markLaunched(childId);
    launchPromise
      .then(() => this.clearPendingLaunch(childId))
      .catch(() => {});
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
