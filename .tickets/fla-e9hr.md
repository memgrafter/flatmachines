---
id: fla-e9hr
status: closed
deps: []
links: []
created: 2026-06-01T00:55:15Z
type: feature
priority: 1
assignee: memgrafter
tags: [flatagents, profiles, ux]
---
# Warn on missing profile override

FlatAgents profiles UX: warn loudly when data.override points to a missing profile (e.g. override: fast but only cheap exists). Should emit clear actionable warning and ideally fail fast or auto-fallback with explicit notice so users know the intended model override was not applied.
