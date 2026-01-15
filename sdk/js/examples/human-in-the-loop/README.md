# FlatAgents Human-in-the-Loop Example

Demonstrates how to integrate human approval and decision-making into FlatAgent workflows using custom hooks.

## What It Does

- Generates a task plan using an AI agent
- Pauses execution to show the plan to a human
- Waits for human approval (yes/no)
- Either proceeds with execution or regenerates the plan

## Features Demonstrated

### Custom Hooks
- `onStateEnter`: Intercept state transitions for human interaction
- Interactive input using Node.js readline
- Context modification based on human decisions

### Conditional Flow
- Approval gates that require human input
- Loop back for plan regeneration if rejected
- Continue execution if approved

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

⚠️ **Important**: This demo is interactive! You'll need to type "yes" or "no" when prompted.

## File Structure

```
human-in-the-loop/
├── config/
│   ├── task_agent.yml       # Agent that generates plans
│   └── machine.yml          # State machine with approval flow
├── src/
│   └── human-in-the-loop/
│       └── main.ts          # Demo application with custom hooks
├── package.json             # Dependencies and scripts
├── run.sh                   # Setup and execution script
└── README.md                # This file
```

## How It Works

### State Machine Flow
1. **generate_plan**: AI agent creates a task plan
2. **approval**: Human reviews and approves/rejects the plan
3. **execute**: If approved, executes the plan
4. **Loop**: If rejected, goes back to step 1

### Custom Hooks
```typescript
class HumanInLoopHooks implements MachineHooks {
  async onStateEnter(state: string, context: any) {
    if (state === 'approval') {
      const approved = await this.askQuestion('Approve this plan? (yes/no): ');
      context.approved = approved.toLowerCase().startsWith('y');
    }
    return context;
  }
}
```

### Conditional Transitions
```yaml
approval:
  transitions:
    - condition: "context.approved"
      to: execute
    - to: generate_plan
```

## Expected Interaction

You'll see:
1. A generated task plan displayed
2. A prompt asking for approval
3. Different results based on your choice

## Use Cases

- **Workflow Approval**: Manager approval for automation
- **Quality Control**: Human validation of AI outputs
- **Safety Gates**: Human oversight for critical operations
- **Interactive Workflows**: Step-by-step human guidance

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Hooks System](../README.md#hooks)
- [Other Examples](../)