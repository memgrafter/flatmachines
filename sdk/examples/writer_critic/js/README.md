# Writer-Critic Demo (JavaScript)

A multi-agent loop that iteratively improves a tagline using a writer and critic agent.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/writer.yml` and `config/critic.yml`).

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
   cd sdk/examples/writer_critic/js
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
   node dist/writer_critic/main.js
   ```

## CLI Options

```bash
node dist/writer_critic/main.js \
  --product "a CLI tool for AI agents" \
  --max-rounds 4 \
  --target-score 8
```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local
```

## File Structure

```
writer_critic/
├── config/
│   ├── machine.yml          # State machine configuration
│   ├── writer.yml           # Writer agent
│   └── critic.yml           # Critic agent
├── js/
│   ├── src/
│   │   └── writer_critic/
│   │       └── main.ts       # Demo application
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

## How It Works

1. **Writer** generates taglines for the product.
2. **Critic** scores and provides feedback.
3. The machine loops until the target score is reached or max rounds is hit.
