---
id: fla-fjl7
status: open
deps: []
links: []
created: 2026-06-01T00:54:33Z
type: feature
priority: 2
assignee: memgrafter
tags: [flatagents, testing, smolagents, pi-agent]
---
# Live integration coverage for smolagents and pi-agent runtimes

Add live/integration coverage for FlatAgents-side smolagents and pi-agent runtimes. Current migration moved those single-agent runtime adapters into Python FlatAgents, but we do not yet have live end-to-end tests/examples validating auth/environment/session behavior the way Codex/Claude paths are exercised. Add at least smoke tests and one example per runtime once credentials/tooling are available.
