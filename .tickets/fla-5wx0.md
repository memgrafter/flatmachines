---
id: fla-5wx0
status: closed
deps: []
links: []
created: 2026-06-01T00:54:44Z
type: bug
priority: 1
assignee: memgrafter
tags: [flatagents, codex, regression]
---
# Fix CodexCliExecutor.execute() session_id kwarg regression

Python codex_cli adapter regression: CodexCliExecutor.execute() receives unexpected keyword argument 'session_id' from execution layer — TypeError. Fix compatibility so sdk/examples/codex_cli_adapter/python runs again.
