# IPD Controller (Python)

Runs a 10-round deterministic Iterated Prisoner's Dilemma match with two identical LLM-controlled player machines.

Hook separation in this example:
- `IPDPlayerHooks` for player-machine actions/debug
- `IPDMatchHooks` for match-machine scoring/setup

## Run
```bash
./run.sh --local
```

Debug mode (shows per-agent input/output):
```bash
./run.sh --debug
```

## CLI
```bash
python -m ipd_controller.main --rounds 10
python -m ipd_controller.main --rounds 10 --debug
```
