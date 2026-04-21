# Iterated Prisoner's Dilemma (Agent as Machine Controller)

Two identical LLM-driven player machines play a deterministic **10-round Iterated Prisoner's Dilemma**.

- Shared `config/agent.yml` for both players
- Each player machine routes through:
  - `llm_decision` (agent)
  - `cooperate` (programmatic action)
  - `defect` (programmatic action)
- Routing uses the recommended pattern: action writes `context.next_state`, transitions read it.
- Hooks are intentionally split by machine responsibility:
  - player machine: `ipd-player-hooks`
  - match machine: `ipd-match-hooks`
  (implemented as separate classes in one `python/src/ipd_controller/hooks.py` file)

## Model setup
This example uses the OpenAI Codex OAuth profile setup from:
`~/code/skills-flatagents/codebase-ripper/profiles.yml`

See: `config/profiles.yml`.

## Run (Python)
```bash
cd python
./run.sh --local
```

Debug mode (shows per-agent input/output messages):
```bash
./run.sh --debug
```

or
```bash
cd python
uv venv .venv
uv pip install --python .venv/bin/python -e .
.venv/bin/python -m ipd_controller.main --rounds 10
```
