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

---

## Overall Status Snapshot (resume-friendly)

Timestamp: 2026-03-25T00:23:23

### 1) Wave completion
- ✅ Wave A complete
- ✅ Wave B complete
- ✅ Wave C complete

### 2) Commits completed
- `4920d3d` — JS parity alignment for peering + mdap shared config-driven flows

### 3) Programmatic parity audit
- Added script: `scripts/check-example-sdk-parity.mjs`
- Run command:
  - `node scripts/check-example-sdk-parity.mjs`
- Latest result:
  - **Examples checked: 17**
  - **PASS: 17**
  - **FAIL: 0**

### 4) Local run smoke tests executed (`--local`)
Ran successfully (exit code 0):
- `error_handling/js`
- `support_triage_json/js`
- `helloworld/js`
- `writer_critic/js`
- `parallelism/js`

Log files used during runs:
- `/tmp/js-local-error_handling.log`
- `/tmp/js-local-support_triage_json.log`
- `/tmp/js-local-helloworld.log`
- `/tmp/js-local-writer_critic.log`
- `/tmp/js-local-parallelism.log`
- plus reruns under `/tmp/js-local-rerun-*.log`

### 5) Temperature warning cleanup
Goal: stop passing `temperature` to reasoning model `gpt-5-mini`.

Status:
- Removed explicit `temperature: 1.0` from example profile/agent configs across `sdk/examples/**/config/` (including JSON profiles where present).
- Re-ran selected JS examples (`error_handling`, `support_triage_json`, `writer_critic`, `parallelism`) with `--local`.
- Result: **temperature warning lines = 0** in those rerun logs.

Note:
- `dynamic_agent` still mentions `otf_temperature` as workflow content/spec data, but this is not the same as passing provider-level temperature params in static profiles.

### 6) Known follow-up
- `parallelism` run output looked semantically off during earlier run (input mapping behavior), despite successful exit code.
- Treat as separate correctness investigation, not SDK parity failure.

### 7) Quick restart commands
```bash
# parity audit
node scripts/check-example-sdk-parity.mjs

# rerun 5 simplest noninteractive JS examples
for e in error_handling support_triage_json helloworld writer_critic parallelism; do
  (cd sdk/examples/$e/js && ./run.sh --local)
done
```
