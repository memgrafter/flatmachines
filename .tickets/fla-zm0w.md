---
id: fla-zm0w
status: open
deps: []
links: []
created: 2026-06-01T00:54:23Z
type: feature
priority: 1
assignee: memgrafter
tags: [flatagents, profiles, dx]
---
# Hierarchical profile discovery with directory walk

Currently `profiles.yml` is discovered only in the agent/machine's own `config_dir` (or passed explicitly). This means every subdirectory that contains agents needs its own `profiles.yml`, even when a whole project shares the same model defaults.

## Desired behavior

Walk parent directories from the agent's `config_dir` up to the project root (git root), then finally check `~/.agents/profiles.yml`. Each closer directory's `profiles.yml` overrides the more distant one.

**Resolution order (lowest to highest priority):**
1. `~/.agents/profiles.yml` (user-global defaults)
2. `<git-root>/profiles.yml` (project-wide defaults)
3. `<git-root>/subdir/profiles.yml` (subdirectory overrides)
4. ...intermediate dirs...
5. `<config_dir>/profiles.yml` (agent's own dir — highest priority)

## Design decision: Option A (recommended) — synthesized fallback chain

**Option A — Synthesized fallback chain:** Walk directory tree, load each profiles.yml found, and merge into a single ProfileManager where each level's `model_profiles` dict is overlaid on top of the parent's. `default` and `override` settings from the nearest file win.

- Gives fine-grained per-profile inheritance: `~/.agents` defines `fast` and `smart`, a subdirectory redefines only `fast`, and `smart` still resolves from global.
- **Shallow merge at profile-name level** — each named profile is replaced wholesale, not field-merged. Profile names are the unit of override, not individual fields within a profile.
- `default` and `override` are taken from the nearest file that sets them (not inherited from parent if child exists but omits them).

**Option B — Bulk override (rejected):** Walk the tree, use the first (nearest) profiles.yml found. No merging. Simpler mental model but forces copying all profiles into every subdirectory that overrides one.

## Affected code

**Python (`sdk/python/flatagents/flatagents/`):**
- `profiles.py` — new `discover_profiles_chain(config_dir) -> List[str]` that walks dirs, new `merge_profiles_chain(chain) -> Dict` that shallow-merges. Update `ProfileManager.get_instance()` and `resolve_model_config()` to use chain. Update/resolve `resolve_profiles_with_fallback`.
- `flatagent.py` L367-383 — replace `discover_profiles_file` + `resolve_profiles_with_fallback` with chain discovery.
- `flatmachine.py` L151-152, L666-667, L936-937 — child machines/agents should inherit parent's resolved chain (or simpler: resolve once at top-level entry point and propagate the merged result, already how `_profiles_dict` works).

**JS (`sdk/js/packages/flatagents/src/`):**
- `profiles.ts` — new `discoverProfilesChain()`, update `ProfileManager.getInstance()`.
- `flatagent.ts` L79-83 — replace configDir-only check with chain discovery.

**Spec:**
- `profile.d.ts` doc comments should document directory-walk resolution.

**Git root detection:**
- Use `git rev-parse --show-toplevel` or walk looking for `.git`. Cache the result.
- Non-git projects: walk to filesystem root or stop at sentinel file (e.g., `.flatagents-root`).

## Tests needed

- Chain discovery with nested dirs
- Git-root boundary behavior
- `~/.agents` fallback
- Merge semantics: child profile overrides parent profile by name, parent-only profiles survive, `default`/`override` nearest-wins
