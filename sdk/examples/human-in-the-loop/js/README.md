# FlatAgents Human-in-the-Loop Example

Demonstrates how to integrate human approval and feedback into FlatAgent workflows using custom hooks.

## What It Does

- Generates a short draft using an AI agent
- Pauses execution to show the draft to a human
- Waits for approval or feedback
- Either finishes or revises the draft

## Features Demonstrated

### Custom Hooks
- `onStateEnter`: Intercept the review state for human interaction
- Interactive input using Node.js readline
- Context modification based on human approval or feedback

### Conditional Flow
- Approval gates that require human input
- Loop back for draft revision if feedback provided
- Continue execution if approved

## Quick Start

```bash
# Setup and run the demo
./run.sh
```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

⚠️ **Important**: This demo is interactive! You'll need to approve or provide feedback when prompted.

## File Structure

```
human-in-the-loop/
├── config/
│   ├── drafter.yml          # Agent that generates drafts
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
1. **generate_draft**: AI agent creates a draft
2. **await_human_review**: Human approves or provides feedback
3. **done**: If approved, returns the draft
4. **Loop**: If feedback provided, the agent revises

### Custom Hooks
```typescript
class HumanInLoopHooks implements MachineHooks {
  async onStateEnter(state: string, context: any) {
    if (state === 'await_human_review') {
      const approved = await this.askQuestion('Approve? (y/yes or feedback): ');
      context.human_approved = approved.toLowerCase().startsWith('y');
    }
    return context;
  }
}
```

### Conditional Transitions
```yaml
await_human_review:
  transitions:
    - condition: "context.human_approved == true"
      to: done
    - to: generate_draft
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
