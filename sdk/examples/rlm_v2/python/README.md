# Recursive Language Model v2 (Minimal)

A stripped-down RLM implementation aligned with Algorithm 1 from the RLM paper, implemented as a FlatMachine loop.

## Key properties

- Long context is stored in REPL variable `context` (not sent directly to root LM input)
- Root LM iteratively emits ` ```repl ` code
- REPL state is persistent across iterations
- Only bounded execution metadata is fed back to root LM
- Recursive `llm_query()` calls launch the same machine with incremented depth
- Termination is strict: run ends only when REPL variable `Final` exists and is not `None`

## Layout

```text
rlm_v2/
├── config/
│   ├── machine.yml
│   ├── coder.yml
│   └── profiles.yml
└── python/
    ├── run.sh
    ├── pyproject.toml
    └── src/rlm_v2/
        ├── main.py
        ├── hooks.py
        └── repl.py
```

## Usage

From `sdk/examples/rlm_v2/python`:

```bash
./run.sh --local --demo
```

`run.sh` defaults to maximum information mode (`--inspect --inspect-level full --print-iterations --trace-dir ./traces`) unless you explicitly provide your own inspect flags.

Run on a file:

```bash
./run.sh --local --file /path/to/long.txt --task "Summarize the argument by chapter"
```

Run with inspect mode (recommended for research):

```bash
./run.sh --local --demo --inspect --print-iterations --trace-dir ./traces
```

This writes:

- `traces/<run_id>/manifest.json`
- `traces/<run_id>/events.jsonl`

Core event types in `events.jsonl`:
- `run_start`, `iteration_start`, `llm_response`, `code_blocks_extracted`
- `repl_exec`
- `subcall_start`, `subcall_end`
- `final_detected`, `run_end`, `error`

## Options

- `--max-depth` (default: 5)
- `--timeout-seconds` (default: 300)
- `--max-iterations` (default: 20)
- `--max-steps` (default: 80)
- `--inspect` (enable JSONL trace capture)
- `--inspect-level summary|full` (default: `summary`)
- `--trace-dir <dir>` (default: `./traces`)
- `--print-iterations` (live concise iteration/subcall progress)
- `--experiment <name>` and repeated `--tag key=value`

## Testing

```bash
./test.sh --local
```

or directly:

```bash
uv pip install --python .venv/bin/python -e .[dev]
.venv/bin/python -m pytest -q
```

## Known limitations

- `llm_query()` timeouts use thread futures. A timed-out subcall thread may continue running briefly.
- Dynamic per-subcall model override is passed through as metadata but may not be honored by all model/profile setups.
