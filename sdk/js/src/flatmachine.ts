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
  BackendConfig,
  HooksRef
} from './types';
import { FlatAgent } from './flatagent';
import { AgentResponse, FinishReason } from './agent_response';
import { getExecutionType } from './execution';
import { evaluate } from './expression';
import { CheckpointManager, LocalFileBackend, MemoryBackend } from './persistence';
import { SQLiteCheckpointBackend, SQLiteConfigStore, configHash } from './persistence_sqlite';
import { inMemoryResultBackend } from './results';
import { LocalFileLock, NoOpLock } from './locking';
import { SQLiteLeaseLock } from './locking_sqlite';
import { renderTemplate } from './templating';
import { HooksRegistry } from './hooks';
import {
  AgentExecutor,
  AgentResult,
  AgentRef,
  AgentAdapterRegistry,
  AgentAdapterContext,
  normalizeAgentRef,
  coerceAgentResult,
  agentResultOutputPayload,
} from './agents';
import { FlatAgentAdapter, FlatAgentExecutor } from './adapters/flatagent_adapter';
import { ToolProvider, ToolResult } from './tools';
import { SignalBackend, TriggerBackend, NoOpTrigger } from './signals';
import { evaluateCel } from './expression_cel';

// ─────────────────────────────────────────────────────────────────────────────
// WaitingForSignal exception
// ─────────────────────────────────────────────────────────────────────────────

export class WaitingForSignal extends Error {
  channel: string;
  constructor(channel: string) {
    super(`Waiting for signal on channel: ${channel}`);
    this.name = 'WaitingForSignal';
    this.channel = channel;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Extended MachineOptions to support new features
// ─────────────────────────────────────────────────────────────────────────────

export interface ExtendedMachineOptions extends MachineOptions {
  signalBackend?: SignalBackend;
  triggerBackend?: TriggerBackend;
  agentRegistry?: AgentAdapterRegistry;
  toolProvider?: ToolProvider;
  configStore?: any;
}

// ─────────────────────────────────────────────────────────────────────────────
// FlatMachine
// ─────────────────────────────────────────────────────────────────────────────

export class FlatMachine {
  public config: MachineConfig;
  public executionId: string = randomUUID();
  private agents = new Map<string, FlatAgent>();
  private executors = new Map<string, AgentExecutor>();
  private context: Record<string, any> = {};
  private input: Record<string, any> = {};
  private hooks?: MachineHooks;
  private _hooksRegistry: HooksRegistry;
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
  private totalApiCalls = 0;
  private totalCost = 0;

  // Config store for SQLite auto-wiring
  public _config_store?: any;
  // Resolved config as raw string
  public _config_raw?: string;
  // Config hash for resume support
  public _config_hash?: string;

  // New Phase 3+ backends
  private signalBackend?: SignalBackend;
  private triggerBackend: TriggerBackend;
  private agentRegistry: AgentAdapterRegistry;
  private toolProvider?: ToolProvider;
  private expressionEngine: 'simple' | 'cel' = 'simple';

  constructor(options: MachineOptions | ExtendedMachineOptions) {
    const configIsPath = typeof options.config === "string";
    this.config = configIsPath
      ? yaml.parse(readFileSync(options.config, "utf-8")) as MachineConfig
      : options.config;
    this._hooksRegistry = options.hooksRegistry ?? new HooksRegistry();
    this.hooks = this.resolveHooks(options.hooks);
    this.configDir = options.configDir ?? (configIsPath ? dirname(resolve(options.config as string)) : process.cwd());
    this.profilesFile = this.resolveProfilesFile(options.profilesFile);
    this.executionId = options.executionId ?? this.executionId;
    this.parentExecutionId = options.parentExecutionId;

    const backendConfig = this.config.data.settings?.backends;
    this.resultBackend = options.resultBackend ?? this.createResultBackend(backendConfig);
    this.executionLock = options.executionLock ?? this.createExecutionLock(backendConfig);

    // New backends
    const extOpts = options as ExtendedMachineOptions;
    this.signalBackend = extOpts.signalBackend;
    this.triggerBackend = extOpts.triggerBackend ?? new NoOpTrigger();
    this.toolProvider = extOpts.toolProvider;
    if (extOpts.configStore && !this._config_store) {
      this._config_store = extOpts.configStore;
    }

    // Agent adapter registry with default flatagent adapter
    this.agentRegistry = extOpts.agentRegistry ?? new AgentAdapterRegistry();
    if (!extOpts.agentRegistry) {
      this.agentRegistry.register(new FlatAgentAdapter());
    }

    // Expression engine
    this.expressionEngine = (this.config.data.expression_engine as any) ?? 'simple';

    // Resolve agent references at construction time
    this.resolveAgentRefs();

    // Store resolved config as raw string
    this._config_raw = yaml.stringify(this.config);

    // Compute config hash and store in config store (only if config store available)
    if (this._config_store && this._config_raw) {
      this._config_hash = configHash(this._config_raw);
      this._config_store.put(this._config_raw).catch(() => {});
    }

    if (options.persistence) {
      this.checkpointManager = new CheckpointManager(options.persistence);
    } else if (this.config.data.persistence?.enabled) {
      const backend = this.createPersistenceBackend(this.config.data.persistence);
      this.checkpointManager = new CheckpointManager(backend);
      // Auto-wire SQLiteLeaseLock + SQLiteConfigStore when using sqlite persistence
      if (this.config.data.persistence?.backend === 'sqlite' && backend instanceof SQLiteCheckpointBackend) {
        if (this.executionLock instanceof NoOpLock && !options.executionLock) {
          this.executionLock = new SQLiteLeaseLock((backend as SQLiteCheckpointBackend).db);
        }
        if (!this._config_store) {
          this._config_store = (backend as SQLiteCheckpointBackend).configStore;
        }
      }
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

  get hooksRegistry(): HooksRegistry {
    return this._hooksRegistry;
  }

  private resolveHooks(explicit?: MachineHooks): MachineHooks | undefined {
    if (explicit) return explicit;
    const hooksConfig = (this.config.data as any).hooks as HooksRef | undefined;
    if (!hooksConfig) return undefined;
    return this._hooksRegistry.resolve(hooksConfig);
  }

  async execute(input?: Record<string, any>, resumeSnapshot?: MachineSnapshot): Promise<any> {
    // CEL expression engine is supported via cel-js (optional dependency)

    // Acquire execution lock
    const lockKey = resumeSnapshot?.execution_id ?? this.executionId;
    const lockAcquired = await this.executionLock.acquire(lockKey);
    if (!lockAcquired) {
      throw new Error(`Execution ${lockKey} is already running`);
    }

    try {
      return await this.executeInternal(input, resumeSnapshot);
    } catch (err) {
      if (err instanceof WaitingForSignal) {
        // Machine is parked — checkpoint was already saved, just return
        return { _waiting: true, _channel: err.channel, _waiting_for: err.channel };
      }
      throw err;
    } finally {
      await this.executionLock.release(lockKey);
    }
  }

  private async executeInternal(input?: Record<string, any>, resumeSnapshot?: MachineSnapshot): Promise<any> {
    let state: string;
    let steps: number;

    if (resumeSnapshot) {
      this.executionId = resumeSnapshot.execution_id;
      this.parentExecutionId = resumeSnapshot.parent_execution_id;
      this.context = resumeSnapshot.context;
      state = resumeSnapshot.current_state;
      steps = resumeSnapshot.step;
      this.pendingLaunches = resumeSnapshot.pending_launches ?? [];
      if (this.pendingLaunches.length) {
        await this.resumePendingLaunches();
      }
    } else {
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
      const def = this.config.data.states[state]!;
      this.currentState = state;
      this.currentStep = steps;

      // Inject machine metadata into context
      this.injectMachineMetadata(state, steps);

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

      // Execute state
      let output: any;

      try {
        // 0. Handle wait_for (external signal)
        if (def.wait_for) {
          output = await this.handleWaitFor(def, state, steps);
          // Apply output_to_context for wait_for states
          if (def.output_to_context && output != null) {
            const safeOutput = typeof output === 'object' ? output : { value: output };
            Object.assign(this.context, this.render(def.output_to_context, { context: this.context, input: this.input, output: safeOutput }));
          }
        }
        // 1. Handle action
        else if (def.action) {
          const actionResult = await this.hooks?.onAction?.(def.action, this.context);
          if (actionResult !== undefined) {
            this.context = actionResult;
            output = actionResult;
          }
        }
        // 2. Handle agent (with optional tool loop)
        else if (def.agent) {
          if (def.tool_loop) {
            const [ctx, toolOutput] = await this.executeToolLoop(state, def);
            this.context = ctx;
            output = toolOutput;
          } else {
            const executor = getExecutionType(def.execution);
            output = await executor.execute(() => this.executeAgent(def));
          }
        }
        // 3. Handle machine
        else if (def.machine) {
          output = await this.executeMachine(def);
        }
      } catch (err) {
        if (err instanceof WaitingForSignal) throw err;
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

      // Map output to context (for non-wait_for states)
      if (def.output_to_context && !def.wait_for) {
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
    return this.execute(undefined, snapshot);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Context machine metadata injection (#14)
  // ─────────────────────────────────────────────────────────────────────────

  private injectMachineMetadata(state: string, step: number): void {
    this.context.machine = Object.freeze({
      execution_id: this.executionId,
      machine_name: this.config.data.name ?? 'unnamed',
      spec_version: this.config.spec_version ?? '0.1.0',
      step,
      current_state: state,
      parent_execution_id: this.parentExecutionId ?? null,
      total_api_calls: this.totalApiCalls,
      total_cost: this.totalCost,
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Wait-for states (#11)
  // ─────────────────────────────────────────────────────────────────────────

  private async handleWaitFor(def: State, state: string, step: number): Promise<any> {
    const channel = this.render(def.wait_for!, { context: this.context, input: this.input });

    // Try to consume a signal
    let signalData: any = null;
    if (this.signalBackend) {
      const signal = await this.signalBackend.consume(channel);
      if (signal) signalData = signal.data;
    }

    if (signalData == null) {
      // No signal — checkpoint with waiting_channel and exit
      await this.checkpointWithChannel(state, step, channel);
      throw new WaitingForSignal(channel);
    }

    return signalData;
  }

  private async checkpointWithChannel(state: string, step: number, channel: string): Promise<void> {
    if (!this.checkpointManager) return;
    await this.checkpointManager.checkpoint({
      execution_id: this.executionId,
      machine_name: this.config.data.name ?? "unnamed",
      spec_version: this.config.spec_version ?? "0.4.0",
      current_state: state,
      context: this.context,
      step,
      created_at: new Date().toISOString(),
      event: "wait_for",
      waiting_channel: channel,
      parent_execution_id: this.parentExecutionId,
      pending_launches: this.pendingLaunches.length ? this.pendingLaunches : undefined,
      config_hash: this._config_hash,
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Tool loop in machine states (#10)
  // ─────────────────────────────────────────────────────────────────────────

  private async executeToolLoop(
    stateName: string,
    def: State,
  ): Promise<[Record<string, any>, any]> {
    const loopConfig = typeof def.tool_loop === 'object' ? def.tool_loop : {};
    const renderGuardrail = (v: any) => this._render_guardrail(v, { context: this.context, input: this.input }, Number);
    const maxTurns = renderGuardrail(loopConfig.max_turns) ?? 20;
    const maxToolCalls = renderGuardrail(loopConfig.max_tool_calls) ?? 50;
    const toolTimeout = (renderGuardrail(loopConfig.tool_timeout) ?? 30) * 1000;
    const totalTimeout = (renderGuardrail(loopConfig.total_timeout) ?? 600) * 1000;
    const maxCost = loopConfig.max_cost != null ? renderGuardrail(loopConfig.max_cost) : undefined;
    const allowedTools = new Set<string>(loopConfig.allowed_tools ?? []);
    const deniedTools = new Set<string>(loopConfig.denied_tools ?? []);

    // Get executor — need one that supports tool calls (execute_with_tools)
    const agentName = def.agent!;
    const executor = this.getExecutor(agentName);

    // Check if executor supports tool calls
    if (!('execute_with_tools' in executor) || typeof (executor as any).execute_with_tools !== 'function') {
      throw new Error(`Agent '${agentName}' does not support tool calls (execute_with_tools). Use a tool-capable adapter.`);
    }

    // Resolve tool provider (hooks can override)
    let activeToolProvider = this.toolProvider;
    if (this.hooks?.get_tool_provider) {
      const hookProvider = this.hooks.get_tool_provider(stateName, this.context);
      if (hookProvider) activeToolProvider = hookProvider;
    }

    // Resolve tool definitions
    const toolDefs = activeToolProvider?.get_tool_definitions() ?? [];

    // Build initial input
    const agentInput = this.render(def.input ?? {}, { context: this.context, input: this.input });

    let chain: Array<Record<string, any>> = [];
    let turns = 0;
    let toolCallsCount = 0;
    let loopCost = 0;
    const startTime = Date.now();
    let lastContent: string | undefined;
    let context = this.context;

    while (true) {
      // Guardrails
      if (Date.now() - startTime >= totalTimeout) { context._tool_loop_stop = 'timeout'; break; }
      if (turns >= maxTurns) { context._tool_loop_stop = 'max_turns'; break; }
      if (maxCost != null && loopCost >= maxCost) { context._tool_loop_stop = 'cost_limit'; break; }

      // Call agent via executor
      let result: AgentResult;
      if ('execute_with_tools' in executor && typeof (executor as any).execute_with_tools === 'function') {
        if (turns === 0) {
          result = await (executor as any).execute_with_tools(agentInput, toolDefs, undefined, context);
        } else {
          result = await (executor as any).execute_with_tools({}, toolDefs, chain, context);
        }
      } else {
        // Fallback for executors without execute_with_tools
        if (turns === 0) {
          result = await executor.execute(agentInput, context);
        } else {
          result = await executor.execute({}, context);
        }
      }
      result = coerceAgentResult(result);

      turns += 1;
      // Extract cost
      const turnCost = typeof result.cost === 'number' ? result.cost
        : (result.cost && typeof result.cost === 'object') ? ((result.cost as any).total ?? 0) : 0;
      loopCost += turnCost;
      this.totalCost += turnCost;

      context._tool_loop_turns = turns;
      context._tool_loop_cost = loopCost;
      context._tool_calls_count = toolCallsCount;
      context._tool_loop_content = result.content;

      // Error
      if (result.error) {
        throw new Error(`${result.error.type ?? 'AgentError'}: ${result.error.message ?? 'unknown'}`);
      }

      // Seed chain on first turn
      if (turns === 1 && result.rendered_user_prompt) {
        chain.push({ role: 'user', content: result.rendered_user_prompt });
      }

      // Build assistant message
      const assistantMsg: Record<string, any> = { role: 'assistant', content: result.content ?? '' };
      if (result.tool_calls?.length) {
        assistantMsg.tool_calls = result.tool_calls.map(tc => ({
          id: tc.id, type: 'function',
          function: { name: tc.name ?? tc.tool, arguments: typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments) },
        }));
      }
      chain.push(assistantMsg);
      lastContent = result.content ?? undefined;

      // No tool calls = loop complete
      if (result.finish_reason !== 'tool_use' && result.finish_reason !== FinishReason.TOOL_USE) break;

      const pendingCalls = result.tool_calls ?? [];
      if (toolCallsCount + pendingCalls.length > maxToolCalls) {
        context._tool_loop_stop = 'max_tool_calls'; break;
      }

      // Fire on_tool_calls hook
      if (this.hooks?.on_tool_calls && pendingCalls.length) {
        const hookResult = await this.hooks.on_tool_calls(stateName, pendingCalls, context);
        if (hookResult) context = hookResult;
        if (context._abort_tool_loop) { context._tool_loop_stop = 'aborted'; break; }
      }

      // Execute tools
      for (const tc of pendingCalls) {
        // Allow/deny check
        if (deniedTools.size && deniedTools.has(tc.tool)) {
          chain.push({ role: 'tool', tool_call_id: tc.id, content: `Tool '${tc.tool}' is not allowed.` });
          continue;
        }
        if (allowedTools.size && !allowedTools.has(tc.tool)) {
          chain.push({ role: 'tool', tool_call_id: tc.id, content: `Tool '${tc.tool}' is not allowed.` });
          continue;
        }

        // Skip tools that hooks flagged for skipping
        if (context._skip_tool_ids?.includes(tc.id) ||
            context._skip_tool_names?.includes(tc.name ?? tc.tool) ||
            context._skip_tools?.includes(tc.name ?? tc.tool) ||
            context._skip_tools?.includes(tc.id)) {
          chain.push({ role: 'tool', tool_call_id: tc.id, content: 'Tool skipped by hook.' });
          continue;
        }

        let toolResult: ToolResult;
        if (activeToolProvider) {
          try {
            toolResult = await Promise.race([
              activeToolProvider.execute_tool(tc.tool, tc.id, tc.arguments),
              new Promise<ToolResult>((_, reject) => setTimeout(() => reject(new Error('timeout')), toolTimeout)),
            ]);
          } catch (e: any) {
            toolResult = { content: e?.message === 'timeout' ? `Tool '${tc.tool}' timed out` : `Error: ${e}`, is_error: true };
          }
        } else {
          toolResult = { content: `No tool provider configured for '${tc.tool}'`, is_error: true };
        }

        toolCallsCount += 1;
        chain.push({ role: 'tool', tool_call_id: tc.id, content: toolResult.content });
        context._tool_calls_count = toolCallsCount;

        // Fire on_tool_result hook
        if (this.hooks?.on_tool_result) {
          const hookResult = await this.hooks.on_tool_result(stateName, {
            ...tc,
            name: tc.name ?? tc.tool,
            result: toolResult,
          }, context);
          if (hookResult) context = hookResult;
          if (context._abort_tool_loop) { context._tool_loop_stop = 'aborted'; break; }
        }

        // Checkpoint after each tool call with tool_loop_state
        if (this.shouldCheckpoint("execute")) {
          await this.checkpointWithToolLoop(stateName, this.currentStep, chain, turns, toolCallsCount, loopCost);
        }

        // Check for abort or conditional transition
        if (context._abort_tool_loop) { context._tool_loop_stop = 'aborted'; break; }

        const nextState = this.findConditionalTransition(stateName);
        if (nextState) { context._tool_loop_stop = 'transition'; context._tool_loop_next_state = nextState; break; }
      }

      if (context._tool_loop_stop) break;

      // Inject steering messages if set by hooks
      if (context._steering_messages?.length) {
        for (const msg of context._steering_messages) {
          chain.push(msg);
        }
        delete context._steering_messages;
      }
    }

    // Build output
    const output: Record<string, any> = {
      content: lastContent,
      _tool_calls_count: toolCallsCount,
      _tool_loop_turns: turns,
      _tool_loop_cost: loopCost,
      _tool_loop_stop: context._tool_loop_stop ?? 'complete',
    };

    // Apply output_to_context
    if (def.output_to_context) {
      Object.assign(context, this.render(def.output_to_context, { context, output, input: this.input }));
    }

    this.context = context;
    return [context, output];
  }

  private evaluateExpr(expr: string, ctx: { context: any; input: any; output: any }): any {
    if (this.expressionEngine === 'cel') {
      return evaluateCel(expr, ctx);
    }
    return evaluate(expr, ctx);
  }

  private findConditionalTransition(stateName: string): string | null {
    const state = this.config.data.states[stateName];
    if (!state?.transitions) return null;
    for (const t of state.transitions) {
      if (!t.condition) continue;
      if (this.evaluateExpr(t.condition, { context: this.context, input: this.input, output: {} })) {
        return t.to;
      }
    }
    return null;
  }

  private async checkpointWithToolLoop(
    state: string, step: number,
    chain: Array<Record<string, any>>,
    turns: number, toolCallsCount: number, loopCost: number,
  ): Promise<void> {
    if (!this.checkpointManager) return;
    await this.checkpointManager.checkpoint({
      execution_id: this.executionId,
      machine_name: this.config.data.name ?? "unnamed",
      spec_version: this.config.spec_version ?? "0.4.0",
      current_state: state,
      context: this.context,
      step,
      created_at: new Date().toISOString(),
      event: "tool_call",
      parent_execution_id: this.parentExecutionId,
      config_hash: this._config_hash,
      tool_loop_state: {
        chain: [...chain],
        turns,
        tool_calls_count: toolCallsCount,
        cost: loopCost,
      },
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Tool loop helper methods (exposed for testing, matching Python)
  // ─────────────────────────────────────────────────────────────────────────

  _render_guardrail(value: any, vars: Record<string, any>, type: new (v: any) => any): any {
    if (value === null || value === undefined) return null;
    if (typeof value === 'string' && value.includes('{{')) {
      const rendered = renderTemplate(value, vars, "flatmachine");
      if (type === Number) return Number(rendered);
      return rendered;
    }
    return type === Number ? Number(value) : value;
  }

  _build_assistant_message(result: any): Record<string, any> {
    const msg: Record<string, any> = { role: 'assistant', content: result.content ?? '' };
    const toolCalls = result.tool_calls;
    if (toolCalls?.length) {
      msg.tool_calls = toolCalls.map((tc: any) => ({
        id: tc.id,
        type: 'function',
        function: {
          name: tc.name ?? tc.tool,
          arguments: typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments ?? {}),
        },
      }));
    }
    return msg;
  }

  _extract_cost(result: any): number {
    const cost = result?.cost;
    if (cost == null) return 0;
    if (typeof cost === 'number') return cost;
    if (typeof cost === 'object' && 'total' in cost) return Number(cost.total);
    return 0;
  }

  _resolve_tool_definitions = (agentName?: string, provider?: any): any[] => {
    const tp = provider ?? this?.toolProvider;
    const defs = tp?.get_tool_definitions?.() ?? [];
    // Check if agent has inline tools
    if (agentName && this?.config) {
      const agentConfig = this.config.data?.agents?.[agentName];
      if (agentConfig && typeof agentConfig === 'object') {
        const inlineTools = (agentConfig as any).data?.tools ?? (agentConfig as any).tools;
        if (Array.isArray(inlineTools)) {
          return [...defs, ...inlineTools];
        }
      }
    }
    return defs;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Existing methods (updated)
  // ─────────────────────────────────────────────────────────────────────────

  private findInitialState(): string {
    for (const [name, state] of Object.entries(this.config.data.states)) {
      if (state.type === "initial") return name;
    }
    return Object.keys(this.config.data.states)[0]!;
  }

  private getExecutor(agentName: string): AgentExecutor {
    let executor = this.executors.get(agentName);
    if (executor) return executor;

    const rawRef = this.config.data.agents?.[agentName] ?? agentName;
    const agentRef = normalizeAgentRef(rawRef);
    const adapterContext: AgentAdapterContext = {
      config_dir: this.configDir,
      settings: this.config.data.settings ?? {},
      machine_name: this.config.data.name ?? 'unnamed',
      profiles_file: this.profilesFile,
    };
    executor = this.agentRegistry.createExecutor({
      agent_name: agentName,
      agent_ref: agentRef,
      context: adapterContext,
    });
    this.executors.set(agentName, executor);
    return executor;
  }

  private async executeAgent(def: State): Promise<any> {
    const executor = this.getExecutor(def.agent!);
    const input = this.render(def.input ?? {}, { context: this.context, input: this.input });
    const result = await executor.execute(input, this.context);
    const agentResult = coerceAgentResult(result);

    // Accumulate metrics
    if (agentResult.usage) {
      this.totalApiCalls += (agentResult.usage as any).api_calls ?? 1;
    } else {
      this.totalApiCalls += 1;
    }
    if (agentResult.cost != null) {
      const costVal = typeof agentResult.cost === 'number' ? agentResult.cost
        : typeof agentResult.cost === 'object' ? (agentResult.cost as any).total ?? 0 : 0;
      this.totalCost += costVal;
    }

    if (agentResult.error) {
      const err = agentResult.error;
      throw new Error(`${err.type ?? 'AgentError'}: ${err.message ?? 'unknown'}`);
    }

    return agentResultOutputPayload(agentResult);
  }

  private async executeMachine(def: State): Promise<any> {
    const machineDefs = Array.isArray(def.machine) ? def.machine : [def.machine!];
    const mode = def.mode ?? "settled";
    const timeoutMs = def.timeout && def.timeout > 0 ? def.timeout * 1000 : undefined;

    // foreach - dynamic parallelism
    if (def.foreach) {
      let rawItems = this.render({ items: def.foreach }, { context: this.context, input: this.input }).items;
      // If render returned a JSON string (from {{ template }}), parse it
      if (typeof rawItems === 'string') {
        try { rawItems = JSON.parse(rawItems); } catch { /* leave as string */ }
      }
      const items = rawItems as any[];
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
      if (!t.condition || this.evaluateExpr(t.condition, { context: this.context, input: this.input, output })) {
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
      total_api_calls: this.totalApiCalls,
      total_cost: this.totalCost,
      parent_execution_id: this.parentExecutionId,
      pending_launches: this.pendingLaunches.length ? this.pendingLaunches : undefined,
      config_hash: this._config_hash,
    });
  }

  private render(template: any, vars: Record<string, any>): any {
    if (typeof template === "string") {
      // Bare path (no {{ }}) — resolve directly, preserving native type
      const bareResult = this.resolveBarePath(template, vars);
      if (bareResult !== undefined) return bareResult;
      // Jinja/Nunjucks template — render to string (like Python Jinja2)
      return renderTemplate(template, vars, "flatmachine");
    }
    if (Array.isArray(template)) return template.map(t => this.render(t, vars));
    if (typeof template === "object" && template !== null) {
      return Object.fromEntries(Object.entries(template).map(([k, v]) => [k, this.render(v, vars)]));
    }
    return template;
  }

  /**
   * Resolve bare path references (no {{ }}) to preserve native types.
   * Only matches dotted paths like `context.value` or `output.items` that start
   * with a known variable root. Single-segment strings are treated as literal values.
   * Returns null for missing paths (Python's None), undefined if not a bare path.
   */
  private resolveBarePath(template: string, vars: Record<string, any>): any | undefined {
    const stripped = template.trim();
    // Must NOT contain template syntax
    if (stripped.includes('{{') || stripped.includes('{%')) return undefined;
    // Must be a valid dotted path with at least 2 segments (root.property)
    if (!/^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]+$/.test(stripped)) return undefined;
    // Root segment must be a known variable
    const root = stripped.split('.')[0]!;
    if (!(root in vars)) return undefined;
    const resolved = this.resolvePath(vars, stripped);
    // Return null for missing paths (not undefined) to match Python's None
    return resolved === undefined ? null : resolved;
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
    throw new Error(`Unknown persistence backend '${setting}'`);
  }

  private createPersistenceBackend(config: NonNullable<MachineConfig["data"]["persistence"]>) {
    if (config.backend === "memory") return new MemoryBackend();
    if (config.backend === "local") return new LocalFileBackend();
    if (config.backend === "sqlite") {
      return new SQLiteCheckpointBackend(config.db_path ?? 'flatmachines.sqlite');
    }
    throw new Error(`Unknown persistence backend '${config.backend}'`);
  }

  /**
   * Resolve agent references at construction time.
   * - String refs (paths): read the file and inline the config
   * - Typed refs with `ref`: read the file and inline as `config`
   * - Already-inline configs: left as-is
   */
  private resolveAgentRefs(): void {
    const agents = this.config.data.agents;
    if (!agents || typeof agents !== 'object') return;

    for (const [name, ref] of Object.entries(agents as Record<string, any>)) {
      if (typeof ref === 'string') {
        // String path reference
        const resolved = this.resolveAgentRefPath(ref);
        if (resolved) {
          (agents as any)[name] = resolved;
        }
      } else if (typeof ref === 'object' && ref !== null && ref.ref) {
        // Typed ref: { type: "...", ref: "./path.yml" }
        const resolved = this.resolveAgentRefPath(ref.ref);
        if (resolved) {
          const result: any = { ...ref, config: resolved };
          delete result.ref;
          (agents as any)[name] = result;
        }
      }
    }
  }

  private resolveAgentRefPath(refPath: string): any | null {
    try {
      const fullPath = resolve(this.configDir, refPath);
      if (!existsSync(fullPath)) return null;
      const content = readFileSync(fullPath, 'utf-8');
      if (fullPath.endsWith('.json')) {
        return JSON.parse(content);
      }
      return yaml.parse(content);
    } catch {
      return null;
    }
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
      persistence: this.checkpointManager?.persistenceBackend,
      executionLock: this.executionLock,
      resultBackend: this.resultBackend,
      hooksRegistry: this._hooksRegistry,
      executionId: overrides?.executionId,
      parentExecutionId: overrides?.parentExecutionId,
      profilesFile: this.profilesFile,
      signalBackend: this.signalBackend,
      triggerBackend: this.triggerBackend,
      agentRegistry: this.agentRegistry,
      toolProvider: this.toolProvider,
      configStore: this._config_store,
    } as ExtendedMachineOptions);
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
    const resolved = resolve(this.configDir, pathRef);
    return { config: resolved, configDir: dirname(resolved) };
  }

  private resolveProfilesFile(explicitPath?: string): string | undefined {
    // 1. Explicit non-empty path takes precedence
    if (explicitPath && explicitPath.trim().length > 0) return explicitPath;
    // 2. Config-level profiles setting
    const configProfiles = (this.config as any)?.data?.profiles;
    if (typeof configProfiles === "string" && configProfiles.trim().length > 0) {
      return resolve(this.configDir, configProfiles);
    }
    // 3. Auto-discover profiles.yml in config directory
    const discovered = resolve(this.configDir, "profiles.yml");
    if (existsSync(discovered)) return discovered;
    return undefined;
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
}
