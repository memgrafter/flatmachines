# SDK Inconsistencies

- **JS FlatMachine metrics not exposed**: Python examples access `machine.total_api_calls` and `machine.total_cost` (e.g., `support_triage_json/python`). The JS SDK `FlatMachine` does not expose equivalent fields, so JS demos cannot print stats without SDK changes (types define `MachineSnapshot.total_api_calls/total_cost`, but runtime does not surface them).
- **Missing `tojson` filter in JS templating**: Several configs use `| tojson` (e.g., `support_triage_json/config/machine.json`, `story_writer/config/machine.yml`, `dynamic_agent/config/machine.yml`). The JS SDK uses Nunjucks without registering a `tojson` filter, which likely raises an "unknown filter" error at runtime.
- **Missing Jinja filters in JS templating**: RLM config uses filters like `dictsort`, `map`, and `list` (e.g., `rlm/config/machine.yml` `output_to_context` for `sub_task_results`). The JS SDK uses plain Nunjucks without these filters, so these templates likely fail or render incorrectly.
