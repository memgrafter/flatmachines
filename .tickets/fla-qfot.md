---
id: fla-qfot
status: open
deps: []
links: []
created: 2026-06-01T00:54:11Z
type: feature
priority: 2
assignee: memgrafter
tags: [flatagents, tool-loop]
---
# ToolLoopAgent per-turn callback / input_data refresh

Currently run() takes input_data once and only renders templates on turn 0. There is no hook to inject dynamic state (remaining budget, elapsed cost, steering context) into subsequent turns. Callers who need per-turn injection must reimplement the loop. Options: (a) accept a per-turn callback that returns extra messages to append after tool results, receiving current (turns, tool_calls, usage) as args; (b) accept a callable that returns updated input_data for re-rendering each turn. Option (a) is simpler and doesn't require re-rendering. The existing SteeringProvider is close but receives no loop state.
