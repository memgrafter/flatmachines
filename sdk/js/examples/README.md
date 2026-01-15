# FlatAgents Examples

This directory contains demonstration examples of the FlatAgents TypeScript SDK in action. Each example is self-contained with its own dependencies and can be run independently.

## Available Examples

### 🚀 [helloworld/](./helloworld)
A simple demonstration that builds "Hello World" one character at a time using a looping state machine.

**Learn**: Basic agent calls, state machine transitions, loops

```bash
cd helloworld && ./run.sh
```

### ⚡ [parallelism/](./parallelism)
Demonstrates parallel execution capabilities including machine arrays and foreach loops.

**Learn**: Parallel processing, dynamic scaling, performance patterns

```bash
cd parallelism && ./run.sh
```

### 👥 [human-in-the-loop/](./human-in-the-loop)
Shows how to integrate human approval and decision-making using custom hooks.

**Learn**: Custom hooks, interactive workflows, approval gates

**Warning**: Interactive demo requiring user input!

```bash
cd human-in-the-loop && ./run.sh
```

### 🌐 [peering/](./peering)
Demonstrates machine-to-machine communication, persistence, and distributed processing.

**Learn**: Machine peering, checkpointing, fire-and-forget patterns

```bash
cd peering && ./run.sh
```

## Running Examples

### Quick Start
Each example includes a `run.sh` script that handles all setup:

```bash
cd example-name
./run.sh
```

### Development Mode
For development with hot reloading:

```bash
cd example-name
./run.sh --dev
```

### Local Development
To test with the local flatagents source:

```bash
cd example-name
./run.sh --local
```

## Prerequisites

All examples require:
- **Node.js** (version 16 or higher)
- **npm** (comes with Node.js)

The `run.sh` script will automatically check for these requirements.

## Example Structure

Each example follows this consistent structure:

```
example-name/
├── config/
│   ├── machine.yml          # State machine(s)
│   └── agent.yml            # Agent configuration(s)
├── src/
│   └── example-name/
│       └── main.ts          # Demo application
├── package.json             # Dependencies
├── tsconfig.json           # TypeScript config
├── run.sh                   # Setup & execution script
└── README.md                # Example documentation
```

## Environment Setup

Each example is completely isolated with its own:

- **Dependencies**: Managed via npm
- **TypeScript**: Uses local tsconfig.json
- **Node Modules**: Install in example directory
- **Build Output**: Local dist/ directory

## Configuration Files

### Machines (`machine.yml`)
Define state machines with:
- States and transitions
- Conditional logic
- Error handling
- Persistence settings

### Agents (`agent.yml`)
Configure LLM agents with:
- Model selection
- System/user prompts
- Output schemas
- MCP tool integration

## Getting Help

Each example supports:

```bash
cd example-name
./run.sh --help
```

## Common Issues

**"flatagents not found"**: Run with `--local` flag to build from source.

**TypeScript errors**: Ensure all dependencies installed by running `./run.sh`.

**Permission denied**: Make run.sh executable: `chmod +x run.sh`.

## Next Steps

1. Start with **helloworld** to understand basic concepts
2. Try **parallelism** to see scaling capabilities
3. Explore **human-in-the-loop** for interactive workflows
4. Study **peering** for advanced patterns

For complete API documentation, see the [main README](../README.md).