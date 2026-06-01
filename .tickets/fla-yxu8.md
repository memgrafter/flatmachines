---
id: fla-yxu8
status: open
deps: []
links: []
created: 2026-06-01T00:54:18Z
type: feature
priority: 2
assignee: memgrafter
tags: [testing, codex, caching]
---
# Port live Codex cache tests into flatagents/flatmachines test suites

Port the live Codex cache tests built in swarm worker back into flatmachines/flatagents proper test suites (unit + integration). Specifically cover: execution_id->session_id/prompt_cache_key plumbing in execute_with_tools, first-3-message prefix stability across continuation turns, and large-initial-prompt continuation cache-hit behavior.
