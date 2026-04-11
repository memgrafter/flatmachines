# Expert Debate (FlatMachine)

Interactive machine that:
1. Collects/refines debate setup from the user via quiz loop,
2. Runs a two-master multi-round educational debate,
3. Calls a **non-LLM recorder machine** to produce a markdown transcript.

## Run

```bash
cd sdk/examples/expert_debate/python
./run.sh --local --topic "What is intelligence?" --round-count 5

# Debug logs
./run.sh --local --debug --topic "What is intelligence?"
```

If `--topic` is omitted, you'll be prompted.

## Output

Markdown transcript is written to:

- `sdk/examples/expert_debate/output/`

(or `--output-dir` if provided).
