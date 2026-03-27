# FlatMachine HelloWorld Demo

A simple "Hello, World!" project that demonstrates how to use the FlatMachines TypeScript SDK.

The demo involves an agent that attempts to build the string "Hello, World!" by querying an LLM one character at a time. It showcases:
- Using a FlatMachine from YAML configuration
- Hooks via `HooksRegistry` (config-referenced by name)
- Looping until a completion condition is met
- Structured logging with `setupLogging` / `getLogger`
- Basic execution output handling

## Prerequisites

1. **Node.js & npm**: Node.js 18+ and npm installed.
2. **LLM API Key**: This demo uses OpenAI by default, so set `OPENAI_API_KEY` (or update `config/agent.yml` and `config/profiles.yml` for another provider).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export OPENAI_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run the demo
./run.sh
```

## Manual Setup

1. **Navigate into this project directory**:
   ```bash
   cd sdk/examples/helloworld/js
   ```
2. **Install dependencies**:
   ```bash
   npm install
   ```
3. **Set your LLM API key**:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```
4. **Build and run**:
   ```bash
   npm run build
   node dist/helloworld/main.js
   ```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

## File Structure

```
helloworld/
├── config/
│   ├── machine.yml          # State machine configuration
│   ├── agent.yml            # Agent configuration
│   └── profiles.yml         # Model profiles
├── js/
│   ├── src/
│   │   └── helloworld/
│   │       └── main.ts      # Demo application
│   ├── package.json         # Dependencies and scripts
│   ├── tsconfig.json        # TypeScript config
│   ├── run.sh               # Setup and execution script
│   └── README.md            # This file
└── python/                  # Python equivalent
```

## How It Works

1. **State Machine**: `config/machine.yml` defines a loop that continues adding characters.
2. **Agent**: `config/agent.yml` is an LLM agent that returns just the next character.
3. **Profiles**: `config/profiles.yml` defines reusable model configurations.
4. **Hooks**: `HelloWorldHooks` is registered via `HooksRegistry` under `"hello-world-hooks"` — the same name referenced in `machine.yml`.
5. **Loop Logic**: The machine checks if the target string is reached, otherwise continues.
6. **Input/Output**: Uses Jinja2/Nunjucks templating to pass context between states.

## Expected Output

You'll see the state machine execute multiple times, once for each character, until it outputs:

```json
{
  "result": "Hello, World!",
  "success": true
}
```

## Learn More

- [FlatAgents Documentation](../../../js/packages/flatagents/README.md)
- [FlatMachines Documentation](../../../js/packages/flatmachines/README.md)
- [Other Examples](../)
