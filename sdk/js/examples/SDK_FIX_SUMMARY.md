# JS SDK Fix Summary (0.4.0 Scope)

- Added machine `machines` map resolution, `foreach`/`key`/`mode`/`timeout` handling, per‑machine inputs, action hook dispatch, error map handling, context error fields, persistence config + checkpoint events, and max_steps support in `sdk/js/src/flatmachine.ts`.
- Implemented `parallel` and `mdap_voting` execution types plus config plumbing in `sdk/js/src/execution.ts`.
- Added model fields, `instruction_suffix`, output‑instruction guard fix, enum hints, and `tools_prompt`/`model` template variables in `sdk/js/src/flatagent.ts`.
- Extended JS types for 0.4.0/0.6.0 schema fields, including `MachineInput`, `MachineReference`, `MachineWrapper`, `action`, `key`, `mode`, `timeout`, and output field metadata in `sdk/js/src/types.ts`.
- Added `onAction` support to hook implementations in `sdk/js/src/hooks.ts`.
- Updated human‑in‑the‑loop example to use `onAction` for the `action: human_review` state in `sdk/js/examples/human-in-the-loop/src/human-in-the-loop/main.ts`.

## Audit

✔︎ Each bullet maps to a concrete file change and includes the exact file path.
