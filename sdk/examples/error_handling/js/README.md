# FlatAgents Error Handling Demo

Demonstrates FlatMachine error handling with `on_error` and retry logic.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/worker.yml`).

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
   cd sdk/examples/error_handling/js
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
   node dist/error_handling/main.js
   ```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local
```

## File Structure

```
error_handling/
├── config/
│   ├── machine.yml          # State machine configuration
│   ├── worker.yml           # Worker agent (intentionally broken ref in machine)
│   └── cleanup.yml          # Cleanup agent for error summary
├── js/
│   ├── src/
│   │   └── error_handling/
│   │       └── main.ts       # Demo application
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

## How It Works

1. The machine attempts to run a missing agent (`broken`) and triggers `on_error`.
2. The cleanup agent summarizes the error with retry backoff.
3. The final state returns `success: false` with error summary and type.

## Expected Output

You'll see a failure result with a concise summary, e.g.:

```json
{
  "success": false,
  "summary": "...",
  "error_type": "..."
}
```
