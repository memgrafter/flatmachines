---
id: fla-2btn
status: open
deps: []
links: []
created: 2026-06-01T00:48:48Z
type: feature
priority: 0
assignee: memgrafter
tags: [flatagents, debug]
---
# FlatAgents debug I/O mode

Add first-class debug capability to print rendered prompts + raw model output (and optionally transport payload metadata) across FlatAgents/FlatMachines without per-example custom hooks. Proposed levels: (a) metadata only, (b) rendered prompts + raw completion, (c) full payload with redaction. Must be explicit opt-in, safe by default.
