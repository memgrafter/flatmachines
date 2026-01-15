# FlatAgents Peering Example

Demonstrates machine-to-machine communication, persistence, and checkpointing in FlatAgents for distributed workflows.

## Features Demonstrated

### 1. Machine Peering
- **Orchestrator**: Launches worker nodes without waiting
- **Worker Nodes**: Process tasks independently
- **Communication**: Results shared via result backend

### 2. Persistence & Checkpointing
- **Memory Backend**: In-memory checkpoint storage
- **Resume Capability**: Can resume from any checkpoint
- **State Management**: Full context preservation

### 3. Fire-and-Forget Pattern
- Launch machines without blocking execution
- Workers run independently in background
- Results available via polling or callbacks

## Quick Start

```bash
# Setup and run the demo
./run.sh
```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local

# Run in development mode with tsx
./run.sh --dev

# Show help
./run.sh --help
```

## File Structure

```
peering/
├── config/
│   ├── orchestrator.yml      # Launches worker nodes
│   └── worker_node.yml      # Processes tasks independently
├── src/
│   └── peering/
│       └── main.ts          # Demo application
├── package.json             # Dependencies and scripts
├── run.sh                   # Setup and execution script
└── README.md                # This file
```

## How It Works

### Orchestrator Pattern
```yaml
states:
  initial:
    launch: [worker_node.yml]  # Fire-and-forget
    launch_input:
      tasks: "{{ context.tasks }}"
    transitions:
      - to: wait_for_results
```

### Worker Node Processing
```yaml
states:
  process_tasks:
    foreach: "{{ input.tasks }}"
    as: task
    agent: worker.yml
    output_to_context:
      results: "{{ output }}"
```

### Persistence Setup
```yaml
persistence:
  enabled: true
  backend: memory
```

## Expected Output

You'll see:
1. **Orchestrator Launch**: Tasks delegated to worker nodes
2. **Worker Processing**: Independent task execution
3. **Checkpoint Demo**: Execution ID for potential resume
4. **Distributed Results**: Processed data from multiple nodes

## Use Cases

- **Distributed Processing**: Scale across multiple machines
- **Background Jobs**: Long-running tasks without blocking
- **Fault Tolerance**: Resume from checkpoints on failure
- **Workload Distribution**: Balance tasks across workers

## Advanced Features

### Checkpoint/Resume
```typescript
// Save execution ID for later resume
const executionId = machine.executionId;

// Resume from checkpoint later
const resumedMachine = new FlatMachine({...});
await resumedMachine.resume(executionId);
```

### Result Backend
```typescript
// Shared result storage between machines
const resultBackend = inMemoryResultBackend;
await resultBackend.write(`flatagents://${executionId}/result`, data);
```

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Persistence](../README.md#persistence--checkpointing)
- [Other Examples](../)