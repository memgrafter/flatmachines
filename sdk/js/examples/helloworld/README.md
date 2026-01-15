# FlatAgent HelloWorld Demo

A simple "Hello, World!" project that demonstrates how to use the FlatAgents TypeScript SDK.

The demo involves an agent that attempts to build the string "Hello, World!" by querying an LLM one character at a time. It showcases:
- Using a FlatMachine from YAML configuration
- Looping until a completion condition is met
- Basic execution output handling

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/agent.yml` for another provider).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export CEREBRAS_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run the demo
./run.sh
```

## Manual Setup

1. **Navigate into this project directory**:
   ```bash
   cd sdk/js/examples/helloworld
   ```
2. **Install dependencies**:
   ```bash
   npm install
   ```
3. **Set your LLM API key**:
   ```bash
   export CEREBRAS_API_KEY="your-api-key-here"
   ```
4. **Build and run**:
   ```bash
   npm run build
   node dist/helloworld/main.js
   ```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local
```

## File Structure

```
helloworld/
├── config/
│   ├── machine.yml          # State machine configuration
│   └── agent.yml            # Agent configuration
├── src/
│   └── helloworld/
│       └── main.ts          # Demo application
├── package.json             # Dependencies and scripts
├── tsconfig.json            # TypeScript config
├── run.sh                   # Setup and execution script
├── .gitignore
└── README.md                # This file
```

## How It Works

1. **State Machine**: `config/machine.yml` defines a loop that continues adding characters.
2. **Agent**: `config/agent.yml` is an LLM agent that returns just the next character.
3. **Loop Logic**: The machine checks if the target string is reached, otherwise continues.
4. **Input/Output**: Uses Jinja2 templating to pass context between states.

## Expected Output

You'll see the state machine execute multiple times, once for each character, until it outputs:

```json
{
  "result": "Hello, World!",
  "success": true
}
```

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Other Examples](../)
