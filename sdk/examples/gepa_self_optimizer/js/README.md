# GEPA Self-Optimizer (JavaScript)

Optimizes a GEPA judge using @memgrafter/flatagents for all LLM calls.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/agents/*.yml`).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export CEREBRAS_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run full pipeline
./run.sh run
```

## Commands

```bash
# Full pipeline
node dist/gepa_self_optimizer/main.js run --num-examples 100 --budget 50

# Generate evaluation data
node dist/gepa_self_optimizer/main.js generate-data --num-examples 50 --correct-ratio 0.3

# Evaluate current judge
node dist/gepa_self_optimizer/main.js evaluate --judge config/agents/judge.yml --data data/evaluation_set.json

# Run optimization only
node dist/gepa_self_optimizer/main.js optimize --budget 50 --pareto-size 30 --minibatch-size 5

# Silence progress logging
node dist/gepa_self_optimizer/main.js run --quiet
```

## File Structure

```
gepa_self_optimizer/
├── config/
│   ├── profiles.yml
│   ├── settings.yml
│   └── agents/
├── data/
│   └── evaluation_set.json
├── output/
│   ├── optimized_judge.yml
│   ├── optimization_log.json
│   └── summary.json
├── js/
│   ├── src/
│   │   └── gepa_self_optimizer/
│   │       ├── data_generator.ts
│   │       ├── evaluator.ts
│   │       ├── optimizer.ts
│   │       ├── prompt_evolver.ts
│   │       ├── utils.ts
│   │       └── main.ts
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```
