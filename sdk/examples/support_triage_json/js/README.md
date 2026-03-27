# Support Triage JSON Demo (JavaScript)

Demonstrates FlatMachine + FlatAgent configs written in JSON, plus machine peering (launcher -> peer).

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/profiles.json`).

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
   cd sdk/examples/support_triage_json/js
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
   node dist/support_triage_json/main.js
   ```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

## JSON Config Note

This demo loads `config/machine.json` (and related JSON agent/machine configs) rather than YAML.

## File Structure

```
support_triage_json/
├── config/
│   ├── machine.json         # State machine configuration (JSON)
│   ├── profiles.json        # Model profiles (JSON)
│   ├── triage_agent.json    # Triage agent
│   └── response_machine.json # Nested response machine
├── js/
│   ├── src/
│   │   └── support_triage_json/
│   │       └── main.ts       # Demo application
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

## How It Works

1. The **triage agent** categorizes the ticket and decides if a response is needed.
2. If a response is needed, the machine delegates to a **nested response machine**.
3. The final state returns the triage summary plus the drafted response.
