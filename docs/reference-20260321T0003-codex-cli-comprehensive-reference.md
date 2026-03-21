# Codex CLI Comprehensive Reference for Orchestration

> Tested against codex-cli **0.116.0** on 2026-03-21.
> Binary: `codex` (installed via fnm/npm)
> Target model: `gpt-5.3-codex` (reasoning effort: `high`)

## Overview

Codex CLI is OpenAI's terminal-based coding agent. It runs an internal agentic
loop with shell execution (`exec_command`), file patching (`apply_patch`),
web search, MCP tools, image generation, and multi-agent collaboration
(`spawnAgent`, `sendInput`, `resumeAgent`, `wait`, `closeAgent`).

It manages its own conversation history, tool execution, sandbox enforcement,
and context compaction. Sessions are persisted locally as JSONL rollout files
with a SQLite state database for indexing.

For FlatMachines orchestration, the CLI is driven in **exec mode**
(`codex exec`) with `--json` for structured JSONL output, session management
for cache preservation via `resume`/`fork`, and streaming events for
real-time observability.

---

## Architecture

### Storage Layout

```
~/.codex/
  auth.json                    # OAuth/API key credentials
  config.toml                  # Global configuration
  version.json                 # Latest version tracking
  models_cache.json            # Model definitions cache
  state_5.sqlite               # Session index, jobs, tools
  logs_1.sqlite                # Debug/telemetry logs
  sessions/
    2026/03/20/
      rollout-{ts}-{uuid}.jsonl  # Full session replay logs
  memories/                    # Agent memories (experimental)
  skills/                      # Installed skills
  shell_snapshots/             # Shell environment snapshots
```

### Key Components

| Component | Purpose |
|-----------|---------|
| `state_5.sqlite` | Session index (`threads` table), agent jobs, dynamic tools |
| `rollout-*.jsonl` | Full event replay per session (two formats: internal & exec) |
| `auth.json` | ChatGPT OAuth tokens or API key (`auth_mode: chatgpt`) |
| `config.toml` | Personality, project trust, feature flags, model migrations |
| `models_cache.json` | Cached model definitions from OpenAI (12 models, slugs, context windows) |

### Thread Database Schema

```sql
CREATE TABLE threads (
    id TEXT PRIMARY KEY,              -- UUID
    rollout_path TEXT NOT NULL,       -- Path to JSONL rollout file
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,             -- "exec", "cli", "vscode", etc.
    model_provider TEXT NOT NULL,     -- "openai"
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,              -- First user message (auto)
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    reasoning_effort TEXT,
    git_sha TEXT,
    git_branch TEXT,
    git_origin_url TEXT,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT ''
);
```

---

## Execution Modes

### Interactive TUI (`codex [PROMPT]`)

Full terminal UI with alt-screen. Not suitable for automation.

### Non-Interactive Exec (`codex exec`)

Primary automation interface. Runs a prompt, executes tools, exits.

```bash
codex exec --json --model gpt-5.3-codex --full-auto "Your prompt here"
```

**Key flags for exec mode:**

| Flag | Purpose |
|------|---------|
| `--json` | Emit structured JSONL events to stdout |
| `--full-auto` | Alias for `-a on-request --sandbox workspace-write` |
| `-a never` | Never ask for approval (fully autonomous) |
| `--sandbox <mode>` | `read-only`, `workspace-write`, `danger-full-access` |
| `-m, --model <model>` | Model slug (e.g., `gpt-5.3-codex`) |
| `-o, --output-last-message <file>` | Write final agent message to file |
| `--output-schema <file>` | JSON Schema for structured output (requires `additionalProperties: false`) |
| `--ephemeral` | Don't persist session to disk |
| `--skip-git-repo-check` | Allow running outside a git repo |
| `-C, --cd <dir>` | Set working directory |
| `--add-dir <dir>` | Additional writable directories |
| `--color never` | Disable ANSI output (plain text mode) |
| `-c <key=value>` | Override config.toml values (TOML syntax) |
| `-i, --image <file>` | Attach image(s) to prompt |
| `--search` | Enable web search tool |
| `-p, --profile <name>` | Use named config profile |
| `--progress-cursor` | Force cursor-based progress updates |

**Prompt sources:**
- Positional argument: `codex exec --json "prompt"`
- stdin: `echo "prompt" | codex exec --json -`
- Both: positional takes precedence over stdin

### Code Review (`codex exec review` / `codex review`)

Specialized code review mode:

```bash
codex exec review --json --full-auto --uncommitted
codex exec review --json --full-auto --base main
codex exec review --json --full-auto --commit abc123
```

| Flag | Purpose |
|------|---------|
| `--uncommitted` | Review staged, unstaged, and untracked changes |
| `--base <branch>` | Review changes against base branch |
| `--commit <sha>` | Review specific commit |
| `--title <title>` | Optional commit title for review summary |

---

## Session Management

### Thread IDs

Every session gets a UUID thread ID. This is the primary handle for resume/fork.

```jsonl
{"type":"thread.started","thread_id":"019d0f31-2075-7e11-a58a-075ecdff2d9a"}
```

### Resume (`codex exec resume`)

Continue a previous session with full conversation history and API cache:

```bash
# By thread ID
codex exec resume --json --full-auto "<thread-id>" "Follow-up prompt"

# Most recent session
codex exec resume --json --full-auto --last "Follow-up prompt"
```

Resume preserves the thread ID and entire conversation prefix.
The OpenAI Responses API provides prefix-based prompt caching:
cached tokens show in `turn.completed` usage as `cached_input_tokens`.

**Observed caching behavior:**
- First call: 8,960 cached tokens (system/developer prompt prefix)
- Resume call: 17,920-21,248 cached tokens (system + prior conversation)
- Cache hit grows with conversation length

### Fork (`codex fork`)

Create a new session branching from an existing one. The original session
is untouched. Interactive only (no `codex exec fork`). For exec-mode forking,
use `codex exec resume` which creates a continuation (same thread ID).

### Session Querying

Sessions are indexed in `state_5.sqlite`:

```sql
SELECT id, cwd, model, source, title, created_at
FROM threads
ORDER BY created_at DESC LIMIT 10;
```

The `--all` flag on resume/fork disables CWD filtering to show all sessions.

---

## JSONL Event Protocol (exec `--json`)

The `--json` flag produces a clean, machine-parseable JSONL stream on stdout.
Each line is one JSON object with a `type` field.

### Event Types

| Event | Fields | When |
|-------|--------|------|
| `thread.started` | `thread_id` | Session begins |
| `turn.started` | | Turn begins |
| `item.started` | `item: {id, type, ...}` | Tool execution begins |
| `item.completed` | `item: {id, type, ...}` | Tool execution or message completes |
| `turn.completed` | `usage: {input_tokens, cached_input_tokens, output_tokens}` | Turn ends successfully |
| `turn.failed` | `error: {message}` | Turn ends with error |
| `error` | `message` | Error during processing |

### Item Types

| Type | Fields | Description |
|------|--------|-------------|
| `agent_message` | `text` | Agent text output (commentary or final answer) |
| `command_execution` | `command`, `aggregated_output`, `exit_code`, `status` | Shell command execution |

**Item lifecycle:**
- `item.started` with `status: "in_progress"` and empty `aggregated_output`
- `item.completed` with `status: "completed"`, populated output and exit code

### Example: Simple prompt

```jsonl
{"type":"thread.started","thread_id":"019d0f31-2075-7e11-a58a-075ecdff2d9a"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"PINEAPPLE"}}
{"type":"turn.completed","usage":{"input_tokens":12316,"cached_input_tokens":8960,"output_tokens":19}}
```

### Example: Tool-using prompt

```jsonl
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"I'll inspect the directory..."}}
{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"/bin/bash -lc 'ls -la'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"/bin/bash -lc 'ls -la'","aggregated_output":"total 132\n...","exit_code":0,"status":"completed"}}
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"Found 16 files..."}}
{"type":"turn.completed","usage":{"input_tokens":37728,"cached_input_tokens":30336,"output_tokens":368}}
```

### Example: Error

```jsonl
{"type":"thread.started","thread_id":"..."}
{"type":"turn.started"}
{"type":"error","message":"{\"type\":\"error\",\"error\":{...},\"status\":400}"}
{"type":"turn.failed","error":{"message":"{...}"}}
```

---

## Internal Rollout Format (Session Files)

Session JSONL files (`~/.codex/sessions/`) use a richer format with the
full Responses API payload. These are NOT the same as `--json` exec output.

### Internal Event Types

| Type | Purpose |
|------|---------|
| `session_meta` | Session metadata: id, cwd, model, git info, base instructions |
| `event_msg` | Wrapper for: `task_started`, `task_complete`, `user_message`, `agent_message`, `token_count` |
| `response_item` | Full Responses API items: `message`, `reasoning`, `function_call`, `function_call_output` |
| `turn_context` | Turn configuration: model, sandbox, approval, personality, truncation |

### Token Usage in Internal Format

```json
{
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": {
        "input_tokens": 13697,
        "cached_input_tokens": 8960,
        "output_tokens": 494,
        "reasoning_output_tokens": 232,
        "total_tokens": 14191
      }
    },
    "rate_limits": {
      "limit_id": "codex",
      "primary": { "used_percent": 0.0, "window_minutes": 300 },
      "secondary": { "used_percent": 0.0, "window_minutes": 10080 },
      "plan_type": "team"
    }
  }
}
```

---

## Configuration

### config.toml

```toml
personality = "pragmatic"         # none | friendly | pragmatic

[projects."/path/to/repo"]
trust_level = "trusted"

[notice.model_migrations]
"gpt-5.3-codex" = "gpt-5.4"     # Dismiss upgrade notices
```

### Runtime Config Overrides (`-c`)

```bash
codex exec -c model="gpt-5.3-codex" -c reasoning_effort="high" ...
codex exec -c 'sandbox_permissions=["disk-full-read-access"]' ...
codex exec -c shell_environment_policy.inherit=all ...
```

### Feature Flags

```bash
codex features list                    # Show all flags
codex --enable fast_mode ...           # Enable per-invocation
codex --disable multi_agent ...        # Disable per-invocation
codex features enable <flag>           # Persist in config.toml
```

**Notable stable flags:** `fast_mode`, `multi_agent`, `personality`,
`shell_snapshot`, `shell_tool`, `enable_request_compression`, `unified_exec`

**Notable experimental flags:** `guardian_approval`, `js_repl`,
`prevent_idle_sleep`, `tui_app_server`

### Sandbox Policies

| Policy | Behavior |
|--------|----------|
| `read-only` | Can read files, no writes, no network |
| `workspace-write` | Can write to CWD and TMPDIR, network restricted |
| `danger-full-access` | Unrestricted (no sandboxing) |

The `--full-auto` flag is equivalent to `-a on-request --sandbox workspace-write`.

For automation, use either:
- `--full-auto` (sandbox + model decides when to ask)
- `-a never --sandbox workspace-write` (never ask, sandboxed writes)
- `--dangerously-bypass-approvals-and-sandbox` (no sandbox, no approvals)

---

## Structured Output

Use `--output-schema <file>` with a JSON Schema:

```json
{
  "type": "object",
  "properties": {
    "answer": { "type": "string" },
    "confidence": { "type": "number" }
  },
  "required": ["answer", "confidence"],
  "additionalProperties": false
}
```

**Requirements:**
- `additionalProperties: false` is MANDATORY at every object level
- Schema is passed to the Responses API `text.format.schema`
- Output appears as JSON string in the final `agent_message` text

```bash
codex exec --json --full-auto --output-schema schema.json "Question"
# item.completed -> item.text = '{"answer":"Paris.","confidence":1.0}'
```

---

## Authentication

### Auth Modes

1. **ChatGPT OAuth** (`auth_mode: chatgpt`): Device flow via `codex login`
2. **API Key**: `codex login --with-api-key` (reads from stdin)
3. **Environment**: `OPENAI_API_KEY` env var

Auth stored in `~/.codex/auth.json`:
```json
{
  "auth_mode": "chatgpt",
  "OPENAI_API_KEY": "...",
  "tokens": { "access_token": "...", "refresh_token": "..." },
  "last_refresh": "..."
}
```

---

## MCP Server Integration

### As MCP Client

```bash
codex mcp add my-server -- /path/to/server
codex mcp add my-http-server --url https://mcp.example.com
codex mcp list
codex mcp remove my-server
```

MCP tools become available to the agent during sessions.

### As MCP Server

```bash
codex mcp-server     # Starts Codex as an MCP server over stdio
```

This exposes Codex capabilities to other MCP clients.

---

## App Server Protocol

Codex has a full JSON-RPC app server protocol (used by VS Code extension):

```bash
codex app-server --listen ws://127.0.0.1:8080
codex app-server --listen stdio://
```

### Key Protocol Methods

| Method | Purpose |
|--------|---------|
| `thread/start` | Start a new thread with prompt, config, sandbox |
| `thread/resume` | Resume thread by ID, path, or history |
| `thread/fork` | Fork a thread (new ID, preserved history) |
| `turn/start` | Send a message in an existing thread |
| `turn/interrupt` | Cancel current turn |
| `thread/read` | Read thread history |
| `thread/list` | List threads (with filtering) |
| `thread/archive` | Archive a thread |
| `thread/rollback` | Rollback to a previous state |
| `thread/compact/start` | Trigger context compaction |

### Key Protocol Notifications

| Notification | Purpose |
|--------------|---------|
| `thread.started` | Thread created |
| `turn.started` / `turn.completed` | Turn lifecycle |
| `item.started` / `item.completed` | Item lifecycle (messages, commands, patches) |
| `agentMessageDelta` | Streaming agent text |
| `commandExecOutputDelta` | Streaming command output |
| `turnDiffUpdated` | File change diffs |
| `contextCompacted` | Context was compacted |
| `tokenUsageUpdated` | Token usage update |
| `rateLimitsUpdated` | Rate limit state change |

### Thread Item Types (App Server)

The app server protocol exposes richer item types than exec `--json`:

| Type | Description |
|------|-------------|
| `userMessage` | User input (text, image, skill, mention) |
| `agentMessage` | Agent text with phase (`commentary` / `final_answer`) |
| `reasoning` | Reasoning content and summaries |
| `commandExecution` | Shell command with parsed actions, output, exit code |
| `fileChange` | File patches with per-file diffs and change kinds |
| `mcpToolCall` | MCP tool invocations with server, arguments, result |
| `dynamicToolCall` | Dynamic tool calls |
| `collabAgentToolCall` | Multi-agent collaboration calls |
| `webSearch` | Web search with query and action |
| `imageGeneration` | Image generation results |
| `contextCompaction` | Context was compacted |

### Schema Generation

```bash
codex app-server generate-json-schema --out /tmp/schemas/
codex app-server generate-ts --out /tmp/ts/
```

Generates full JSON Schema or TypeScript bindings for the protocol.

---

## Codex Cloud (Experimental)

Remote execution in OpenAI-hosted environments:

```bash
codex cloud exec --env <env-id> "Task prompt"
codex cloud list [--env <env-id>] [--json]
codex cloud status <task-id>
codex cloud diff <task-id>
codex cloud apply <task-id>
```

Best-of-N attempts: `codex cloud exec --attempts 3 --env <id> "prompt"`

---

## Models

Available models (from `models_cache.json`):

| Slug | Context Window | Shell Type | Notes |
|------|---------------|------------|-------|
| `gpt-5.4` | 272,000 | default | Latest, recommended upgrade |
| `gpt-5.4-mini` | 272,000 | default | Smaller, faster |
| `gpt-5.3-codex` | 272,000 | shell_command | **Our target model** |
| `gpt-5.2-codex` | 272,000 | shell_command | Previous gen |
| `gpt-5.2` | 272,000 | default | General purpose |
| `gpt-5.1-codex-max` | 272,000 | shell_command | Extended limits |
| `gpt-5.1-codex` | 272,000 | shell_command | Hidden |
| `gpt-5.1-codex-mini` | 272,000 | shell_command | Mini variant |

All models: 272,000 context window, 95% effective utilization.

### Reasoning Effort

Set via `-c reasoning_effort="high"`:
- `none`, `minimal`, `low`, `medium` (default), `high`, `xhigh`

### Reasoning Summaries

Models support reasoning summaries: `auto`, `concise`, `detailed`, `none`.
Encrypted reasoning content is stored in session rollouts.

---

## Automation Patterns

### Pattern 1: Single-Shot Exec

```bash
codex exec --json --model gpt-5.3-codex --full-auto \
  -C /path/to/repo "Implement the auth module" \
  2>/dev/null
```

Parse JSONL stdout. Exit code 0 = success, 1 = error.

### Pattern 2: Structured Output

```bash
codex exec --json --model gpt-5.3-codex --full-auto \
  --output-schema schema.json "Analyze this code" \
  2>/dev/null
```

Final `item.completed` with `type: agent_message` contains JSON string.

### Pattern 3: Resume for Multi-Turn

```bash
# First turn
THREAD=$(codex exec --json --full-auto "Read the codebase" 2>/dev/null \
  | python3 -c "import sys,json; [print(json.loads(l)['thread_id']) for l in sys.stdin if 'thread_id' in l]" \
  | head -1)

# Follow-up turn (same thread, cache-warm)
codex exec resume --json --full-auto "$THREAD" "Now implement feature X" 2>/dev/null
```

### Pattern 4: Output to File

```bash
codex exec --json --full-auto -o /tmp/result.txt "Your prompt" 2>/dev/null
# Result text written to /tmp/result.txt
```

### Pattern 5: Working Directory Control

```bash
codex exec --json --full-auto -C /path/to/repo "Your prompt" 2>/dev/null
# For non-git directories:
codex exec --json --full-auto --skip-git-repo-check -C /tmp "Your prompt" 2>/dev/null
```

### Pattern 6: Read-Only Analysis

```bash
codex exec --json --model gpt-5.3-codex \
  -a never --sandbox read-only \
  -C /path/to/repo "Analyze the architecture" 2>/dev/null
```

### Pattern 7: Stdin Prompt

```bash
cat instructions.md | codex exec --json --full-auto - 2>/dev/null
```

### Pattern 8: Ephemeral (No Persist)

```bash
codex exec --json --ephemeral --full-auto "Quick question" 2>/dev/null
```

---

## Composability Between Features

### Resume + Structured Output

Resume a session AND constrain the output:
```bash
codex exec resume --json --full-auto --output-schema schema.json \
  "$THREAD" "Summarize what you found"
```

### Resume + Model Override

Change model on resume:
```bash
codex exec resume --json --model gpt-5.4 --full-auto \
  "$THREAD" "Continue with upgraded model"
```

### Config Overrides + Profiles

```bash
codex exec --json -p my_profile -c reasoning_effort="high" "Prompt"
```

### MCP + Exec

MCP servers configured globally are available in exec mode.

### Review + Exec (JSONL)

```bash
codex exec review --json --full-auto --base main 2>/dev/null
```

### Image Input + Exec

```bash
codex exec --json --full-auto -i screenshot.png "What's in this image?"
```

---

## OpenAI-Specific Surface

### Responses API (Not Chat Completions)

Codex uses the **Responses API**, not Chat Completions:
- SSE streaming (not WebSocket)
- `response_format` with `text.format.schema` for structured output
- Built-in tools: `exec_command`, `apply_patch`, `web_search`, `image_generation`
- Reasoning with encrypted content blocks
- Multi-agent collaboration via `spawnAgent`/`sendInput`/`resumeAgent`/`wait`/`closeAgent`

### Prompt Caching

The Responses API provides **automatic prefix-based prompt caching**:
- Cache key is the common prefix of the conversation
- `cached_input_tokens` in usage shows cache hits
- System prompt + developer prompt: ~8,960 tokens cached on first call
- Full conversation prefix: grows with each turn
- No explicit TTL management needed (unlike Claude's 1-hour TTL)

### Rate Limits

Rate limit info exposed in internal rollout format:
```json
{
  "rate_limits": {
    "limit_id": "codex",
    "primary": { "used_percent": 0.0, "window_minutes": 300 },
    "secondary": { "used_percent": 0.0, "window_minutes": 10080 },
    "plan_type": "team"
  }
}
```

Rate limits use a dual-window system:
- Primary: 5-hour window
- Secondary: 7-day window

### Service Tiers

Available tiers: `fast`, `flex` (set via `-c service_tier="fast"`).
Model support varies.

### Context Compaction

When context exceeds limits, Codex performs automatic compaction:
- `contextCompacted` notification in app server
- `compaction` response item with encrypted content
- Transparent to the user/orchestrator

### Ghost Commits

Codex creates "ghost commits" to snapshot working tree state:
- `ghost_snapshot` response item
- Contains commit SHA, parent, and lists of preexisting untracked files/dirs
- Enables rollback via `thread/rollback`

### Truncation Policy

Models define truncation policies:
- `gpt-5.3-codex`: `{ "mode": "tokens", "limit": 10000 }`
- `gpt-5` and above: `{ "mode": "bytes", "limit": 10000 }`

This controls how tool output is truncated before being sent to the model.

---

## Differences from Claude Code CLI

| Aspect | Claude Code CLI | Codex CLI |
|--------|----------------|-----------|
| Primary mode | `claude -p` (print mode) | `codex exec --json` |
| Output format | `--output-format stream-json` | `--json` (simpler JSONL) |
| Session resume | `--resume <id>` | `codex exec resume <id>` (subcommand) |
| Session fork | `--fork-session` (flag) | `codex fork` (separate command, TUI only) |
| Structured output | `--json-schema` (flag) | `--output-schema <file>` |
| Tool control | `--tools` or `--allowed-tools` | No explicit tool control (model decides) |
| System prompt | `--system-prompt` / `--append-system-prompt` | Via `-c instructions="..."` |
| Cost control | `--max-budget-usd` | No equivalent (rate limits only) |
| Effort level | `--effort low/medium/high/max` | `-c reasoning_effort="high"` |
| Continuation | Implicit (tool loop continues) | Implicit (tool loop continues) |
| Event types | `system`, `assistant`, `user`, `result`, `rate_limit_event` | `thread.started`, `turn.*`, `item.*` |
| Session storage | `~/.claude/projects/` | `~/.codex/sessions/` + `state_5.sqlite` |
| Sandbox | Permission modes (`acceptEdits`, etc.) | Sandbox modes (`read-only`, `workspace-write`) |
| API | Messages API (Anthropic) | Responses API (OpenAI) |
| Caching | Explicit prefix cache, 1-hour TTL | Automatic prefix cache, transparent |
| Multi-agent | Via Task tool | Via `multi_agent` feature (spawnAgent, etc.) |

---

## Key Observations for FlatMachines Orchestration

### 1. Simpler JSONL Format

The exec `--json` format is significantly simpler than Claude Code's
`stream-json`. Only 6 event types vs Claude's complex nested format.
Parsing is straightforward.

### 2. Native Resume Semantics

`codex exec resume <thread-id> "prompt"` provides built-in session continuity.
The thread ID is stable across resumes. Cache warming is automatic via the
Responses API prefix cache.

### 3. No Fork in Exec Mode

Unlike Claude Code (`--fork-session`), Codex CLI has no exec-mode fork.
The `codex fork` command is interactive-only. For parallel fan-out from a
shared context, use `codex exec resume` with the same thread ID from
multiple processes (each will get cache hits but advance the same thread).

**Implication:** The SessionHoldback fork pattern from Claude Code adapter
needs adaptation. Options:
- Use resume from the same session (conversation diverges after the resume point)
- Use the app-server protocol's `thread/fork` via WebSocket
- Seed context via prompt engineering rather than session history

### 4. Output Schema Support

Native structured output via `--output-schema` eliminates the need for
a downstream extractor FlatAgent in many cases.

### 5. Exit Semantics

- Exit code 0: success (even with tool errors handled by agent)
- Exit code 1: failure (API error, config error, etc.)
- Exit code 2: usage error (missing args, etc.)
- `turn.completed` always has usage info
- `turn.failed` has error details

### 6. No Cost Tracking

Unlike Claude Code (which reports `total_cost_usd`), Codex CLI does not
report per-session cost. Only token counts are available. Cost must be
calculated externally from token counts and model pricing.

### 7. Session Inspection

Sessions can be inspected via:
- SQLite queries on `state_5.sqlite`
- Reading JSONL rollout files
- `codex exec resume --last` to query most recent
- `codex resume --all` to list all sessions

### 8. Prompt Caching is Implicit

No warm/refresh cycle needed. The Responses API caches automatically.
On resume, the shared conversation prefix gets cache hits immediately.
This simplifies the adapter significantly vs Claude Code's explicit
cache management.

### 9. AGENTS.md Support

Codex automatically reads AGENTS.md files from the repo root and CWD
ancestry. These are injected into the developer prompt. The instructions
appear in the internal rollout as `response_item` with `role: user`.

### 10. Multi-Agent (Stable Feature)

The `multi_agent` feature is stable and enabled by default. It provides
`spawnAgent`, `sendInput`, `resumeAgent`, `wait`, and `closeAgent` tools.
This is Codex's native parallel execution model.

---

## Concurrency & Process Model

Each `codex exec` invocation is a separate OS process. There is no
daemon or long-running server (unless using `codex app-server`).

Multiple concurrent `codex exec` processes can:
- Run independently (different threads)
- Resume the same thread (last-writer-wins on the rollout file)
- Share the same `state_5.sqlite` (SQLite WAL mode handles concurrency)

The app-server mode (`codex app-server --listen ws://...`) provides a
persistent server that can manage multiple threads concurrently over
WebSocket, with proper thread isolation.

---

## Appendix: Full JSONL Event Schema Reference

### `thread.started`
```json
{ "type": "thread.started", "thread_id": "uuid" }
```

### `turn.started`
```json
{ "type": "turn.started" }
```

### `item.started`
```json
{
  "type": "item.started",
  "item": {
    "id": "item_N",
    "type": "command_execution",
    "command": "/bin/bash -lc 'cmd'",
    "aggregated_output": "",
    "exit_code": null,
    "status": "in_progress"
  }
}
```

### `item.completed` (agent_message)
```json
{
  "type": "item.completed",
  "item": {
    "id": "item_N",
    "type": "agent_message",
    "text": "Response text"
  }
}
```

### `item.completed` (command_execution)
```json
{
  "type": "item.completed",
  "item": {
    "id": "item_N",
    "type": "command_execution",
    "command": "/bin/bash -lc 'cmd'",
    "aggregated_output": "stdout+stderr output",
    "exit_code": 0,
    "status": "completed"
  }
}
```

### `turn.completed`
```json
{
  "type": "turn.completed",
  "usage": {
    "input_tokens": 12316,
    "cached_input_tokens": 8960,
    "output_tokens": 19
  }
}
```

### `turn.failed`
```json
{
  "type": "turn.failed",
  "error": { "message": "error details" }
}
```

### `error`
```json
{
  "type": "error",
  "message": "error details"
}
```
