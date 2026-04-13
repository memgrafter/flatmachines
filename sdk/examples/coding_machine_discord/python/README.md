# Coding Machine Discord Example (Python)

This example is **copied from `sdk/examples/coding_machine_cli/`** and adapted to run behind a Discord queue pipeline:

- same FlatMachine config (`config/machine.yml`, `config/agent.yml`)
- same tools (`read`, `bash`, `write`, `edit`)
- new Discord ingress/debounce/respond workers in Python

## Modes

### 1) Original CLI mode (from coding_machine_cli)

```bash
cd sdk/examples/coding_machine_discord/python
./run.sh --local cli
./run.sh --local cli -p "list all Python files"
./run.sh --local cli --standalone "summarize README.md"
```

### 2) Discord queue mode

Required env:

```bash
export DISCORD_BOT_TOKEN="..."
export DISCORD_CHANNEL_ID="123456789012345678"
```

Run all workers:

```bash
./run.sh --local all
```

By default, ingress **does not backfill old history** on first run. It bootstraps the cursor to the latest message.

If you want historical backfill on first run:

```bash
./run.sh --local all --backfill-on-first-run
```

Queue behavior defaults:

- `--debounce-seconds 15` (ingress burst coalescing)
- `--queue-wait-seconds 15` (human-loop wait baseline after each model turn)
- responder leases one batch at a time (`--responder-lease-limit 1`)

or individually:

```bash
./run.sh --local ingress
./run.sh --local debounce
./run.sh --local respond
```

Inspect queue state:

```bash
./run.sh --local status
```

## Discord queue flow

1. `ingress` polls channel messages and enqueues into `discord_incoming`
2. `debounce` batches bursts by conversation into `discord_debounced`
3. `respond` starts the copied coding machine and keeps it in the human-review loop
4. while the model is thinking, new user messages can queue
5. after each model turn, responder waits queue baseline and drains queued feedback into the same loop
6. replies are posted back to Discord turn-by-turn

Use `--echo-only` on `respond` or `all` to skip FlatMachine calls and just echo batches.

Ingress ignores empty-content events unless they include attachments, embeds, or components.

## Package layout

```
config/
  agent.yml
  machine.yml
  profiles.yml

python/src/tool_use_discord/
  tools.py            # copied from coding_machine_cli
  hooks.py            # copied from coding_machine_cli
  main.py             # CLI mode + Discord worker modes
  messages_backend.py # generic SQLite queue
  discord_ingress.py  # Discord poller -> queue
  debounce.py         # queue debounce worker
  responder.py        # queue consumer -> Discord responses
```
