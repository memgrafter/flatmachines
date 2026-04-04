# Profile YAML Resolution & Discovery — Design Plan

> Python SDK only. Spec version: 2.5.0+

## Current State

Profiles live in `config/profiles.yml` co-located with agent/machine configs. Discovery is directory-local only — no global/user-level config, no alias chaining, case-sensitive names, no project-root search.

## Use Cases (ordered by frequency)

1. **Per-agent named profiles** (most common)
   - User sets `model: "fast"` or `model: "gpt-5-mini"` in their agent YAML
   - Profile resolved from the nearest `profiles.yml`
   - Enables one-touch model swaps without editing every agent
   - *Status: fully supported*

2. **Per-project profiles** (`./config/profiles.yml` or project root)
   1. Explicit path — user passes `profiles_file` kwarg
      - *Status: fully supported*
   2. Co-located discovery — `profiles.yml` in same dir as agent config
      - *Status: fully supported*
   3. **Project-root discovery** — walk up to find `profiles.yml` or `.flatmachines/profiles.yml` at repo root
      - *Status: **gap** — not implemented*
      - Value: avoids duplicating profiles.yml into every `config/` subdirectory

3. **User-global profiles** (`~/.agents/flatmachines.yml` or `~/.config/flatagents/profiles.yml`)
   - Researcher always wants `gpt-5-mini` as default across all projects
   - Global file is the lowest-priority fallback, project profiles override it
   - *Status: **gap** — not implemented*
   - Discovery order would become:
     1. Explicit path (if provided)
     2. Co-located `config/profiles.yml`
     3. Project-root `profiles.yml` or `.flatmachines/profiles.yml`
     4. `~/.agents/flatmachines.yml` (user global)
   - Env var override: `FLATAGENTS_PROFILES_FILE`

4. **Profile aliases** (profile referencing another profile)
   - `default: fast` already works (sets fallback profile name)
   - **Alias chaining**: a profile whose value is a string name of another profile
     ```yaml
     model_profiles:
       fast: { provider: openai, name: gpt-5-mini }
       default:
         - fast          # alias → resolves to "fast" profile
       my-cheap:
         - fast          # alias → same model, different semantic name
     ```
   - *Status: **gap** — not implemented*
   - Implementation: detect when a profile value is a string or single-element list; resolve transitively (max depth=5 to prevent cycles)

5. **Inline overrides on named profiles**
   - `model: { profile: "fast", temperature: 0.9 }`
   - *Status: fully supported*

6. **Global override** (force all agents to one profile)
   - `override: smart` in profiles.yml
   - *Status: fully supported*

7. **Parent-to-child propagation** (machines pass profiles to sub-agents)
   - Child's own profiles.yml wins completely (no merge)
   - *Status: fully supported*

## Proposed Discovery Order (new)

```
resolve_profiles(agent_config_dir, explicit_path=None):
    1. explicit_path (if provided) → return
    2. agent_config_dir/profiles.yml → return
    3. walk up to project root, check:
       a. <dir>/profiles.yml
       b. <dir>/.flatmachines/profiles.yml
       → return first found
    4. FLATAGENTS_PROFILES_FILE env var → return
    5. ~/.agents/flatmachines.yml → return
    6. None (no profiles; agent uses inline model config only)
```

Project root detection: first parent containing `.git`, `pyproject.toml`, or `setup.py`.

**Merge semantics**: none. Nearest profiles.yml wins entirely — consistent with current `resolve_profiles_with_fallback` behavior. User-global is a fallback, not a base layer.

## Profile Aliases — Detailed Design

### Syntax

```yaml
data:
  model_profiles:
    fast: { provider: openai, name: gpt-5-mini }
    smart: { provider: anthropic, name: claude-sonnet-4-6 }

    # Alias: value is a single-element list containing a profile name
    default:
      - fast
    cheap:
      - fast
    best:
      - smart
```

Single-element list chosen over bare string because bare string would be ambiguous with model name strings in other contexts.

### Resolution

```python
def resolve_alias(profiles, name, depth=0):
    if depth > 5:
        raise ValueError(f"Circular profile alias: {name}")
    cfg = profiles.get(name)
    if isinstance(cfg, list) and len(cfg) == 1 and isinstance(cfg[0], str):
        return resolve_alias(profiles, cfg[0], depth + 1)
    return cfg
```

### Profile Name Constraints (deferred)

Profile names are currently arbitrary YAML strings. A future version may restrict to `[A-Za-z0-9._-]` and make lookup case-insensitive. **Deferred** — for now, document the recommendation without enforcing it.

Recommended pattern: `lowercase-kebab-case` (e.g., `fast`, `gpt-5-mini`, `my-research-default`).

## Gaps Summary

| Gap | Priority | Complexity | Notes |
|-----|----------|-----------|-------|
| Project-root discovery | **High** | Low | Walk-up search, stop at `.git`/`pyproject.toml` |
| User-global profiles (`~/.agents/`) | **High** | Low | Single fallback file, no merge |
| `FLATAGENTS_PROFILES_FILE` env var | Medium | Trivial | Inserted at step 4 of discovery |
| Profile alias chaining | Medium | Low | Single-element list syntax, max depth=5 |
| Case-insensitive profile names | Low | Low | Deferred; document recommended convention |
| Schema validation at load time | Low | Medium | Currently only validates `spec` field |

## Implementation Plan

1. **`discover_profiles_file` enhancement** (profiles.py)
   - Add `project_root` detection (walk up for `.git`/`pyproject.toml`)
   - Add project-root search (steps 3a, 3b)
   - Add env var check (`FLATAGENTS_PROFILES_FILE`)
   - Add user-global fallback (`~/.agents/flatmachines.yml`)
   - Keep existing explicit-path and co-located behavior unchanged

2. **Profile alias resolution** (profiles.py → `ProfileManager`)
   - Add `_resolve_alias()` method
   - Call from `get_profile()` transparently
   - Add cycle detection (max depth=5)

3. **Tests** (test_profiles_discovery.py)
   - Test walk-up discovery
   - Test env var override
   - Test user-global fallback
   - Test alias resolution and cycle detection

4. **Update AGENTS.md / CLAUDE.md** profile section
   - Document discovery order
   - Document alias syntax
   - Document recommended naming convention

## Additional Ideas

- **`flatagents profiles list`** CLI command — show resolved profiles for a given config directory, including which file they came from. Useful for debugging "which profile am I actually using?"
- **`flatagents profiles init`** — scaffold a `profiles.yml` in the current directory or `~/.agents/`
- **Profile inheritance** (not aliases) — `creative: { extends: "fast", temperature: 0.95 }`. More powerful than aliases but adds complexity. Could be a v2 feature.
- **Environment-scoped profiles** — `profiles.dev.yml`, `profiles.prod.yml` selected via `FLATAGENTS_ENV`. Useful but can be achieved today with the override mechanism.
- **Profile validation warnings** — warn if a profile references a provider/model combination that doesn't exist in the user's environment (e.g., missing API key). Non-blocking.
