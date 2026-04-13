# tool_use_discord

Discord-facing wrapper around a coding-machine workflow.

This project lets you run a coding assistant in two ways:

- **CLI mode** for direct local prompts
- **Discord queue mode** with three workers (`ingress`, `debounce`, `respond`)

The README is intentionally operational (how to run/use it), not a code tour.

---

## What you need

- Python **3.10+**
- `uv` installed
- A model provider configured for `flatagents`/`litellm` (for real responses)
- For Discord mode:
  - `DISCORD_BOT_TOKEN`
  - `DISCORD_CHANNEL_ID`

---

## Quick start

From this directory:

```bash
./run.sh --local cli -p "summarize this repository"
```

Run tests:

```bash
./test.sh -q
```

`run.sh` will:

1. create `.venv` if needed
2. install dependencies
3. run `tool_use_discord.main`

Use `--local` to install `flatagents/flatmachines` from local SDK paths under your repo root.

---

## Discord mode (end-to-end)

Set env vars:

```bash
export DISCORD_BOT_TOKEN="..."
export DISCORD_CHANNEL_ID="123456789012345678"
```

Run all workers together:

```bash
./run.sh --local all
```

This starts:

- **ingress**: polls Discord and enqueues incoming messages
- **debounce**: groups bursts into batches
- **respond**: consumes batches and posts assistant replies

---

## Worker commands

Run individually when debugging:

```bash
./run.sh --local ingress
./run.sh --local debounce
./run.sh --local respond
./run.sh --local status
```

---

## CLI commands

Examples:

```bash
./run.sh --local cli
./run.sh --local cli -p "list python files"
./run.sh --local cli --standalone "explain run.sh"
```

---

## Important flags

Common queue tuning flags:

- `--debounce-seconds <n>`: message coalescing window
- `--queue-wait-seconds <n>`: responder wait baseline between turns
- `--responder-lease-limit <n>`: batches leased per responder iteration
- `--backfill-on-first-run`: ingest historical messages on initial startup

Safe testing flag:

- `--echo-only` (with `respond` or `all`): skips model calls and echoes batches

Debug logging:

```bash
CODING_MACHINE_DISCORD_DEBUG=true ./run.sh --local all
# or
./run.sh --local --debug all
```

---

## Runtime behavior notes

- By default, first ingress run **does not backfill full channel history**.
- Empty-content Discord events are ignored unless they include useful payloads (attachments/embeds/components).
- In responder flow, replies may be posted turn-by-turn during human-review loop handling.

---

## Troubleshooting

### `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID` missing
Set both env vars before `ingress`/`all`/`respond` in Discord mode.

### Local SDK install fails with `--local`
`run.sh` expects this repo layout at project root:

- `sdk/python/flatagents`
- `sdk/python/flatmachines`

If unavailable, run without `--local` to install from PyPI.

### No responses appearing

1. Run `./run.sh --local status`
2. Enable debug logs
3. Try `--echo-only` to verify queue plumbing independently from model/provider setup

---

## Project entrypoint

Installed script:

- `tool-use-discord` → `tool_use_discord.main:main`

Primary package:

- `src/tool_use_discord`
