---
id: fla-ghnk
status: open
deps: []
links: []
created: 2026-06-01T00:54:06Z
type: feature
priority: 1
assignee: memgrafter
tags: [flatagents, anthropic, caching]
---
# Anthropic prompt caching support

Anthropic supports automatic caching via a top-level cache_control param on the request body (no content-block restructuring needed). FlatAgent already forwards unknown model config keys to litellm params, so callers can add cache_control: {type: ephemeral} to their model config and it passes through. Verify this works end-to-end through litellm → OpenRouter → Anthropic and document it. If litellm strips the param, add it to the explicit pass-through list.
