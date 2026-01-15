# FlatAgents TypeScript SDK

TypeScript SDK for FlatAgents - Declarative LLM orchestration with YAML.

## Installation

```bash
npm install flatagents
```

## Quick Start

### Single Agent Call

```typescript
import { FlatAgent } from 'flatagents';

const agent = new FlatAgent('agent.yml');
const result = await agent.call({ query: "Hello World" });
console.log(result.output);
```

### State Machine Execution

```typescript
import { FlatMachine } from 'flatagents';

const machine = new FlatMachine({
  config: 'machine.yml',
  hooks: customHooks,
  persistence: new MemoryBackend()
});

const result = await machine.execute({ input: "Hello" });
console.log(result);
```

## Core Concepts

### FlatAgent
A single LLM call configured in YAML:

```yaml
spec: flatagent
spec_version: "1.0"
data:
  name: my_agent
  model:
    name: gpt-4o-mini
    provider: openai
  system: "You are a helpful assistant."
  user: "{{ input.query }}"
  output:
    response:
      type: str
      description: "The response"
```

### FlatMachine
A state machine that orchestrates agents:

```yaml
spec: flatmachine
spec_version: "1.0"
data:
  name: my_workflow
  context:
    result: ""
  states:
    initial:
      type: initial
      agent: agent.yml
      transitions:
        - to: final
    final:
      type: final
      output:
        result: "{{ context.result }}"
```

## Key Features

### Parallel Execution
```yaml
states:
  parallel_review:
    machine: [legal_review, tech_review, finance_review]
    transitions:
      - to: synthesize
```

### Dynamic Parallelism (Foreach)
```yaml
states:
  process_all:
    foreach: "{{ context.documents }}"
    as: doc
    machine: processor.yml
    transitions:
      - to: aggregate
```

### Retry with Backoff
```yaml
states:
  robust_call:
    agent: agent.yml
    execution:
      type: retry
      backoffs: [2, 8, 16, 35]
      jitter: 0.1
```

### Conditional Transitions
```yaml
states:
  check_result:
    agent: evaluator.yml
    transitions:
      - condition: "context.score >= 8"
        to: success
      - to: retry
```

### Error Handling
```yaml
states:
  risky_state:
    agent: agent.yml
    on_error: error_handler
```

### Persistence & Checkpointing
```yaml
persistence:
  enabled: true
  backend: local  # or memory
```

## Hooks

Extend with custom logic:

```typescript
class CustomHooks implements MachineHooks {
  async onStateEnter(state: string, context: any) {
    console.log(`Entering ${state}`);
    return context;
  }

  async onError(state: string, error: Error, context: any) {
    console.error(`Error in ${state}:`, error);
    return "recovery_state";
  }
}
```

## MCP Integration

```yaml
data:
  mcp:
    servers:
      filesystem:
        command: "npx"
        args: ["@modelcontextprotocol/server-filesystem", "/path/to/files"]
    tool_filter:
      allow: ["filesystem:*"]
```

## Examples

- **Helloworld**: Simple agent that builds "Hello World" one character at a time
- **Parallelism**: Machine arrays, foreach loops, and fire-and-forget patterns
- **Human-in-the-loop**: Custom hooks for interactive approval flows
- **Peering**: Parent-child machine communication with result backends

## API Reference

### FlatAgent
```typescript
class FlatAgent {
  constructor(config: AgentConfig | string);
  async call(input: Record<string, any>): Promise<{content: string, output: any}>;
}
```

### FlatMachine
```typescript
class FlatMachine {
  constructor(options: MachineOptions);
  async execute(input?: Record<string, any>): Promise<any>;
  async resume(executionId: string): Promise<any>;
}
```

### Execution Types
- `DefaultExecution`: Simple single execution
- `RetryExecution`: Retry with exponential backoff

### Persistence Backends
- `MemoryBackend`: In-memory storage
- `LocalFileBackend`: File-based with atomic writes

## Testing

```bash
npm test
npm run typecheck
```

## Building

```bash
npm run build
npm run dev  # watch mode
```

## License

MIT