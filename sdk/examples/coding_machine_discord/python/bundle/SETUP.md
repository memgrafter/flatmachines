# mk42 Setup

This install keeps runtime secrets/config outside the self-modifying workspace root.

## Paths

- mk42 home: `~/.agents/mk42`
- workspace root: `~/.agents/mk42/current`
- state db: `~/.agents/mk42/current/data/coding_machine_discord.sqlite`
- runtime conf: `~/.agents/mk42/conf`
- env file (default): `~/.agents/flatmachines/mk42.env`
- codex auth file (default): `~/.agents/flatmachines/auth.json`

`~/.agents/mk42/conf` controls external paths:

```bash
MK42_ENV_FILE=~/.agents/flatmachines/mk42.env
MK42_CODEX_AUTH_FILE=~/.agents/flatmachines/auth.json
```

## Discord env vars

Set in `MK42_ENV_FILE` (default `~/.agents/flatmachines/mk42.env`):

```bash
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
CODING_MACHINE_DISCORD_DEBUG=true
```

## Codex OAuth

mk42 uses `FLATAGENTS_CODEX_AUTH_FILE` (wired to `MK42_CODEX_AUTH_FILE`).

Expected file (default):

```bash
~/.agents/flatmachines/auth.json
```

If missing, authenticate and place/copy auth JSON there.

## Runtime packaging note

Installer uses the vendored wheelhouse in `current/wheels` and installs with `--offline --no-index`.
No PyPI access is required during install.

## Run

```bash
mk42 all
mk42 status
mk42 cli -p "summarize this workspace"
```
