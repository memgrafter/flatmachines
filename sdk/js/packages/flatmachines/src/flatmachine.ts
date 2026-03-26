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
import {
  AgentResponse, FinishReason,
  AgentExecutor, AgentResult, AgentRef,
  AgentAdapterRegistry, AgentAdapterContext,
  normalizeAgentRef, coerceAgentResult, agentResultOutputPayload,
} from '@memgrafter/flatagents';
import type { ToolProvider, ToolResult } from '@memgrafter/flatagents';
import { getExecutionType } from './execution';
import { CheckpointManager, LocalFileBackend, MemoryBackend } from './persistence';
import {
  evaluateExpr as _evaluateExpr,
  renderValue,
  renderGuardrail,
  ExpressionEngine,
} from './machine_context';
import {
  makeResultUri,
  injectMachineMetadata,
  buildAssistantMessage,
  extractCost,
  normalizeMachineResult,
  firstCompleted,
  withTimeout,
  awaitWithMode,
} from './machine_lifecycle';
import { SQLiteCheckpointBackend, SQLiteConfigStore, configHash } from './persistence_sqlite';
import type { ConfigStore } from './persistence_sqlite';
import { inMemoryResultBackend } from './results';
import { LocalFileLock, NoOpLock } from './locking';
import { SQLiteLeaseLock } from './locking_sqlite';
import { HooksRegistry } from './hooks';
import { FlatAgentAdapter, FlatAgentExecutor } from './adapters/flatagent_adapter';
import { SignalBackend, TriggerBackend, NoOpTrigger } from './signals';
// Expression evaluation is delegated to machine_context.ts

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
  configStore?: ConfigStore;
  /** @deprecated Use configStore */
  config_store?: ConfigStore;
}

// ─────────────────────────────────────────────────────────────────────────────
// FlatMachine
// ─────────────────────────────────────────────────────────────────────────────

export class FlatMachine {
  public config: MachineConfig;
  public executionId: string = randomUUID();
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
  public _config_store?: ConfigStore;
  // Resolved config as raw string
  public _config_raw?: string;
  // Config hash for resume support
  public _config_hash?: string;
  // Whether config store put is pending (deferred from constructor)
  private _configStorePending = false;

  // New Phase 3+ backends
  private signalBackend?: SignalBackend;
  private triggerBackend: TriggerBackend;
  private agentRegistry: AgentAdapterRegistry;
  private toolProvider?: ToolProvider;
  private expressionEngine: 'simple' | 'cel' = 'simple';

  constructor(options: MachineOptions | ExtendedMachineOptions) {
    const configIsPath = typeof options.config === "string";
    this.config = configIsPath
      ? yaml.parse(readFileSync(options.config as string, "utf-8")) as MachineConfig
      : options.config as MachineConfig;
    this._hooksRegistry = options.hooksRegistry ?? new HooksRegistry();
    this.hooks = this.resolveHooks(options.hooks);
    this.configDir = options.configDir ?? (configIsPath ? dirname(resolve(options.config as string)) : process.cwd());
    // FlatMachine does NOT auto-discover profiles.yml — only resolve explicit or config-level paths
    if (options.profilesFile) {
      this.profilesFile = options.profilesFile;
    } else {
      const configProfiles = this.config.data.profiles;
      if (typeof configProfiles === "string" && configProfiles.trim().length > 0) {
        this.profilesFile = resolve(this.configDir, configProfiles);
      }
    }
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
    const explicitConfigStore = extOpts.configStore ?? extOpts.config_store;
    if (explicitConfigStore && !this._config_store) {
      this._config_store = explicitConfigStore;
    }

    // Agent adapter registry with default flatagent adapter
    this.agentRegistry = extOpts.agentRegistry ?? new AgentAdapterRegistry();
    if (!extOpts.agentRegistry) {
      this.agentRegistry.register(new FlatAgentAdapter());
    }

    // Expression engine
    this.expressionEngine = this.config.data.expression_engine ?? 'simple';

    // Resolve agent references at construction time
    this.resolveAgentRefs();

    // Store resolved config as raw string
    this._config_raw = yaml.stringify(this.config);

    // Compute config hash synchronously (hash is needed for checkpoints)
    if (this._config_raw) {
      this._config_hash = configHash(this._config_raw);
    }

    // Config store put is deferred to execute() to avoid constructor async race
    this._configStorePending = !!(this._config_store && this._config_raw);

    if (options.persistence) {
      this.checkpointManager = new CheckpointManager(options.persistence);
    } else if (this.config.data.persistence?.enabled) {
      const backend = this.createPersistenceBackend(this.config.data.persistence);
      this.checkpointManager = new CheckpointManager(backend);
      // Auto-wire locking for local backend
      if (this.config.data.persistence?.backend === 'local') {
        if (this.executionLock instanceof NoOpLock && !options.executionLock) {
          this.executionLock = new LocalFileLock();
        }
      }
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

  /**
   * Release all resources owned by this machine instance.
   *
   * Closes persistence backends, signal backends, and config stores that
   * expose a `close()` method. Safe to call multiple times. Should be called
   * when the machine is no longer needed to prevent DB handle leaks.
   *
   * Supports `Symbol.dispose` for use with `using` declarations (TS 5.2+).
   */
  close(): void {
    const closeable = [
      this.checkpointManager?.persistenceBackend,
      this.signalBackend,
      this._config_store,
    ];
    for (const backend of closeable) {
      if (backend && typeof (backend as any).close === 'function') {
        try {
          (backend as any).close();
        } catch {
          // Best-effort cleanup
        }
      }
    }
  }

  [Symbol.dispose](): void {
    this.close();
  }

  private resolveHooks(explicit?: MachineHooks): MachineHooks | undefined {
    if (explicit) return explicit;
    const hooksConfig = this.config.data.hooks;
    if (!hooksConfig) return undefined;
    return this._hooksRegistry.resolve(hooksConfig);
  }

  async execute(input?: Record<string, any>, resumeSnapshot?: MachineSnapshot): Promise<any> {
    // Flush deferred config store put (moved from constructor to avoid async race)
    if (this._configStorePending && this._config_store && this._config_raw) {
      await this._config_store.put(this._config_raw);
      this._configStorePending = false;
    }

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
    injectMachineMetadata(this.context, {
      executionId: this.executionId,
      machineName: this.config.data.name ?? 'unnamed',
      specVersion: this.config.spec_version ?? '0.1.0',
      step,
      state,
      parentExecutionId: this.parentExecutionId,
      totalApiCalls: this.totalApiCalls,
      totalCost: this.totalCost,
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
    const guardVars = { context: this.context, input: this.input };
    const maxTurns = this._render_guardrail(loopConfig.max_turns, guardVars, Number) ?? 20;
    const maxToolCalls = this._render_guardrail(loopConfig.max_tool_calls, guardVars, Number) ?? 50;
    const toolTimeout = (this._render_guardrail(loopConfig.tool_timeout, guardVars, Number) ?? 30) * 1000;
    const totalTimeout = (this._render_guardrail(loopConfig.total_timeout, guardVars, Number) ?? 600) * 1000;
    const maxCost = loopConfig.max_cost != null ? this._render_guardrail(loopConfig.max_cost, guardVars, Number) : undefined;
    const allowedTools = new Set<string>(loopConfig.allowed_tools ?? []);
    const deniedTools = new Set<string>(loopConfig.denied_tools ?? []);

    // Get executor — need one that supports tool calls (execute_with_tools)
    const agentName = def.agent!;
    const executor = this.getExecutor(agentName);

    // Check if executor supports tool calls
    if (!executor.execute_with_tools) {
      throw new Error(`Agent '${agentName}' does not support tool calls (execute_with_tools). Use a tool-capable adapter.`);
    }

    // Resolve tool provider (hooks can override)
    let activeToolProvider = this.toolProvider;
    if (this.hooks?.get_tool_provider) {
      const hookProvider = this.hooks.get_tool_provider(stateName, this.context);
      if (hookProvider) activeToolProvider = hookProvider;
    }

    // Resolve tool definitions (provider + agent YAML, provider overrides by name)
    const toolDefs = this._resolve_tool_definitions(agentName, activeToolProvider);

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
      if (executor.execute_with_tools) {
        if (turns === 0) {
          result = await executor.execute_with_tools(agentInput, toolDefs, undefined, context);
        } else {
          result = await executor.execute_with_tools({}, toolDefs, chain, context);
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
      const turnCost = this._extract_cost(result);
      loopCost += turnCost;
      this.totalCost += turnCost;

      context._tool_loop_turns = turns;
      context._tool_loop_cost = loopCost;
      context._tool_calls_count = toolCallsCount;
      context._tool_loop_content = result.content;
      context._tool_loop_usage = result.usage;

      // Error
      if (result.error) {
        throw new Error(`${result.error.type ?? 'AgentError'}: ${result.error.message ?? 'unknown'}`);
      }

      // Seed chain on first turn
      if (turns === 1 && result.rendered_user_prompt) {
        chain.push({ role: 'user', content: result.rendered_user_prompt });
      }

      // Build assistant message
      chain.push(buildAssistantMessage(result));
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
        const toolName = tc.name ?? tc.tool;
        if (deniedTools.size && deniedTools.has(toolName)) {
          chain.push({ role: 'tool', tool_call_id: tc.id, content: `Tool '${toolName}' is not allowed.` });
          continue;
        }
        if (allowedTools.size && !allowedTools.has(toolName)) {
          chain.push({ role: 'tool', tool_call_id: tc.id, content: `Tool '${toolName}' is not allowed.` });
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
              activeToolProvider.execute_tool(tc.name ?? tc.tool, tc.id, tc.arguments),
              new Promise<ToolResult>((_, reject) => setTimeout(() => reject(new Error('timeout')), toolTimeout)),
            ]);
          } catch (e: any) {
            toolResult = { content: e?.message === 'timeout' ? `Tool '${toolName}' timed out` : `Error: ${e}`, is_error: true };
          }
        } else {
          toolResult = { content: `No tool provider configured for '${toolName}'`, is_error: true };
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

    // Save chain to context for preservation/inspection
    context._tool_loop_chain = [...chain];

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
    return _evaluateExpr(expr, ctx, this.expressionEngine);
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
    return renderGuardrail(value, vars, type);
  }

  _build_assistant_message(result: any): Record<string, any> {
    return buildAssistantMessage(result);
  }

  _extract_cost(result: any): number {
    return extractCost(result);
  }

  _resolve_tool_definitions(agentName?: string, provider?: any): any[] {
    const tp = provider ?? this?.toolProvider;
    const providerDefs = tp?.get_tool_definitions?.() ?? [];

    if (!agentName) {
      return providerDefs;
    }

    const agentConfig = this._get_agent_config(agentName);
    const yamlDefs = agentConfig?.data?.tools ?? [];

    if (!providerDefs.length) {
      return yamlDefs;
    }
    if (!yamlDefs.length) {
      return providerDefs;
    }

    // Merge: provider overrides YAML by function name
    const providerNames = new Set<string>();
    for (const d of providerDefs) {
      const fn = d?.function ?? {};
      if (fn?.name) {
        providerNames.add(String(fn.name));
      }
    }

    const merged = [...providerDefs];
    for (const d of yamlDefs) {
      const fn = d?.function ?? {};
      if (!providerNames.has(String(fn?.name ?? ''))) {
        merged.push(d);
      }
    }

    return merged;
  }

  _get_agent_config(agentName: string): Record<string, any> | null {
    const agentsMap = this.config.data?.agents ?? {};
    const ref = agentsMap[agentName];
    if (ref == null) return null;

    // String path to flatagent config
    if (typeof ref === 'string') {
      try {
        const fullPath = resolve(this.configDir, ref);
        return yaml.parse(readFileSync(fullPath, 'utf-8')) as Record<string, any>;
      } catch {
        return null;
      }
    }

    // Inline flatagent config (object ref)
    if (ref.spec === 'flatagent') {
      return ref;
    }

    // Typed adapter ref
    if (ref.type === 'flatagent') {
      if (typeof ref.config === 'object' && ref.config) {
        if (ref.config.spec === 'flatagent') {
          return ref.config;
        }
      }

      if (typeof ref.ref === 'string') {
        try {
          const fullPath = resolve(this.configDir, ref.ref);
          return yaml.parse(readFileSync(fullPath, 'utf-8')) as Record<string, any>;
        } catch {
          return null;
        }
      }
    }

    return null;
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
      this.totalApiCalls += agentResult.usage.api_calls ?? 1;
    } else {
      this.totalApiCalls += 1;
    }
    this.totalCost += this._extract_cost(agentResult);

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
      const items = Array.isArray(rawItems) ? rawItems : [rawItems];
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
    return renderValue(template, vars);
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

    for (const [name, ref] of Object.entries(agents)) {
      if (typeof ref === 'string') {
        // String path reference
        const resolved = this.resolveAgentRefPath(ref);
        if (resolved) {
          agents[name] = resolved;
        }
      } else if (typeof ref === 'object' && ref !== null && 'ref' in ref && typeof ref.ref === 'string') {
        // Typed ref: { type: "...", ref: "./path.yml", config?: {...} }
        const resolved = this.resolveAgentRefPath(ref.ref);
        if (resolved) {
          // Merge inline config overrides on top of file config
          const mergedConfig = ref.config ? { ...resolved, ...(ref.config as Record<string, any>) } : resolved;
          const { ref: _ref, ...rest } = ref;
          agents[name] = { ...rest, config: mergedConfig };
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

  /**
   * Resolve profiles file path. When called with an explicit path, returns it.
   * When called with empty/undefined, discovers profiles.yml in configDir.
   * NOTE: FlatMachine constructor does NOT call this for auto-discovery.
   */
  resolveProfilesFile(explicitPath?: string): string | undefined {
    // 1. Explicit non-empty path takes precedence
    if (explicitPath && explicitPath.trim().length > 0) return explicitPath;
    // 2. Config-level profiles setting
    const configProfiles = this.config.data.profiles;
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
    return makeResultUri(executionId);
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
    return normalizeMachineResult(result);
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
    return awaitWithMode(tasks, mode, timeoutMs);
  }
}
