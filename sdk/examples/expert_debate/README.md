# Expert Debate Example

This example implements an `expert_debate` FlatMachine with:

- **User refinement loop** (topic + iterative quiz until satisfied),
- **Two-master debate loop** (fixed round count, 1/N topical pacing),
- **Non-LLM recorder child machine** that writes a markdown dialogue file.

## Config files

- `config/machine.yml` — main orchestration
- `config/recorder_machine.yml` — non-LLM recorder section
- `config/quiz_master.yml` — asks one high-leverage quiz question
- `config/quiz_refiner.yml` — updates structured debate config
- `config/topic_slicer.yml` — plans round topic slices
- `config/master_a.yml`, `config/master_b.yml` — debate participants

## Python runner

See `python/README.md`.
