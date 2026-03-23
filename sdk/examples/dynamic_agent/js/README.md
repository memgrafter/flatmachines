# Dynamic Agent (JavaScript)

Demonstrates On-The-Fly (OTF) agent generation with supervisor validation and human-in-the-loop review.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses OpenAI profile defaults, so set `OPENAI_API_KEY` (or update `config/profiles.yml`).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export OPENAI_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run the demo (interactive prompts)
./run.sh
```

## Manual Setup

1. **Navigate into this project directory**:
   ```bash
   cd sdk/examples/dynamic_agent/js
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
   node dist/dynamic_agent/main.js
   ```

## CLI Options

```bash
node dist/dynamic_agent/main.js \
  "Write a haiku about the beauty of mountain sunrises" \
  --style "melancholic"
```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

## File Structure

```
dynamic_agent/
├── config/
│   ├── machine.yml          # Dynamic agent machine
│   └── *.yml                # Generator/supervisor agents
├── js/
│   ├── src/
│   │   └── dynamic_agent/
│   │       ├── hooks.ts      # Human review + OTF execution actions
│   │       └── main.ts       # Demo application
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

## How It Works

1. A **generator agent** proposes a new agent spec.
2. A **supervisor agent** validates the spec before execution.
3. You review/approve or deny the generated agent.
4. The approved agent is executed on the original task.
