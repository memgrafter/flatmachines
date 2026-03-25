# MDAP Demo (JavaScript)

JavaScript parity demo for MDAP Tower of Hanoi using the **same shared config** as Python:

- `config/machine.yml` (FlatMachine orchestration with `mdap_voting` execution)
- `config/hanoi.yml` (solver agent + MDAP metadata)
- `config/profiles.yml` (model profiles)

## Prerequisites

1. Node.js + npm
2. API key for your configured provider (see `config/profiles.yml`)

## Quick Start

```bash
chmod +x run.sh
./run.sh
```

For local SDK development:

```bash
./run.sh --local
```

## What this runs

`js/src/mdap/demo.ts` now mirrors Python golden behavior:

- Loads `config/machine.yml`
- Reads initial/goal peg defaults from `config/hanoi.yml` metadata
- Executes FlatMachine end-to-end
- Prints solved state, steps, and API/cost stats

## File Structure

```text
mdap/
├── config/
│   ├── machine.yml
│   ├── hanoi.yml
│   └── profiles.yml
├── js/
│   ├── src/mdap/
│   │   ├── demo.ts
│   │   └── mdap.ts
│   ├── package.json
│   ├── run.sh
│   └── README.md
└── python/
```
