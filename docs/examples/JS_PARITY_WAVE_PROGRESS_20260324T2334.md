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

### 8) Next-5 JS run batch (`--local`)
Timestamp: 2026-03-25T00:52:16

Target batch:
- `character_card/js`
- `custom_coding_workflow/js`
- `coding_machine_cli/js`
- `rlm/js`
- `multi_paper_synthesizer/js`

Run outcomes:
- ✅ `character_card/js` succeeded (auto-user run with temp card JSON)
- ✅ `custom_coding_workflow/js` succeeded after switching exploration to `codebase-ripper` path (no `codebase_explorer` symlink requirement)
- ✅ `coding_machine_cli/js` succeeded (`--standalone` mode)
- ✅ `rlm/js` succeeded (`--demo` mode)
- ✅ `multi_paper_synthesizer/js` succeeded

Logs:
- `/tmp/js-local-next5b-character_card.log`
- `/tmp/js-local-next5b-custom_coding_workflow.log`
- `/tmp/js-local-next5b-coding_machine_cli.log`
- `/tmp/js-local-next5b-rlm.log`
- `/tmp/js-local-next5b-multi_paper_synthesizer.log`

Post-run parity audit:
- `node scripts/check-example-sdk-parity.mjs` => **PASS 17 / FAIL 0**

### 9) Remaining costly runs: mdap + gepa_self_optimizer
Timestamp: 2026-03-25T01:38:41

Run outcomes (`--local`):
- ✅ `mdap/js` succeeded after TS typing fix in `src/mdap/demo.ts`
  - command: `bash ./run.sh --local`
  - log: `/tmp/js-local-final-mdap.log`
  - note: execution finished with API calls and stats; semantic quality of final state should be reviewed separately.
- ✅ `gepa_self_optimizer/js` succeeded
  - command: `bash ./run.sh --local`
  - log: `/tmp/js-local-final-gepa_self_optimizer.log`

Remaining run-blocked example:
- None

### 10) `custom_coding_workflow` exploration dependency update
Timestamp: 2026-03-25T22:54:43

Changes made:
- Replaced `codebase_explorer` machine dependency with `explore_codebase` hook action in shared machine config.
- Updated JS and Python hooks to prefer `codebase-ripper` CLI (`$HOME/.agents/skills/codebase-ripper/run.sh --json`) and fall back to local tree/README exploration.
- Removed JS `run.sh` hard failure on missing `codebase_explorer` symlink.

Validation:
- ✅ JS run: `custom_coding_workflow/js` with `./run.sh --local ...` now executes.
- ✅ Python run: `custom_coding_workflow/python` with `./run.sh --local ...` now executes.
- ✅ Parity audit still passes: `node scripts/check-example-sdk-parity.mjs` => PASS 17 / FAIL 0.
