# mk42 Setup

This install keeps runtime secrets/config outside the self-modifying workspace root.

## Paths

- mk42 home: `~/.agents/mk42`
- workspace root: `~/.agents/mk42/current`
- state db: `~/.agents/mk42/current/data/coding_machine_discord.sqlite`
- runtime conf: `~/.agents/mk42/conf`
- env file (default): `~/.agents/flatmachines/mk42.env`
- codex auth file (default): `~/.agents/flatmachines/auth.json`

`~/.agents/mk42/conf` controls external paths and chat rollover settings:

```bash
MK42_ENV_FILE=~/.agents/flatmachines/mk42.env
MK42_CODEX_AUTH_FILE=~/.agents/flatmachines/auth.json
TOOL_USE_DISCORD_HISTORY_DIR=~/.agents/flatmachines/history/mk42
MK42_CHAT_ROLLOVER_TOKEN_LIMIT=50000
```

## Discord env vars

Set in `MK42_ENV_FILE` (default `~/.agents/flatmachines/mk42.env`):

```bash
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
CODING_MACHINE_DISCORD_DEBUG=true
```

## Discord admins (stored in DB)

At least 1 Discord user ID (for admin) is required. Admin IDs are stored in:

- `~/.agents/mk42/current/data/coding_machine_discord.sqlite`
- table: `discord_users` (`is_admin = 1`)

`mk42 setup` prompts for `DISCORD_ADMIN_USER_IDS` (comma/space separated IDs or `<@...>` mentions).

Interactive helper:

```bash
mk42 setup
```

(Individual command still available: `mk42 setup discord`)

## Codex OAuth

mk42 uses `FLATAGENTS_CODEX_AUTH_FILE` (wired to `MK42_CODEX_AUTH_FILE`).

Expected file (default):

```bash
~/.agents/flatmachines/auth.json
```

If missing, run:

```bash
mk42 login codex
```

This runs Codex OAuth and copies auth JSON into the configured auth path.

## Runtime packaging note

Installer uses the vendored wheelhouse in `current/wheels` and installs with `--offline --no-index`.
No PyPI access is required during install.

## Run

```bash
mk42 setup
mk42          # same as: mk42 all
mk42 status
mk42 cli -p "summarize this workspace"
```

Individual setup commands (optional):

```bash
mk42 login codex
mk42 setup discord
mk42 --skip-setup all
```
