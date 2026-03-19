# Claude Code CLI: Cache & System Prompt Token Behavior

> Measured against Claude Code 2.1.79, sonnet, effort=low, `-p` mode.
> Date: 2026-03-18.

## Summary

The internet claims ~60K tokens for Claude Code's system prompt.
In `-p` (non-interactive print) mode, the actual total is **~15K tokens**.
Interactive mode is higher because it loads CLAUDE.md files, project
context, git state, memory, scratchpad, and full tool definitions.

With `--system-prompt` (replace) and `--tools` (restrict), the total
can be brought down to **~5K tokens**.

## Token Breakdown

| Config | Tools reported | Cache tokens | Notes |
|--------|---------------|-------------|-------|
| Default (no overrides) | 23 | **15,350** | Full CC prompt, 14 tools deferred |
| `--tools Bash,Read,Write,Edit` | 4 | **10,761** | Tool defs sent for all 4 |
| `--tools Read` | 1 | **6,935** | Single tool |
| `--system-prompt` (all tools) | 23 | **9,503** | Replaced user prompt, saved ~6K |
| `--system-prompt` + 4 tools | 4 | **5,172** | Both levers pulled |
| `--system-prompt` + 1 tool | 1 | **~0** | Below cache minimum threshold |

### Component Costs

| Component | Approx. tokens |
|-----------|---------------|
| CC internal base (safety rules, internal instructions) | ~3–4K |
| CC default user-visible prompt | ~6K |
| Each tool definition | ~1–1.5K |
| 9 non-deferred tool definitions (default set) | ~5K |

The **~15K default** breaks down as:

    ~4K internal base + ~6K CC user prompt + ~5K for 9 non-deferred tool defs ≈ 15K

### Deferred Tool Loading

Claude Code reports 23 tools in the `system` init event but only sends
definitions for **9 of them** in the initial system prompt.  The debug
log confirms: `Dynamic tool loading: 0/14 deferred tools included`.

The 14 deferred tools have their definitions loaded on-demand when the
model first invokes them.  This is why 23 tools costs ~15K, not ~35K+.

Deferred tools (not in initial prompt unless used):
- NotebookEdit, WebFetch, WebSearch, TodoWrite, TaskStop,
  AskUserQuestion, Skill, EnterPlanMode, ExitPlanMode,
  EnterWorktree, ExitWorktree, CronCreate, CronDelete, CronList

Non-deferred (always in prompt): Task, TaskOutput, Bash, Glob, Grep,
Read, Edit, Write, ToolSearch.

### `--system-prompt` Behavior

`--system-prompt` replaces the **user-visible portion** (~6K tokens)
but Claude Code still prepends its own internal system content (safety
rules, tool definitions, internal instructions).  It does **not**
eliminate the internal overhead.

`--append-system-prompt` adds to the default prompt without replacing it.

### `--tools` Behavior

`--tools` restricts to exactly the listed tools.  Only definitions for
the listed tools are sent.  The `system` init event confirms the
restriction.  Reducing from 23 → 4 tools saves ~5K tokens.

### `CLAUDE_CODE_SIMPLE=1`

Undocumented env var.  Replaces the entire system prompt with a 3-line
version: identity + CWD + date.  Tool definitions are still sent.
Measured at **~5K tokens** with default tools.

## Interactive vs `-p` Mode

| Mode | Estimated tokens | Includes |
|------|-----------------|----------|
| `-p` (print, SDK) | ~15K | Internal base, user prompt, 9 tool defs |
| Interactive | ~60K (claimed) | Above + CLAUDE.md, project context, git state, memory, scratchpad, full tool defs, agent/skill defs |

The session JSONL files (`~/.claude/projects/<cwd-slug>/<session-id>.jsonl`)
do **not** store the system prompt.  It is assembled fresh each invocation
from the binary's bundled JS.

## Cache Behavior Across Sessions

| Turn | Operation | cache_read | cache_write | Cost |
|------|-----------|-----------|-------------|------|
| 1 | `--session-id` (new) | ~8K | ~7K | ~$0.028 |
| 2 | `--resume` | ~15K | ~300 | ~$0.008 |
| 3 | `--resume` | ~15K | ~300 | ~$0.008 |

On first call, some of the system prompt is already cached from prior
sessions (shared prefix across sessions using the same model).  On
resume, nearly all tokens hit cache.  Cache write per turn is small
(~300 tokens for the new user message + response).

Cache TTL is 1 hour (ephemeral_1h tier).  The `ephemeral_5m` tier
shows 0 tokens in all measurements.

## Implications for Orchestration

1. **Session resume is cheap.**  After the first turn, each resume
   costs ~$0.008 (sonnet) vs ~$0.028 for a new session.

2. **`--system-prompt` + `--tools` is the minimum cost config.**
   4 tools + custom prompt = ~5K tokens.  This is the recommended
   config for orchestrated coding tasks.

3. **Tool restriction has real savings.**  Each tool def is ~1-1.5K
   tokens.  Restricting to the 4-6 tools actually needed saves
   5-10K tokens per call.

4. **The holdback/fork pattern amortizes the first-call cost.**
   Seed once (~$0.028), then forks hit cache (~$0.008 each).

---

## Methodology

All measurements used:

```python
ClaudeCodeExecutor(
    config={
        "model": "sonnet",
        "effort": "low",
        "permission_mode": "bypassPermissions",
        "max_continuations": 0,
        # varied: tools, system_prompt
    },
    config_dir="/tmp",
    settings={},
    throttle=CallThrottle(),  # disabled for measurement
)
```

Prompt: `"Say OK. Nothing else."` — minimal user input to isolate
system prompt cost.

Token source: `AgentResult.usage` fields mapped from the CLI's
`result` event:
- `cache_read_tokens` ← `usage.cache_read_input_tokens`
- `cache_write_tokens` ← `usage.cache_creation_input_tokens`
- `input_tokens` ← `usage.input_tokens` (user message only)

"Cache total" = `cache_read + cache_write`.  This represents the
full system prompt + tool definitions, since those are the only
content eligible for prefix caching on a single-turn call.

Each measurement was a fresh session (`--session-id <new-uuid>`).
Cache read on first call reflects shared prefix cache from prior
sessions on the same model (Anthropic caches by token prefix, not
by session ID).

Debug log captured via `claude -p ... --debug "api" --debug-file`:
- `autocompact: tokens=443 threshold=167000 effectiveWindow=180000`
- `Dynamic tool loading: 0/14 deferred tools included`
- `Sending 5 skills via attachment (initial, 5 total sent)`

The `CLAUDE_CODE_SIMPLE=1` measurement used the same setup with the
env var set.  Source analysis (binary strings extraction) confirmed
this replaces the prompt with: `"You are Claude Code... CWD: ... Date: ..."`.

Session JSONL files were inspected at `~/.claude/projects/-tmp/<id>.jsonl`
to confirm the system prompt is not persisted — only user/assistant
turns and queue operations are stored.
