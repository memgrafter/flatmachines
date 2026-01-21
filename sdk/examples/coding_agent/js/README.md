# Coding Agent (JavaScript)

An agentic coding assistant that plans, implements, and verifies code changes with human approval gates.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update the agent configs in `config/agents/`).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export CEREBRAS_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run the demo
./run.sh "Add input validation" --cwd /path/to/project
```

## Manual Setup

1. **Navigate into this project directory**:
   ```bash
   cd sdk/examples/coding_agent/js
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
   node dist/coding_agent/main.js "Add input validation" --cwd /path/to/project
   ```

## CLI Options

```bash
node dist/coding_agent/main.js "Add input validation" \
  --cwd /path/to/project \
  --max-iterations 5
```

## Safety Notes

- SEARCH/REPLACE diffs must match file content exactly.
- Paths are constrained to the provided working directory (and your current shell directory).
- If a SEARCH matches multiple locations, the change is rejected.

## File Structure

```
coding_agent/
├── config/
│   ├── machine.yml          # Coding agent state machine
│   └── agents/              # Planner/coder/reviewer agents
├── js/
│   ├── src/
│   │   └── coding_agent/
│   │       ├── hooks.ts      # Human review + safe apply hooks
│   │       └── main.ts       # CLI entry
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```
