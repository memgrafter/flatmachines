# FlatAgents Helloworld Example

A simple demonstration of FlatAgents that builds "Hello World" one character at a time using a looping state machine.

## What It Does

- Starts with an empty string
- Uses an agent to generate the next character needed
- Loops until "Hello World" is complete
- Demonstrates basic agent calls and state machine transitions

## Quick Start

```bash
# Setup and run the demo
./run.sh
```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local

# Run in development mode with tsx (for hot reloading)
./run.sh --dev

# Show help
./run.sh --help
```

## File Structure

```
helloworld/
├── config/
│   ├── machine.yml          # State machine configuration
│   └── next_char.yml        # Agent configuration
├── src/
│   └── helloworld/
│       └── main.ts          # Demo application
├── package.json             # Dependencies and scripts
├── run.sh                   # Setup and execution script
└── README.md                # This file
```

## How It Works

1. **State Machine**: `config/machine.yml` defines a loop that continues adding characters
2. **Agent**: `config/next_char.yml` is an LLM agent that returns just the next character
3. **Loop Logic**: The machine checks if the target string is reached, otherwise continues
4. **Input/Output**: Uses Jinja2 templating to pass context between states

## Expected Output

You'll see the state machine execute multiple times, once for each character, until it outputs:

```json
{
  "result": "Hello World"
}
```

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Other Examples](../)