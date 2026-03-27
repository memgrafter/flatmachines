# DFSS Pipeline Example (JavaScript)

JS parity implementation for the DFSS pipeline demo.

This example uses inline task machine config plus SQLite work/checkpoint backends,
matching the Python demo behavior.

## Run

```bash
cd sdk/examples/dfss_pipeline/js
./run.sh --local --roots 6 --max-depth 3 --seed 7 --fail-rate 0 --db-path data/dfss.sqlite
./run.sh --local --resume --db-path data/dfss.sqlite
```
