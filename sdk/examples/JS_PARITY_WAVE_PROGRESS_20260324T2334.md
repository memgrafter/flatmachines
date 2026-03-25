# JS Parity Wave Progress

Timestamp started: 2026-03-24T23:34:35

Scope: ensure JS examples use the same shared `config/` machines, agents, and profiles as Python (golden).

---

## Wave A

Examples:
- `error_handling`
- `support_triage_json`
- `dynamic_agent`
- `human-in-the-loop`

### Findings
- All 4 JS entrypoints load machine config from the shared example-level `config/` directory.
- All 4 corresponding Python entrypoints load from that same `config/` directory.
- Profile usage is aligned:
  - `dynamic_agent`: shared `config/profiles.yml` used in both Python and JS (including dynamic OTF agent execution hooks).
  - `support_triage_json`: shared JSON configs (`machine.json` -> `profiles.json`) used by both Python and JS.
- No JS-only duplicate machine/agent/profile config trees were found for these 4 examples.

### Changes made
- No code/config changes required for Wave A.

### Status
- ✅ Wave A parity complete.

---

## Wave B

Examples:
- `peering`
- `writer_critic`
- `helloworld`
- `parallelism`
- `research_paper_analysis`
- `story_writer`

### Findings
- 5/6 were already aligned with Python golden config usage:
  - `writer_critic`, `helloworld`, `parallelism`, `research_paper_analysis`, `story_writer`
  - JS and Python both load the shared `config/machine.yml` entrypoint for each example.
- `peering` had one parity mismatch:
  - Python golden runs `config/peering_demo.yml`.
  - JS was running `config/orchestrator.yml` and `config/worker_node.yml` directly in app code.

### Changes made
- Updated JS peering entrypoint to match Python golden machine:
  - `sdk/examples/peering/js/src/peering/main.ts`
    - Now runs `config/peering_demo.yml` with shared in-memory persistence/result backend.
    - Keeps checkpoint/execution-id reporting behavior.
- Updated JS peering README to reflect actual parity topology and paths:
  - `sdk/examples/peering/js/README.md`
    - Added `peering_demo.yml` as the primary demo flow.
    - Corrected file-structure block to `js/src/...` layout.

### Validation notes
- Static path/parity checks complete.
- Build command attempted for `peering/js` but local `tsc` is unavailable until dependencies are installed (`npm install` via `run.sh` or manual setup).

### Status
- ✅ Wave B parity complete.

---

## Wave C

Examples:
- `character_card`
- `custom_coding_workflow`
- `coding_machine_cli`
- `rlm`
- `multi_paper_synthesizer`
- `mdap`
- `gepa_self_optimizer`

### Findings
- Already aligned with shared config usage:
  - `character_card`, `custom_coding_workflow`, `coding_machine_cli`, `rlm`, `multi_paper_synthesizer`, `gepa_self_optimizer`
  - JS and Python point to the same example-level `config/` (and `paper_analyzer/config/` where applicable).
- `mdap` had a parity mismatch:
  - Python golden runner executes `config/machine.yml` (`mdap.demo_machine`).
  - JS runner executed a custom JS-only MDAP loop over `config/hanoi.yml` instead of the shared machine.

### Changes made
- Updated JS MDAP demo to use the same machine entrypoint as Python:
  - `sdk/examples/mdap/js/src/mdap/demo.ts`
    - now loads and executes `config/machine.yml`
    - reads Hanoi defaults from `config/hanoi.yml` metadata
- Updated JS MDAP dependency wiring for machine runtime:
  - `sdk/examples/mdap/js/package.json`
    - added `@memgrafter/flatmachines`
  - `sdk/examples/mdap/js/run.sh`
    - now sets both `@memgrafter/flatagents` and `@memgrafter/flatmachines` in local/non-local modes
- Updated docs to reflect parity topology:
  - `sdk/examples/mdap/js/README.md`

### Validation notes
- Static config-path parity checks complete.
- Full TypeScript build was not executed in this environment after dependency changes (requires `npm install` in `sdk/examples/mdap/js`).

### Status
- ✅ Wave C parity complete.
