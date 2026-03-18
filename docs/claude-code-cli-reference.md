# Claude Code CLI Reference for Orchestration

> Tested against Claude Code 2.1.78 on 2026-03-18.
> Binary: `~/.local/bin/claude`

## Overview

Claude Code is Anthropic's CLI coding agent. It runs an internal agentic loop
with 23 built-in tools (Bash, Read, Write, Edit, Grep, Glob, WebFetch,
WebSearch, Task, etc.). It manages its own conversation history, tool
execution, and context.

For FlatAgents orchestration, the CLI is driven in **non-interactive print
mode** (`-p`) with structured output, session management for cache
preservation, and streaming events for real-time observability.

## Key Flags

### Execution Modes

| Flag | Purpose |
|------|---------|
| `-p, --print` | Non-interactive mode. Run prompt, print result, exit. |
| `--output-format text\|json\|stream-json` | Output format. `json` for single result, `stream-json` for event stream. |
| `--verbose` | Required when using `--output-format stream-json`. |
| `--input-format text\|stream-json` | Input format. `stream-json` enables bidirectional pipe (experimental, unreliable — prefer `--resume` for multi-turn). |
| `--include-partial-messages` | Include partial message chunks (only with `stream-json`). |

### Session Management

| Flag | Purpose |
|------|---------|
| `--session-id <uuid>` | Assign a specific UUID to a new session. |
| `--resume <session-id>` | Resume an existing session by ID. Preserves full conversation and cache. |
| `-c, --continue` | Resume the most recent session in the current directory. |
| `--fork-session` | When resuming, create a new session ID (branching). |
| `--no-session-persistence` | Don't persist session to disk. |
| `-n, --name <name>` | Display name for the session. |

### Model & Cost

| Flag | Purpose |
|------|---------|
| `--model <model>` | Model alias (`sonnet`, `opus`) or full name (`claude-sonnet-4-6`). |
| `--effort <level>` | Effort level: `low`, `medium`, `high`, `max`. |
| `--max-budget-usd <amount>` | Cost cap for the session (only with `--print`). |
| `--fallback-model <model>` | Fallback model when primary is overloaded (only with `--print`). |

### Prompts & Instructions

| Flag | Purpose |
|------|---------|
| `--system-prompt <prompt>` | Replace the default system prompt entirely. **Caution:** removes built-in tool instructions. |
| `--append-system-prompt <prompt>` | Append instructions to the default system prompt. **Preferred** for custom instructions. |

### Tool Control

| Flag | Purpose |
|------|---------|
| `--allowed-tools <tools...>` | Whitelist tools (e.g., `"Bash(git:*) Edit Read"`). |
| `--disallowed-tools <tools...>` | Blacklist tools. |
| `--tools <tools...>` | Specify exact tool list. `""` disables all, `"default"` enables all. |

### Permissions

| Flag | Purpose |
|------|---------|
| `--permission-mode <mode>` | `default`, `acceptEdits`, `bypassPermissions`, `dontAsk`, `plan`, `auto`. |
| `--dangerously-skip-permissions` | Bypass all permission checks. **Sandboxed environments only.** |

For headless orchestration use `bypassPermissions` in sandboxed environments
or `auto` for production with guardrails.

### Structured Output

| Flag | Purpose |
|------|---------|
| `--json-schema <schema>` | JSON Schema for structured output validation. |

Claude uses an internal `StructuredOutput` tool call (constant name in
source: `jY="StructuredOutput"`) to produce conforming output. The
structured JSON appears as a `tool_use` content block with
`name: "StructuredOutput"` in the stream. The `result` text field contains
a human-readable version, not the raw JSON. See [Structured Output
Extraction](#structured-output-extraction) for details.

### Workspace

| Flag | Purpose |
|------|---------|
| `--add-dir <directories...>` | Additional directories to allow tool access to. |
| `-w, --worktree [name]` | Create a git worktree for the session. |

### MCP & Plugins

| Flag | Purpose |
|------|---------|
| `--mcp-config <configs...>` | Load MCP servers from JSON files or strings. |
| `--strict-mcp-config` | Only use MCP servers from `--mcp-config`. |
| `--plugin-dir <path>` | Load plugins from a directory. |

### Agents

| Flag | Purpose |
|------|---------|
| `--agent <agent>` | Agent for the session (overrides default). |
| `--agents <json>` | Define custom agents inline as JSON. |

## Output Formats

### `--output-format json`

Single JSON object on completion:

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 2548,
  "duration_api_ms": 2514,
  "num_turns": 1,
  "result": "Hello! 2+2 = 4.",
  "stop_reason": "end_turn",
  "session_id": "e4ae48b4-2f76-4cea-857e-2b6099d3263f",
  "total_cost_usd": 0.0589,
  "usage": {
    "input_tokens": 3,
    "cache_creation_input_tokens": 8856,
    "cache_read_input_tokens": 6285,
    "output_tokens": 14,
    "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 },
    "service_tier": "standard",
    "cache_creation": {
      "ephemeral_1h_input_tokens": 8856,
      "ephemeral_5m_input_tokens": 0
    }
  },
  "modelUsage": {
    "claude-opus-4-6[1m]": {
      "inputTokens": 3,
      "outputTokens": 14,
      "cacheReadInputTokens": 6285,
      "cacheCreationInputTokens": 8856,
      "costUSD": 0.0589,
      "contextWindow": 1000000,
      "maxOutputTokens": 64000
    }
  }
}
```

### `--output-format stream-json --verbose`

NDJSON event stream. One JSON object per line.

#### `system` (init) — first event

```json
{
  "type": "system",
  "subtype": "init",
  "cwd": "/tmp",
  "session_id": "5e100199-...",
  "tools": ["Task", "Bash", "Glob", "Grep", "Read", "Edit", "Write", "..."],
  "model": "claude-opus-4-6[1m]",
  "permissionMode": "default",
  "agents": ["general-purpose", "Explore", "Plan"],
  "skills": ["update-config", "debug", "simplify", "batch", "loop", "claude-api"]
}
```

#### `assistant` — LLM response

Contains content blocks. Multiple content blocks per message are common
(e.g., text + tool_use together).

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-6",
    "role": "assistant",
    "content": [
      { "type": "text", "text": "I'll read that file." },
      { "type": "tool_use", "id": "toolu_01Abc...", "name": "Read",
        "input": { "file_path": "/tmp/test.txt" } }
    ],
    "usage": {
      "input_tokens": 3,
      "cache_read_input_tokens": 15141,
      "output_tokens": 42
    }
  },
  "session_id": "..."
}
```

Content block types in `assistant` messages:
- `text` — LLM text output (`text` field)
- `tool_use` — tool invocation (`id`, `name`, `input` fields)

#### `user` — tool results

Appears after Claude executes a tool internally. Contains the result fed
back to the model:

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "tool_use_id": "toolu_01Abc...",
        "type": "tool_result",
        "content": "     1→hello world\n",
        "is_error": false
      }
    ]
  },
  "tool_use_result": {
    "type": "text",
    "file": { "filePath": "/tmp/test.txt" }
  }
}
```

When a tool fails (e.g., file not found), `is_error` is `true` and
`content` contains the error message:

```json
{
  "type": "tool_result",
  "content": "File does not exist. Note: your current working directory is /tmp.",
  "is_error": true
}
```

**Note:** Tool errors are non-fatal. The model sees the error and adapts.
The final `result` event will still have `is_error: false` unless the
entire session fails.

#### `rate_limit_event`

```json
{
  "type": "rate_limit_event",
  "rate_limit_info": {
    "status": "allowed",
    "resetsAt": 1773867600,
    "rateLimitType": "five_hour",
    "overageStatus": "rejected"
  }
}
```

#### `result` — final event

Same structure as `--output-format json`. Always the last event emitted.

## Session Management & Cache Preservation

### Creating a Session

```bash
SESSION_ID="$(uuidgen)"
claude -p "task description" --session-id "$SESSION_ID" --output-format json
```

### Resuming a Session

```bash
claude -p "follow-up task" --resume "$SESSION_ID" --output-format json
```

Resume picks up the full conversation history. The model sees all prior
messages. Anthropic's prompt cache is leveraged automatically.

### Cache Behavior (Observed)

| Token Field | Meaning |
|-------------|---------|
| `cache_read_input_tokens` | Tokens served from cache. ~14K for system prompt alone, grows with conversation history. |
| `cache_creation_input_tokens` | New tokens written to cache this turn (~1K per turn). |
| `ephemeral_1h_input_tokens` | Tokens in the 1-hour cache tier. |
| `ephemeral_5m_input_tokens` | Tokens in the 5-minute cache tier. |

Observed multi-turn cache pattern:

| Turn | Operation | cache_read | cache_create | Cost |
|------|-----------|-----------|-------------|------|
| 1 | `--session-id` (new) | ~14,180 | ~958 | $0.0132 |
| 2 | `--resume` | ~14,180 | ~972 | $0.0134 |
| 3 | `--resume` | ~14,180 | ~977 | $0.0134 |

Cache read stays constant (system prompt). Cache creation grows
incrementally per turn. Costs remain flat.

### Session Storage

Sessions are stored **locally** as JSONL files. They are **not** persisted
server-side. If the local session file is deleted, `--resume` fails with
`"No conversation found"`.

**Session file location:**
```
~/.claude/projects/<cwd-slug>/<session-id>.jsonl
```

The cwd slug is derived from the working directory (e.g., `/tmp` → `-tmp`,
`/home/user/project` → `-home-user-project`).

**Session file format** (JSONL — one JSON object per line):

```
{"type": "queue-operation", "operation": "enqueue", "sessionId": "...", ...}
{"type": "queue-operation", "operation": "dequeue", ...}
{"type": "user", "message": {"role": "user", "content": "..."}, ...}
{"type": "assistant", "message": {"role": "assistant", "content": [...]}, ...}
{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", ...}]}, ...}
{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", ...}]}, ...}
{"type": "last-prompt"}
```

This is the full conversation transcript including tool calls and results.
The `--resume` flag replays this file to reconstruct the conversation for
the next API call.

**Active session PID mapping** (interactive sessions only):
```
~/.claude/sessions/<pid>.json
{"pid": 217571, "sessionId": "ec6abeb4-...", "cwd": "...", "startedAt": ...}
```

**Implication for orchestration:** Session files must be on the same
filesystem. Sessions cannot be resumed from a different machine unless the
JSONL file is copied over. The `--no-session-persistence` flag (only with
`-p`) disables writing the JSONL file entirely.

## Built-In Tools (v2.1.78)

Reported in the `system/init` event `tools` array:

| Tool | Purpose |
|------|---------|
| `Bash` | Shell command execution |
| `Read` | Read file contents |
| `Write` | Write file contents |
| `Edit` | Surgical file edits |
| `Glob` | File pattern matching |
| `Grep` | Content search |
| `WebFetch` | Fetch URL content |
| `WebSearch` | Web search |
| `Task` | Spawn sub-agent for scoped work |
| `TaskOutput` | Return sub-agent result |
| `TaskStop` | Terminate sub-agent |
| `AskUserQuestion` | Ask user a question (interactive mode) |
| `NotebookEdit` | Jupyter notebook editing |
| `TodoWrite` | Task list management |
| `Skill` | Execute a skill/slash command |
| `EnterPlanMode` / `ExitPlanMode` | Planning mode toggle |
| `EnterWorktree` / `ExitWorktree` | Git worktree management |
| `CronCreate` / `CronDelete` / `CronList` | Cron job management |
| `ToolSearch` | Search for tools |
| `SendUserMessage` | Send message to user (with `--brief`) |

## Structured Output Extraction

When `--json-schema` is passed, Claude uses an internal `StructuredOutput`
tool call. In the `stream-json` output:

```
assistant content: [
  {"type": "tool_use", "name": "StructuredOutput",
   "input": {"languages": [{"name": "Python", "year": 1991}, ...]}}
]
```

The `result` text field contains a human-readable summary, **not** the raw
structured JSON. To get the structured data, intercept the `tool_use`
content block where `name == "StructuredOutput"` and read `input`.

## Error Behavior

### Process-Level Errors

| Scenario | stdout | stderr | Exit Code |
|----------|--------|--------|-----------|
| Success | JSON result | (empty) | 0 |
| Invalid `--resume` ID | (empty) | `"No conversation found..."` | 1 |
| Process killed (SIGTERM/timeout) | Partial NDJSON or nothing | (varies) | 124 (timeout) / 137 (SIGKILL) |
| Network error | (varies) | Error message | 1 |

### Tool-Level Errors

Tool failures are **non-fatal**. The tool result has `is_error: true` and
the model sees the error and adapts. The final `result` event still has
`is_error: false` unless the entire session fails.

```
TOOL_USE: Read input={"file_path": "/nonexistent"}
TOOL_RESULT: is_error=true content="File does not exist."
TEXT: "The file does not exist."
RESULT: is_error=false
```

## Concurrency

Multiple `claude -p` processes can run simultaneously with different session
IDs. Tested: two concurrent sessions with different IDs both complete
successfully with independent results. No file locking conflicts observed.

## Working Directory

Tool execution uses the `cwd` where `claude` is invoked. To scope a session
to a specific directory:

```bash
cd /path/to/project && claude -p "task" --output-format json
```

Use `--add-dir /other/path` to grant tool access to additional directories
beyond cwd.

## Example: Multi-Turn Orchestrated Session

```bash
SESSION=$(uuidgen)

# Step 1: Plan (new session)
claude -p "Plan how to add a /health endpoint to the Flask app" \
  --session-id "$SESSION" \
  --output-format json \
  --model sonnet \
  --permission-mode bypassPermissions \
  --append-system-prompt "You are working on a Flask application."

# Step 2: Implement (resume — has full plan context, cache hit)
claude -p "Now implement the plan" \
  --resume "$SESSION" \
  --output-format json \
  --permission-mode bypassPermissions

# Step 3: Test (resume — sees implementation, cache hit)
claude -p "Run the tests and fix any failures" \
  --resume "$SESSION" \
  --output-format json \
  --permission-mode bypassPermissions \
  --max-budget-usd 1.00
```

Each step sees the full prior conversation. Cache keeps costs flat per turn.
