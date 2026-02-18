 Depth-First Saturation Scheduler (DFSS) — Straw-Man Spec v0.1

 1) Purpose

 Schedule dynamic DAG workloads so that:

 1. Depth-first progress is favored within each root/job chain.
 2. Constrained resources are saturated (kept busy when work exists).
 3. Fairness is preserved (no root/starvation collapse).

 This is a scheduler spec, not a machine spec.

 ────────────────────────────────────────────────────────────────────────────────

 2) Scope / Non-goals

 ### In scope

 - Multi-root, multi-stage DAG workloads
 - Dynamic task readiness
 - Resource classes with capacities and gates
 - Resume/retry-aware scheduling decisions

 ### Out of scope

 - Storage schema choice (SQL/queue/etc.)
 - Exact retry implementation inside task execution (machine handles this)
 - Provider-specific rate-limit parsing

 ────────────────────────────────────────────────────────────────────────────────

 3) Core Concepts

 - Root: top-level job lineage (e.g., one paper).
 - Node/WorkItem: runnable unit in DAG.
 - Depth: distance from root (higher = deeper).
 - Remaining depth estimate: heuristic distance to completion.
 - Resource class: constrained pool required by item (cheap_model, expensive_model, etc.).
 - Gate: OPEN/CLOSED status per resource class (e.g., 429 cooldown).
 - Active root: root currently admitted to DFS working set.

 ────────────────────────────────────────────────────────────────────────────────

 4) Data Model (logical)

 ```ts
   type RootId = string
   type WorkId = string
   type ResourceClass = string

   interface WorkItem {
     id: WorkId
     root_id: RootId
     depth: number                      // 0-based
     remaining_depth_estimate?: number  // lower is better
     resource_class: ResourceClass
     user_priority?: number             // optional domain hint
     ready_at: number                   // unix ts
     created_at: number
     attempts: number
     max_attempts?: number
     resumable: boolean
     payload_ref: string                // backend-specific pointer
   }

   interface RootState {
     root_id: RootId
     in_flight: number
     last_progress_at?: number
     is_complete: boolean
   }

   interface ResourceState {
     class: ResourceClass
     capacity: number
     in_flight: number
     gate_open: boolean
   }
 ```

 ────────────────────────────────────────────────────────────────────────────────

 5) Scheduler Inputs

 - max_active_roots (int)
 - resource_states[]
 - ready_work_items[] (or backend query equivalent)
 - Policy weights/config (see scoring section)
 - Optional feeder/buffer hints per resource class

 ────────────────────────────────────────────────────────────────────────────────

 6) Scheduling Policy

 6.1 Root admission policy

 - Maintain active root set A, |A| <= max_active_roots.
 - Prefer scheduling work from roots already in A.
 - Admit a new root only if:
     - there is free capacity that active roots cannot consume (due to no ready/gate-open items), or
     - fairness/starvation thresholds require admission.

 6.2 Depth-first preference

 Within candidate items, prefer:
 1. higher depth
 2. lower remaining_depth_estimate
 3. roots with recent progress (continuation bonus)

 6.3 Saturation preference

 For each resource class with free slots and OPEN gate:
 - Fill slots with best available candidates requiring that resource.
 - Avoid idling constrained resources when runnable work exists.

 6.4 Fairness/anti-starvation

 - Add age-based boost for waiting roots/items.
 - Optional per-root concurrency cap (max_in_flight_per_root).
 - Force-admit starving roots after root_starvation_sla.

 ────────────────────────────────────────────────────────────────────────────────

 7) Candidate Scoring (straw man)

 For each runnable item w:

 ```text
   score(w) =
     + W_CONT * is_active_root(w.root_id)
     + W_DEPTH * normalize(depth)
     - W_REMAIN * normalize(remaining_depth_estimate)
     + W_AGE * normalize(wait_time)
     + W_PRIO * normalize(user_priority)
     + W_STARVE * starvation_boost(root)
     - W_NEWROOT * new_root_penalty(if root not active and active set full)
 ```

 Default behavior:
 - W_CONT and W_DEPTH high
 - W_NEWROOT high
 - W_AGE moderate

 ────────────────────────────────────────────────────────────────────────────────

 8) Main Loop (normative behavior)

 1. Refresh resource gate/capacity state.
 2. Build candidates: ready items whose resource_class gate is OPEN.
 3. Partition by resource class; for each class with available slots:
     - rank candidates by score
     - atomically claim top items
     - dispatch execution
 4. On completion/failure:
     - release resource slot
     - update root progress
     - enqueue unlocked successors (backend concern)
 5. Repeat immediately on any completion (no batch boundaries).
 6. If no runnable work:
     - run housekeeping callback
     - sleep/poll interval.

 ────────────────────────────────────────────────────────────────────────────────

 9) Execution Contract (with FlatMachines)

 Each dispatched WorkItem executes one machine run:
 - If resumable and prior checkpoint exists, run with resume_from.
 - Machine-level resilience is internal:
     - data.on_error
     - persistence.resume
 - Scheduler only observes terminal result:
     - COMPLETED
     - RETRYABLE_FAILURE (requeue with backoff)
     - TERMINAL_FAILURE

 ────────────────────────────────────────────────────────────────────────────────

 10) Backend Contract (minimal)

 Scheduler backend must support atomic operations:

 1. claim_ready(resource_class, root_filter?, limit) (atomic claim)
 2. mark_completed(work_id, output_meta)
 3. mark_retryable(work_id, ready_at, reason)
 4. mark_failed(work_id, reason)
 5. enqueue_successors(work_id) (or equivalent DAG unlock)
 6. get_resource_state() / get_root_state() / list_ready()

 ────────────────────────────────────────────────────────────────────────────────

 11) Correctness Invariants

 1. No item runs concurrently more than once (atomic claim).
 2. Gate-closed resource classes dispatch zero new tasks.
 3. If runnable items exist for an OPEN resource with free capacity, scheduler eventually dispatches one.
 4. Starving roots eventually receive service (bounded starvation).
 5. Scheduler decisions are deterministic for equal scores with stable tie-breaks.

 ────────────────────────────────────────────────────────────────────────────────

 12) Observability / KPIs

 - Resource utilization per class (% busy time)
 - Active root count over time
 - Mean completion time per root
 - WIP per root distribution
 - Queue age percentiles
 - Starvation incidents
 - Retry and terminal failure rates

 ────────────────────────────────────────────────────────────────────────────────

 13) Modes (optional)

 - Strict DFS: no new root admission while any active root has gate-open runnable work.
 - Balanced DFS (default): allow controlled new-root admission when active roots are blocked/empty.
 - Fair-share: impose stronger per-root concurrency caps.

 ────────────────────────────────────────────────────────────────────────────────

 14) Open Questions

 1. Should remaining_depth_estimate be required or optional heuristic?
 2. Do we want explicit feeder/buffer policy (for scarce downstream classes), or let scoring handle it?
 3. Should scoring be fully user-pluggable function vs fixed weighted config?
 4. Is root admission global or per-resource-class?


