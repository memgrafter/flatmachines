# Chat Context Reset + Searchable History Design (Atomic Mini One-Pagers)

## 1) Context Reset Primitive

### Goal
Provide a deterministic way to “start fresh” context for the assistant without deleting historical data.

### Scope
- New command: `/reset`
- A reset creates a new `session_id`
- Old sessions remain queryable via history tools

### Inputs / Outputs
- Input: user command `/reset` (optionally reason metadata)
- Output: new active session, empty rolling context buffer

### Core Behavior
- Persist a `session_reset` event tied to user/channel
- Generate and activate new `session_id`
- Do **not** auto-import old messages into active prompt context
- Keep stable identity-level metadata (user id, policy flags, preferences)

### Data Effects
- Insert reset event in events table
- Update active session pointer for `(tenant_id, user_id, channel_id)`

### Failure Modes
- If reset write fails: keep old session active and return explicit error
- If duplicate reset request: idempotent if same request id

### Acceptance Criteria
- After `/reset`, next model turn sees no prior-session transcript unless tools fetch it
- Historical sessions are still retrievable

---

## 2) Chat Persistence Schema

### Goal
Store chat turns durably so history can be searched/retrieved later without bloating active context.

### Scope
SQLite-first schema, WAL mode compatible.

### Proposed Tables
- `sessions(session_id, tenant_id, user_id, channel_id, created_at, closed_at, reset_reason)`
- `messages(message_id, tenant_id, user_id, channel_id, session_id, ts, role, content, metadata_json)`
- `events(event_id, tenant_id, user_id, channel_id, session_id, ts, type, payload_json)`
- `active_sessions(tenant_id, user_id, channel_id, session_id, updated_at)`

### Indexes
- `messages(tenant_id, user_id, ts)`
- `messages(tenant_id, session_id, ts)`
- `events(tenant_id, user_id, ts)`

### FTS
- `messages_fts` virtual table on message content
- Keep `message_id` linkage for secure post-filtering

### Data Retention
- Configurable retention by tenant/user/session age
- Soft-delete marker preferred before hard delete

### Acceptance Criteria
- Insert/query latency acceptable at expected volume
- History queries work by user, session, and keyword

---

## 3) Search & Retrieval Tooling

### Goal
Enable the assistant to retrieve relevant prior chat data on demand (instead of always stuffing full history in prompt).

### Scope
Read-only retrieval tools exposed to agent runtime.

### Tool API (minimum)
- `history.recent(user_id, channel_id, limit=50)`
- `history.session(session_id, limit=200, cursor=None)`
- `history.search(query, user_id, channel_id=None, limit=20, ts_from=None, ts_to=None)`

### Retrieval Contract
- Return compact snippets + ids + timestamps
- Include pagination cursor where needed
- Enforce max payload size per call

### Ranking
- Default: FTS relevance + recency tiebreak
- Optional: hybrid ranking with semantic embeddings later

### Guarded Defaults
- Limit results by default
- Require explicit expansion call for full transcript

### Acceptance Criteria
- Assistant can answer “what did I say about X last week?” using tools
- Queries are fast and scoped

---

## 4) Authorization & Safety Guardrails

### Goal
Prevent cross-user/tenant leakage and reduce sensitive data exposure.

### Scope
Hard enforcement at tool/data layer.

### Mandatory Controls
- Every query requires `tenant_id` and authenticated principal
- Server-side WHERE clauses enforce ownership/scope
- Never rely on model to self-restrict scope

### Redaction Policy
- Optional ingest-time redaction for secrets (tokens/keys)
- Retrieval-time masking for known sensitive patterns

### Auditability
- Log every history tool call:
  - actor
  - tool name
  - scope
  - result count
  - timestamp

### Abuse Prevention
- Rate limits on search endpoints
- Result-size caps and timeout ceilings

### Acceptance Criteria
- No cross-tenant data returned under adversarial prompts
- All access attempts auditable

---

## 5) Prompt + Runtime Integration

### Goal
Keep active context small while allowing explicit retrieval when needed.

### Scope
Prompt policy + orchestration behavior.

### Runtime Pattern
1. Build prompt from recent turns in active session only (small window)
2. If missing context detected, call history tools
3. Inject only selected snippets back into reasoning context

### System Prompt Additions
- “Use history tools only when needed”
- “Cite message ids/timestamps when referencing retrieved history”
- “Do not assume unavailable history”

### Reset Semantics
- `/reset` starts clean short-term context
- History remains tool-addressable

### Acceptance Criteria
- Token usage drops vs always-including full history
- Quality remains stable or improves on long-lived chats

---

## 6) Operations, Performance, and Rollout

### Goal
Ship safely with observability and rollback options.

### Scope
Migration, metrics, and phased launch.

### Migration Steps
1. Add schema + indexes + FTS
2. Introduce write path for sessions/messages/events
3. Add read-only history tools behind feature flag
4. Enable `/reset`

### Metrics
- Tool call rate / latency / error rate
- Search hit rate
- Average prompt token count
- User-visible quality signals (thumbs up/down)

### Reliability
- SQLite WAL mode enabled
- Busy timeout configured
- Periodic integrity checks and backup policy

### Rollout Plan
- Phase 1: internal users only
- Phase 2: selected tenants
- Phase 3: default-on with kill switch

### Acceptance Criteria
- No regressions in latency/SLO
- No auth leakage incidents
- Clear rollback path documented

---

## Appendix A: Minimal SQLite Notes
- Use WAL mode for read/write concurrency.
- Use `busy_timeout` to reduce lock errors under contention.
- Prefer read-only connections for retrieval tools where possible.
- For live backup, use SQLite `.backup` API/command, not raw file copy during active writes.
