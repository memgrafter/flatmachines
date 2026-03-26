# DFSS Pipeline Example

This example has been normalized to the standard SDK example layout:

- `python/` — runnable Python package, tests, and scripts
- top-level wrappers (`main.py`, `scheduler.py`, etc.) are kept for backward compatibility

## Quick start

```bash
cd sdk/examples/dfss_pipeline/python
./run.sh --local --roots 8 --max-depth 3 --max-workers 4 --seed 7 --db-path data/dfss.sqlite
```

For full usage and behavior details, see:

- `python/README.md`
