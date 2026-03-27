# Multi-Chapter Story Writer (JavaScript)

Demonstrates machine peering, checkpoint/persistence, and per-chapter refinement loops.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/profiles.yml`).

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
   cd sdk/examples/story_writer/js
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
   node dist/story_writer/main.js
   ```

## CLI Options

```bash
node dist/story_writer/main.js \
  --genre "science fiction" \
  --premise "A librarian discovers books can transport readers into their stories" \
  --num-chapters 2
```

## Resume & Persistence

This machine has persistence enabled (`config/machine.yml`). You can resume a run by passing the execution ID:

```bash
node dist/story_writer/main.js --resume <execution-id>
```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

## File Structure

```
story_writer/
├── config/
│   ├── machine.yml          # Main machine + persistence settings
│   ├── chapter_machine.yml  # Per-chapter peer machine
│   └── *.yml                # Agents/extractors
├── js/
│   ├── src/
│   │   └── story_writer/
│   │       └── main.ts       # Demo application
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
├── output/                   # Generated stories
└── python/
```

## How It Works

1. The **outliner** builds a structured outline with chapter summaries.
2. Each chapter is written by a **peer machine** that drafts, critiques, and revises.
3. The final output is saved as a Markdown file in `output/`.
