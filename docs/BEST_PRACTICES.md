# FlatAgents / FlatMachines Best Practices (v2)

## 1) Checkpoint/Restore as the Job Engine (not a separate scheduler layer)

### Core rule
- Treat **machine checkpoint state** as the job state.
- Avoid duplicating truth in an external job engine unless you truly need multi-tenant orchestration.

### Why this worked
- Cancel/restart safety comes from checkpoint + resume, not worker heartbeats.
- Fewer moving parts: no separate batch scheduler + worker state reconciliation.
- Better observability: execution state is queryable directly in SQLite.

### Why SQLite shared DB + checkpoint backend
- Single local source of truth for:
  - execution rows
  - checkpoint snapshots
  - latest snapshot pointers
  - lease locks
- Atomic writes and easy recovery (`BEGIN IMMEDIATE`, WAL).
- Lower FD churn vs file `.tmp` checkpoint writes at high concurrency.
- Easy operational queries during incidents.

### Why locks belong in DB (lease model)
- File locks (`.locks`) create FD churn and stale file cleanup pain.
- DB leases allow:
  - owner identity (`host:pid:run_id`)
  - TTL-based takeover
  - explicit renew/release
  - queryable lock state

### DB pieces you should keep
- `executions` (status + payload references)
- `machine_checkpoints` (snapshot blobs)
- `machine_latest` (resume pointer)
- `execution_leases` (lock/ownership)
- `daily_usage` (budget accounting)

### Pruning strategy (important)
- Keep checkpoint history for active/in-flight executions.
- Prune checkpoint rows for terminal executions (`done`/`failed`) on a schedule.
- After heavy prune, reclaim disk with `VACUUM INTO` during downtime.
- Keep one pre-compact backup until integrity checks pass.

### Minimal restore flow
- On startup:
  1. migrate legacy file checkpoints if needed
  2. query `machine_latest + machine_checkpoints` for incomplete states
  3. resume first, then claim new work

---

## 2) LLM Handoff Simplicity: avoid JSON/Jinja between model stages

### Why avoid JSON/Jinja in model-to-model outputs
- Fragile parsing under load/retries.
- Token waste (schema wrappers, braces, escape noise).
- More transformation layers = more failure points.

### Practical pattern
- Pass plain text/markdown payloads between LLM stages.
- Keep context mappings explicit and shallow.
- Minimize transforms to boundary actions only (e.g., final DB write, final report save).
- Preserve full source text (`paper_text`) through expensive stages; avoid excerpt-only chains.

### Rule of thumb
- Every transformation must justify itself in one line.
- If not necessary for control flow, remove it.

### Non-truncation invariant (hard rule)
- **Never truncate data** from LLM outputs or from inputs passed into LLMs.
- If there is concern about fitting/token limits, **consult the user** before changing data shape.
- Acceptable strategies when size is a problem:
  - enforce size limits in `agent.yaml` prompts
  - reject oversized payloads and retry with a compliant output
  - route oversized payloads to a repair/compaction LLM stage
- Silent or automatic truncation is forbidden, ever.

---

## 3) Prioritization anecdote → future DFS-style optimizer

### What we did
- Resume-first policy.
- New work priority: expensive phase first, then wrap, then prep.
- Goal: maximize completed papers under budget and unstable provider windows.

### Why this behaved well
- It approximates **depth-first completion** (finish work already started).
- Reduces stranded partial executions.
- Keeps expensive windows focused on expensive-only calls.

### Future direction (formalized)
- Implement scoring/selection as a DFS-like optimization objective, e.g.:
  - maximize expected `done` transitions per unit budget/time
  - penalize state age and partial-work abandonment
  - dynamically rebalance prep vs expensive vs wrap by queue pressure + model availability

---

## 4) Query/Command suite we used to manage operations

### Pipeline health
- `./phase_buffer_counts.sh`
  - one-line phase and in-flight visibility

- Status counts:
```sql
SELECT status, COUNT(*) AS cnt
FROM executions
GROUP BY status
ORDER BY status;
```

### Failure triage
- Top error prefixes:
```sql
SELECT substr(coalesce(error,''),1,120) AS err_prefix, COUNT(*) AS cnt
FROM executions
WHERE status='failed'
GROUP BY err_prefix
ORDER BY cnt DESC;
```

- Requeue transient failures (manual op policy)

### Output parity checks
- Compare terminal vs report files:
  - terminal = `done + failed`
  - report files = `find data -name '*.md' | wc -l`

### Checkpoint footprint
- Largest tables (`dbstat`):
```sql
SELECT name, SUM(pgsize) AS bytes
FROM dbstat
GROUP BY name
ORDER BY bytes DESC;
```

### FD pressure checks
- Runner FD snapshot:
  - total FDs
  - established TCP
  - checkpoint tmp FDs
  - lock FDs
  - sqlite FDs
- Use these as gating signals before raising worker count.

---

# Appendix A — Prior quick checklist (kept for reference)

## Architecture
- Keep pipeline phase-separated: **prep (cheap) → expensive (pony only) → wrap (cheap)**.
- Treat machine state as the job source of truth; avoid extra scheduler/worker abstractions.
- Prefer depth-first resume-before-new-work behavior.

## Persistence & Locks
- Use **DB-backed checkpoint persistence** (not file temp checkpoints) for high concurrency.
- Use **DB lease locks** (not file `.locks`) to avoid FD churn and stale lock files.
- Keep checkpoint and lock concerns separate in implementation.
- Prune terminal checkpoint history regularly (`done`/`failed`).

## SQLite Usage
- Keep one v2 DB owned by v2; keep arxiv DB read-only.
- Reuse process-wide SQLite connections; avoid per-task connection creation.
- Serialize DB writes in hooks with a single async write gate.
- Always set WAL + busy timeout for long-running runners.

## Concurrency
- `--workers` means coroutine concurrency, not subprocess count.
- High workers can still exhaust FDs via sockets/checkpoints; validate with `lsof`.
- Scale up only after FD profile is stable.

## Error Handling
- Never swallow DB write failures silently (especially mark-failed paths).
- Requeue transient infra failures (`too many open files`, `database is locked`, etc.).
- Keep hard errors (e.g. persistent 404 PDF) isolated for manual review.

## Data Flow Quality
- Pass full `paper_text` end-to-end; avoid excerpt-only paths.
- Never truncate LLM inputs/outputs; if size is a concern, consult the user and use prompt limits/retry/repair flows instead.
- Keep machine I/O mappings explicit and simple.
- Verify wrapper machine context propagation carefully.

## Output Quality Guardrails
- Run a lightweight sentinel on latest reports:
  - section completeness
  - fallback phrase detection
  - duplicate summary opener detection
  - numeric grounding vs extracted paper text
- Run sentinel continuously in watcher mode during long jobs.

## Operations / Recovery
- Track health continuously:
  - `phase_buffer_counts.sh`
  - FD snapshot (`total`, `tcp_est`, `checkpoint_tmp`, `locks`, `sqlite`)
- If drift occurs:
  - stop runner
  - release/reset transient statuses
  - move transient failed back to pending
  - restart cleanly

## Disk Hygiene
- Checkpoint tables can dominate DB size; monitor table footprint (`dbstat`).
- Expect free pages after pruning; run `VACUUM INTO` during downtime to shrink file.
- Keep one backup DB when swapping compacted DB, then delete backup once verified.

## Keep It Simple
- Prefer small, reversible infra changes.
- Add CLI flags for one-off migrations and explicit maintenance actions.
- Avoid changing worker policy unless required by observed behavior.
