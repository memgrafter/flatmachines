# Design: `flatmachines improve --init`

> **Goal:** One command scaffolds everything a user needs to run the converged self-improvement loop. No YAML knowledge required. Edit the generated files, then `--run`.

---

## User Flow

```
$ cd my-project
$ flatmachines improve --init

  Self-improvement setup for /home/user/my-project

  Created:
    .self_improve/config.yml    ← edit this: benchmark, metric, scope, checks
    .self_improve/benchmark.sh  ← your benchmark (must print METRIC lines)
    .self_improve/checks.sh     ← fast sanity check (compile, lint, import)

  Next:
    1. Edit .self_improve/benchmark.sh — define your optimization metric
    2. Edit .self_improve/checks.sh — define your fast sanity check
    3. Review .self_improve/config.yml — adjust scope and settings
    4. Run:  flatmachines improve --run

$ flatmachines improve --run

  Reads .self_improve/config.yml, runs the converged loop.
```

---

## Generated Files

### `.self_improve/config.yml`

Single source of truth. Plain YAML, no Jinja2, no spec header. Just the knobs.

```yaml
# Self-improvement configuration
# Edit this file, then run: flatmachines improve --run

# What to optimize
benchmark: bash .self_improve/benchmark.sh
metric: score            # METRIC line name from benchmark output
direction: higher        # "higher" or "lower"

# Fast sanity check (runs before benchmark, skip with empty string)
checks: bash .self_improve/checks.sh

# What the agent can edit (glob patterns)
editable:
  - "src/**/*.py"
  - "lib/**/*.py"

# What the agent cannot touch (glob patterns)
protected:
  - ".self_improve/**"
  - "tests/**"
  - "benchmark.sh"

# Inner loop: iterations per generation
iterations: 3

# Outer loop: number of generations (1 = linear hill-climbing, >1 = evolutionary)
generations: 1

# Parent selection for multi-generation ("best" or "score_child_prop")
parent_selection: best

# Time budget per benchmark run (seconds)
timeout: 300

# Git integration (auto-commit on keep, auto-revert on discard)
git: true
```

**Design choices:**
- Flat keys, no nesting. `benchmark` not `eval_spec.benchmark_command`.
- Comments explain every field.
- Sensible defaults — works out of the box after editing benchmark.sh.
- `editable` and `protected` default to common patterns. User adjusts for their project.
- `generations: 1` is safe default (linear). Bump to enable evolutionary search.

### `.self_improve/benchmark.sh`

```bash
#!/bin/bash
set -euo pipefail

# Your benchmark. Must output METRIC lines.
# Examples:
#   echo "METRIC score=42"
#   echo "METRIC latency_ms=150"
#   echo "METRIC test_count=120"
#
# The metric name must match the 'metric' field in config.yml.
# Exit 0 on success, non-zero on failure.

echo "METRIC score=0"
echo "TODO: replace this with your actual benchmark"
exit 1
```

### `.self_improve/checks.sh`

```bash
#!/bin/bash
set -euo pipefail

# Fast sanity check. Runs before the benchmark to catch obvious failures.
# Keep this under 30 seconds. Examples:
#   python -c "import mypackage"
#   npm run build
#   cargo check
#
# Exit 0 = checks pass, non-zero = skip benchmark (save time).

echo "TODO: replace with your compilation/import/lint check"
exit 1
```

---

## `--run` Reads Config

When `flatmachines improve --run` is invoked (no `--benchmark` flag), it looks for `.self_improve/config.yml` in the target directory and builds the machine input from it:

```python
def _load_improve_config(target_dir: str) -> Dict[str, Any]:
    """Load .self_improve/config.yml and return machine input dict."""
    config_path = Path(target_dir) / ".self_improve" / "config.yml"
    if not config_path.exists():
        return None

    config = yaml.safe_load(config_path.read_text())

    return {
        "target_dir": target_dir,
        "benchmark_command": config["benchmark"],
        "metric_name": config["metric"],
        "metric_direction": config["direction"],
        "checks_command": config.get("checks", ""),
        "editable_patterns": config.get("editable", ["**/*.py"]),
        "protected_paths": config.get("protected", []),
        "inner_iterations": config.get("iterations", 3),
        "max_generations": config.get("generations", 1),
        "parent_selection": config.get("parent_selection", "best"),
        "timeout_s": config.get("timeout", 300),
        "git_enabled": config.get("git", True),
    }
```

**Precedence:**
1. CLI flags override config file (if both present)
2. Config file overrides machine YAML defaults
3. Machine YAML defaults are the fallback

---

## `--init` Auto-Detection

Before writing the scaffolded files, `--init` inspects the target directory and pre-fills intelligent defaults:

| Signal | Default set |
|--------|-------------|
| `*.py` files exist | `editable: ["**/*.py"]` |
| `package.json` exists | `editable: ["src/**/*.ts", "src/**/*.js"]`, `checks: npm run build` |
| `Cargo.toml` exists | `editable: ["src/**/*.rs"]`, `checks: cargo check` |
| `go.mod` exists | `editable: ["**/*.go"]`, `checks: go build ./...` |
| `tests/` dir exists | `protected: ["tests/**"]` |
| `pytest.ini` or `pyproject.toml [tool.pytest]` | `benchmark` pre-filled with pytest runner |
| `.git` exists | `git: true` |
| No `.git` | `git: false` |

This is best-effort. The user always edits the generated files.

---

## What Changes

| File | Change |
|------|--------|
| `improve.py` → `scaffold_self_improve()` | Rewrite to generate the 3 files above with auto-detection |
| `main.py` → improve command | `--run` without `--benchmark` loads `.self_improve/config.yml`. Falls back to CLI flags. |
| `self_improve.yml` | No change — config.yml values are passed as machine input |

---

## What Does NOT Change

- The machine config (`self_improve.yml`) — it already accepts all these as input
- The hooks (`ConvergedSelfImproveHooks`) — already wired
- The evaluation/archive/isolation modules — already built
- CLI flags (`--benchmark`, `--metric`, etc.) — still work for one-off runs without init

---

## Example: Cutting Over flatmachines_cli

```
$ cd ~/code/flatmachines
$ flatmachines improve sdk/python/flatmachines_cli --init

  Created:
    sdk/python/flatmachines_cli/.self_improve/config.yml
    sdk/python/flatmachines_cli/.self_improve/benchmark.sh
    sdk/python/flatmachines_cli/.self_improve/checks.sh

# Edit config.yml:
benchmark: bash ../../autoresearch.bench.sh
metric: tests_passing
direction: higher
checks: bash ../../autoresearch.checks.sh
editable:
  - "flatmachines_cli/**/*.py"
  - "config/**/*.yml"
protected:
  - "../../autoresearch.bench.sh"
  - "../../autoresearch.checks.sh"
  - "tests/**"
iterations: 3
generations: 1

$ flatmachines improve sdk/python/flatmachines_cli --run
# → converged loop runs, replaces autoresearch
```
