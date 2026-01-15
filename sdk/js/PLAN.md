# FlatAgents TypeScript SDK - Implementation Plan

**Target:** ~1400 lines, full feature parity
**Examples:** helloworld, parallelism, human-in-the-loop, peering

---

## File Structure

```
sdk/js/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts           # Exports (~20 lines)
│   ├── types.ts           # TypeScript types (~150 lines)
│   ├── expression.ts      # Condition parser (~100 lines)
│   ├── execution.ts       # Default + retry (~80 lines)
│   ├── hooks.ts           # Hooks + webhooks (~100 lines)
│   ├── persistence.ts     # Checkpoint/resume (~200 lines)
│   ├── results.ts         # Inter-machine IPC (~50 lines)
│   ├── mcp.ts             # MCP tool integration (~100 lines)
│   ├── flatagent.ts       # Single LLM call (~200 lines)
│   └── flatmachine.ts     # State machine (~400 lines)
├── examples/
│   ├── helloworld/
│   ├── parallelism/
│   ├── human-in-the-loop/
│   └── peering/
└── tests/
```

---

## Dependencies

```json
{
  "dependencies": {
    "nunjucks": "^3.2.4",
    "yaml": "^2.4.0",
    "ai": "^3.0.0",
    "@ai-sdk/openai": "^0.0.70",
    "@ai-sdk/anthropic": "^0.0.55",
    "@modelcontextprotocol/sdk": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.7.0",
    "vitest": "^2.1.0",
    "tsup": "^8.3.0"
  }
}
```

---

## Implementation

### 1. types.ts (~150 lines)

```typescript
export interface AgentConfig {
  spec: "flatagent";
  spec_version: string;
  data: {
    name?: string;
    model: { name: string; provider?: string; temperature?: number; max_tokens?: number };
    system: string;
    user: string;
    output?: Record<string, { type: string; description?: string }>;
    mcp?: { servers: Record<string, MCPServer>; tool_filter?: ToolFilter; tool_prompt?: string };
  };
}

export interface MachineConfig {
  spec: "flatmachine";
  spec_version: string;
  data: {
    name?: string;
    context?: Record<string, any>;
    states: Record<string, State>;
    persistence?: { enabled: boolean; backend: "local" | "memory" };
  };
}

export interface State {
  type?: "initial" | "final";
  agent?: string;
  machine?: string | string[];
  execution?: { type: "default" | "retry"; backoffs?: number[]; jitter?: number };
  input?: Record<string, any>;
  output_to_context?: Record<string, any>;
  output?: Record<string, any>;
  transitions?: { condition?: string; to: string }[];
  on_error?: string;
  foreach?: string;
  as?: string;
  launch?: string | string[];
  launch_input?: Record<string, any>;
}

export interface MachineSnapshot {
  executionId: string;
  machineName: string;
  currentState: string;
  context: Record<string, any>;
  step: number;
  createdAt: string;
  parentExecutionId?: string;
}
```

### 2. expression.ts (~100 lines)

```typescript
export function evaluate(expr: string, ctx: { context: any; input: any; output: any }): boolean;
```

Recursive descent parser supporting:
- Field access: `context.field`, `input.field`, `output.field`
- Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Boolean: `and`, `or`, `not`
- Literals: `"string"`, `42`, `true`, `false`, `null`

### 3. execution.ts (~80 lines)

```typescript
export interface ExecutionConfig {
  type: "default" | "retry";
  backoffs?: number[];
  jitter?: number;
}

export interface ExecutionType {
  execute<T>(fn: () => Promise<T>): Promise<T>;
}

export class DefaultExecution implements ExecutionType {
  async execute<T>(fn: () => Promise<T>): Promise<T> {
    return fn();
  }
}

export class RetryExecution implements ExecutionType {
  constructor(private backoffs = [2, 8, 16, 35], private jitter = 0.1) {}

  async execute<T>(fn: () => Promise<T>): Promise<T> {
    let lastError: Error | undefined;
    for (let i = 0; i <= this.backoffs.length; i++) {
      try {
        return await fn();
      } catch (err) {
        lastError = err as Error;
        if (i < this.backoffs.length) {
          const delay = this.backoffs[i] * (1 + this.jitter * (Math.random() * 2 - 1));
          await new Promise(r => setTimeout(r, delay * 1000));
        }
      }
    }
    throw lastError;
  }
}

export function getExecutionType(config?: ExecutionConfig): ExecutionType {
  if (config?.type === "retry") return new RetryExecution(config.backoffs, config.jitter);
  return new DefaultExecution();
}
```

### 4. hooks.ts (~100 lines)

```typescript
export interface MachineHooks {
  onMachineStart?(context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
  onMachineEnd?(context: Record<string, any>, output: any): any | Promise<any>;
  onStateEnter?(state: string, context: Record<string, any>): Record<string, any> | Promise<Record<string, any>>;
  onStateExit?(state: string, context: Record<string, any>, output: any): any | Promise<any>;
  onTransition?(from: string, to: string, context: Record<string, any>): string | Promise<string>;
  onError?(state: string, error: Error, context: Record<string, any>): string | null | Promise<string | null>;
}

export class WebhookHooks implements MachineHooks {
  constructor(private url: string) {}

  private async send(event: string, data: Record<string, any>) {
    await fetch(this.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, ...data, timestamp: new Date().toISOString() }),
    });
  }

  async onMachineStart(context: Record<string, any>) { await this.send("machine_start", { context }); return context; }
  async onMachineEnd(context: Record<string, any>, output: any) { await this.send("machine_end", { context, output }); return output; }
  async onStateEnter(state: string, context: Record<string, any>) { await this.send("state_enter", { state, context }); return context; }
  async onStateExit(state: string, context: Record<string, any>, output: any) { await this.send("state_exit", { state, context, output }); return output; }
}

export class CompositeHooks implements MachineHooks {
  constructor(private hooks: MachineHooks[]) {}
  // Chain hooks in order, passing results through
}
```

### 5. persistence.ts (~200 lines)

```typescript
export interface PersistenceBackend {
  save(key: string, snapshot: MachineSnapshot): Promise<void>;
  load(key: string): Promise<MachineSnapshot | null>;
  delete(key: string): Promise<void>;
  list(prefix: string): Promise<string[]>;
}

export class MemoryBackend implements PersistenceBackend {
  private store = new Map<string, MachineSnapshot>();
  async save(key: string, snapshot: MachineSnapshot) { this.store.set(key, snapshot); }
  async load(key: string) { return this.store.get(key) ?? null; }
  async delete(key: string) { this.store.delete(key); }
  async list(prefix: string) { return [...this.store.keys()].filter(k => k.startsWith(prefix)); }
}

export class LocalFileBackend implements PersistenceBackend {
  constructor(private dir = ".checkpoints") {}
  // File-based with atomic writes via temp file + rename
  // Key format: {executionId}/step_{step:06d}.json
}

export class CheckpointManager {
  constructor(private backend: PersistenceBackend) {}

  async checkpoint(snapshot: MachineSnapshot): Promise<void> {
    const key = `${snapshot.executionId}/step_${String(snapshot.step).padStart(6, "0")}`;
    await this.backend.save(key, snapshot);
  }

  async restore(executionId: string): Promise<MachineSnapshot | null> {
    const keys = await this.backend.list(executionId);
    if (!keys.length) return null;
    return this.backend.load(keys.sort().pop()!);
  }
}
```

### 6. results.ts (~50 lines)

```typescript
export interface ResultBackend {
  write(uri: string, data: any): Promise<void>;
  read(uri: string, options?: { block?: boolean; timeout?: number }): Promise<any>;
  exists(uri: string): Promise<boolean>;
  delete(uri: string): Promise<void>;
}

const store = new Map<string, any>();

export const inMemoryResultBackend: ResultBackend = {
  async write(uri, data) { store.set(uri, data); },
  async read(uri, opts) {
    if (opts?.block) {
      const deadline = Date.now() + (opts.timeout ?? 30000);
      while (!store.has(uri) && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 100));
      }
    }
    return store.get(uri);
  },
  async exists(uri) { return store.has(uri); },
  async delete(uri) { store.delete(uri); },
};
```

### 7. mcp.ts (~100 lines)

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

export interface MCPServer {
  command?: string;
  args?: string[];
  serverUrl?: string;
}

export interface ToolFilter {
  allow?: string[];
  deny?: string[];
}

export class MCPToolProvider {
  private clients = new Map<string, Client>();

  async connect(servers: Record<string, MCPServer>): Promise<void> {
    for (const [name, server] of Object.entries(servers)) {
      if (server.command) {
        const transport = new StdioClientTransport({ command: server.command, args: server.args });
        const client = new Client({ name, version: "1.0.0" });
        await client.connect(transport);
        this.clients.set(name, client);
      }
    }
  }

  async listTools(filter?: ToolFilter): Promise<any[]> {
    const tools: any[] = [];
    for (const [serverName, client] of this.clients) {
      const { tools: serverTools } = await client.listTools();
      for (const tool of serverTools) {
        const name = `${serverName}:${tool.name}`;
        if (this.matchesFilter(name, filter)) tools.push({ ...tool, name });
      }
    }
    return tools;
  }

  async callTool(name: string, args: any): Promise<any> {
    const [server, tool] = name.split(":");
    return this.clients.get(server)?.callTool({ name: tool, arguments: args });
  }

  private matchesFilter(name: string, filter?: ToolFilter): boolean {
    if (filter?.deny?.some(p => this.match(name, p))) return false;
    if (filter?.allow && !filter.allow.some(p => this.match(name, p))) return false;
    return true;
  }

  private match(name: string, pattern: string): boolean {
    return pattern.includes("*") ? new RegExp(pattern.replace(/\*/g, ".*")).test(name) : name === pattern;
  }
}
```

### 8. flatagent.ts (~200 lines)

```typescript
import { generateText } from "ai";
import { createOpenAI } from "@ai-sdk/openai";
import { createAnthropic } from "@ai-sdk/anthropic";
import nunjucks from "nunjucks";
import yaml from "yaml";
import fs from "node:fs";

export class FlatAgent {
  public config: AgentConfig;
  private mcpProvider?: MCPToolProvider;

  constructor(configOrPath: AgentConfig | string) {
    this.config = typeof configOrPath === "string"
      ? yaml.parse(fs.readFileSync(configOrPath, "utf-8"))
      : configOrPath;
  }

  async call(input: Record<string, any>): Promise<{ content: string; output: any }> {
    // Connect MCP if configured
    if (this.config.data.mcp && !this.mcpProvider) {
      this.mcpProvider = new MCPToolProvider();
      await this.mcpProvider.connect(this.config.data.mcp.servers);
    }

    // Render prompts
    const tools = this.mcpProvider ? await this.mcpProvider.listTools(this.config.data.mcp?.tool_filter) : [];
    const system = nunjucks.renderString(this.config.data.system, { input, tools });
    const user = nunjucks.renderString(this.config.data.user, { input, tools });

    // Call LLM
    const { text } = await generateText({
      model: this.getModel(),
      system,
      prompt: user,
    });

    // Extract structured output
    const output = this.extractOutput(text);
    return { content: text, output };
  }

  private getModel() {
    const { provider = "openai", name } = this.config.data.model;
    if (provider === "anthropic") return createAnthropic()(`anthropic/${name}`);
    return createOpenAI()(`openai/${name}`);
  }

  private extractOutput(text: string): any {
    // Strip markdown fences and parse JSON
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const json = match ? match[1].trim() : text.trim();
    try { return JSON.parse(json); } catch { return { content: text }; }
  }
}
```

### 9. flatmachine.ts (~400 lines)

```typescript
import nunjucks from "nunjucks";
import yaml from "yaml";
import fs from "node:fs";
import { randomUUID } from "node:crypto";

export interface MachineOptions {
  config: MachineConfig | string;
  hooks?: MachineHooks;
  persistence?: PersistenceBackend;
  resultBackend?: ResultBackend;
  configDir?: string;
}

export class FlatMachine {
  public config: MachineConfig;
  public executionId = randomUUID();
  private agents = new Map<string, FlatAgent>();
  private context: Record<string, any> = {};
  private hooks?: MachineHooks;
  private checkpointManager?: CheckpointManager;
  private resultBackend?: ResultBackend;
  private configDir: string;

  constructor(options: MachineOptions) {
    this.config = typeof options.config === "string"
      ? yaml.parse(fs.readFileSync(options.config, "utf-8"))
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
      agent = new FlatAgent(`${this.configDir}/${def.agent}`);
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
```

---

## Examples

### helloworld
- Agent returns next character
- Machine loops until "Hello World" built
- ~2 YAML files, ~20 lines main.ts

### parallelism
- `machine: [a,b,c]` - parallel execution
- `foreach` - dynamic parallelism
- `launch` - fire-and-forget
- ~5 YAML files, ~30 lines main.ts

### human-in-the-loop
- Custom hooks pause for readline input
- Approval gates before proceeding
- ~2 YAML files, ~50 lines main.ts

### peering
- Parent machine launches children
- Children write results to resultBackend
- Parent reads results
- Demonstrates checkpoint/resume
- ~4 YAML files, ~40 lines main.ts

---

## Checklist

- [ ] Project setup (package.json, tsconfig.json, tsup)
- [ ] types.ts
- [ ] expression.ts
- [ ] execution.ts (default + retry)
- [ ] hooks.ts (interface + WebhookHooks + CompositeHooks)
- [ ] persistence.ts (MemoryBackend + LocalFileBackend + CheckpointManager)
- [ ] results.ts (in-memory backend)
- [ ] mcp.ts (MCPToolProvider)
- [ ] flatagent.ts
- [ ] flatmachine.ts
- [ ] helloworld example
- [ ] parallelism example
- [ ] human-in-the-loop example
- [ ] peering example
- [ ] Tests
- [ ] README.md
- [ ] Publish to npm

---

## Deferred

- Parallel sampling execution type
- MDAP voting execution type
- CEL expressions

---

## Line Count

| File | Lines |
|------|-------|
| types.ts | 150 |
| expression.ts | 100 |
| execution.ts | 80 |
| hooks.ts | 100 |
| persistence.ts | 200 |
| results.ts | 50 |
| mcp.ts | 100 |
| flatagent.ts | 200 |
| flatmachine.ts | 400 |
| index.ts | 20 |
| **Total** | **~1400** |
