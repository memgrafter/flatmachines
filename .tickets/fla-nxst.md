---
id: fla-nxst
status: open
deps: []
links: []
created: 2026-06-01T00:48:12Z
type: feature
priority: 0
assignee: memgrafter
tags: [flatmachine, dx]
---
# First-class explicit next-state from action output in FlatMachine

Current pattern (action writes context.next_state, YAML transitions branch on it) is correct and stable, but has boilerplate and stringly-typed routing risks. Evaluate adding a direct contract like action-returned next_state (or reserved context key validated by engine) that jumps immediately when valid. Keep current transitions behavior for compatibility; add validation/error-on-unknown-state and good tracing so routing mistakes don't silently fall through default branches.
