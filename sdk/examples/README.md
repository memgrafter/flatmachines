# Creating Examples

Guide for creating new flatagents examples.

The Python SDK is to be used, JS sdk is experimental.

## Important: Spec Versions

**Check the `SPEC_VERSION` constant in the spec files at repo root:**

- [`flatagent.d.ts`](../../flatagent.d.ts) — `export const SPEC_VERSION = "..."`
- [`flatmachine.d.ts`](../../flatmachine.d.ts) — `export const SPEC_VERSION = "..."`

Use these values for `spec_version` when creating new examples.

## Required Structure

```
example_name/
├── config/
│   ├── machine.yml      # FlatMachine config (required)
│   └── *.yml            # FlatAgent configs (one per agent)
├── src/
│   └── example_name/    # Package name = example folder name
│       ├── __init__.py  # """Example Name for FlatAgents."""
│       ├── main.py      # Entry point with main() function
│       └── hooks.py     # Optional: custom MachineHooks
├── pyproject.toml
├── run.sh
├── README.md
└── .gitignore
```

## File Templates

### pyproject.toml

```toml
[project]
name = "example_name"
version = "0.1.0"
description = "Short description for FlatAgents"
dependencies = ["flatagents[litellm]"]
requires-python = ">=3.10"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.metadata]
allow-direct-references = true

[project.scripts]
example-name-demo = "example_name.main:main"
```

### run.sh

```bash
#!/bin/bash
set -e

VENV_PATH=".venv"

# Parse arguments
LOCAL_INSTALL=false
PASSTHROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l) LOCAL_INSTALL=true; shift ;;
        *) PASSTHROUGH_ARGS+=("$1"); shift ;;
    esac
done

echo "--- Example Name Demo Runner ---"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Create venv
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
fi

# Install (PyPI by default, local with --local flag)
if [ "$LOCAL_INSTALL" = true ]; then
    uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR/../..[litellm]"
else
    uv pip install --python "$VENV_PATH/bin/python" "flatagents[litellm]"
fi
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

# Run
"$VENV_PATH/bin/python" -m example_name.main "${PASSTHROUGH_ARGS[@]}"
```

**Important:** Run `chmod +x run.sh` after creating.

### .gitignore

```
.venv/
uv.lock
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.DS_Store
.env
```

### src/example_name/__init__.py

```python
"""Example Name for FlatAgents."""
```

### src/example_name/main.py

```python
"""
Example Name Demo for FlatAgents.

Brief description of what this example demonstrates.

Usage:
    python -m example_name.main
    ./run.sh
"""

import asyncio
from pathlib import Path

from flatagents import FlatMachine, LoggingHooks, setup_logging, get_logger
# from .hooks import CustomHooks  # If using custom hooks

# Configure logging
setup_logging(level="INFO")
logger = get_logger(__name__)


async def run():
    config_path = Path(__file__).parent.parent.parent / 'config' / 'machine.yml'
    machine = FlatMachine(config_file=str(config_path), hooks=LoggingHooks())
    
    result = await machine.execute(input={...})
    
    logger.info(f"Result: {result}")
    logger.info(f"API calls: {machine.total_api_calls}, Cost: ${machine.total_cost:.4f}")
    return result


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

### config/machine.yml

```yaml
spec: flatmachine
spec_version: "X.X.X"  # Check flatmachine.d.ts SPEC_VERSION constant

data:
  name: example-name
  context:
    key: "{{ input.key }}"
  
  agents:
    agent_name: ./agent.yml
  
  states:
    start:
      type: initial
      transitions:
        - to: process
    
    process:
      agent: agent_name
      input:
        key: "{{ context.key }}"
      output_to_context:
        result: "{{ output.result }}"
      transitions:
        - to: done
    
    done:
      type: final
      output:
        result: "{{ context.result }}"

metadata:
  description: "Brief description"
```

### config/agent.yml

```yaml
spec: flatagent
spec_version: "X.X.X"  # Check flatagent.d.ts SPEC_VERSION constant

data:
  name: agent-name
  
  model: default
  
  system: |
    System instructions here.
  
  user: |
    User prompt with {{ input.variable }} templating.
  
  output:
    result:
      type: str
      description: Brief description

metadata:
  description: "Brief description"
```

### config/profiles.yml

`profiles.yml` is auto-discovered from the machine config directory.
Do not add `data.profiles` to `config/machine.yml`.

```yaml
spec: flatprofiles
spec_version: "X.X.X"  # Check profiles.d.ts SPEC_VERSION constant

data:
  model_profiles:
    default:
      provider: cerebras
      name: zai-glm-4.7
      temperature: 1.0
    creative:
      provider: cerebras
      name: zai-glm-4.7
      temperature: 0.6

  default: default
```

## Custom Hooks (Optional)

For human-in-loop, voting, or custom logic:

```python
# src/example_name/hooks.py
from typing import Any, Dict
from flatagents import MachineHooks


class CustomHooks(MachineHooks):
    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if action_name == "custom_action":
            # Custom logic here
            context["custom_result"] = "value"
        return context
```

Reference in machine.yml:
```yaml
states:
  custom_state:
    action: custom_action  # Triggers on_action hook
```

## Hook Methods

| Method | When Called | Use Case |
|--------|-------------|----------|
| `on_machine_start(context)` | Execution begins | Init logging/metrics |
| `on_machine_end(context, output)` | Execution ends | Cleanup, final logging |
| `on_state_enter(state, context)` | Before state executes | Pre-processing |
| `on_state_exit(state, context, output)` | After state executes | Post-processing |
| `on_transition(from, to, context)` | Between states | Override transitions |
| `on_error(state, error, context)` | Error occurs | Recovery routing |
| `on_action(action, context)` | State has `action:` | Custom logic |

## Checklist

- [ ] Folder name = package name (use underscores)
- [ ] `config/machine.yml` with `spec: flatmachine`
- [ ] At least one `config/*.yml` agent
- [ ] `src/example_name/__init__.py` with docstring
- [ ] `src/example_name/main.py` with `main()` function
- [ ] `pyproject.toml` with correct name
- [ ] `run.sh` executable (`chmod +x`)
- [ ] `.gitignore`
- [ ] `README.md` explaining the example
