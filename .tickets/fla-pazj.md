---
id: fla-pazj
status: open
deps: []
links: []
created: 2026-06-01T00:55:21Z
type: bug
priority: 1
assignee: memgrafter
tags: [flatmachines, flatagents, paths, dx]
---
# Fix embedded config path handling in FlatMachines->FlatAgents

When FlatMachine resolves an agent file ref into an embedded config dict for checkpoint/self-contained execution, preserve the agent file's source config_dir (dirname of the agent file). FlatAgentAdapter should pass that preserved config_dir to FlatAgent(config_dict=..., config_dir=...) instead of the machine config_dir. This allows canonical agent-local prompt refs like prompt: ../prompts/foo.prompt.yml and removes the need for symlink workarounds.
