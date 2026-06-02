# JS Example Implementation Checklist (Easiest → Hardest)

The checklist below is ordered by **implementation effort and risk**, from the most straightforward wrappers (simple FlatMachine runners) to the most complex examples (custom hooks, REPLs, PDF parsing, or algorithmic orchestration). Use this ordering to shard work across multiple folks with minimal merge conflicts.

## 1) error_handling (easiest)
- [x] Create `error_handling/js/` folder
- [x] Add `package.json`, `tsconfig.json`, `run.sh`, `README.md`
- [x] Implement `error_handling/js/src/error_handling/main.ts`
  - [x] Load `../config/machine.yml` via `FlatMachine`
  - [x] Execute with input `{ task: "Analyze market trends" }`
  - [x] Log success/failure summary (mirrors Python)

## 2) writer_critic
- [x] Create `writer_critic/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `writer_critic/js/src/writer_critic/main.ts`
  - [x] Load `../config/machine.yml`
  - [x] Run with `product`, `max_rounds`, `target_score`
  - [x] Log final tagline, score, rounds
- [x] README: usage + args

## 3) support_triage_json
- [x] Create `support_triage_json/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `support_triage_json/js/src/support_triage_json/main.ts`
  - [x] Load `../config/machine.json`
  - [x] Execute with sample input from Python demo
  - [x] Print result + stats
- [x] README: JSON config note

## 4) story_writer
- [x] Create `story_writer/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `story_writer/js/src/story_writer/main.ts`
  - [x] Load `../config/machine.yml` (persistence enabled)
  - [x] Run with `genre`, `premise`, `num_chapters`
  - [x] Flatten nested JSON string chapters
  - [x] Save output to `output/<title>.md`
- [x] README: resume/persistence note

## 5) dynamic_agent
- [x] Create `dynamic_agent/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `dynamic_agent/js/src/dynamic_agent/hooks.ts`
  - [x] `human_review_otf` (approve/deny/ack)
  - [x] `otf_execute` (construct FlatAgent from context spec)
- [x] Implement `dynamic_agent/js/src/dynamic_agent/main.ts`
  - [x] Load `../config/machine.yml` and pass hooks
  - [x] Run default task + optional `--style`
- [x] Ensure temperature + output_fields handling matches Python

## 6) character_card
- [x] Create `character_card/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `character_card/js/src/character_card/card_parser.ts`
  - [x] PNG chunk parsing for `tEXt`/`iTXt` keyword `chara`
  - [x] Base64 decode to JSON
  - [x] JSON file support + V1/V2/V3 normalization
- [x] Implement `character_card/js/src/character_card/hooks.ts`
  - [x] Actions: `load_card`, `show_greeting`, `get_user_input`, `update_chat_history`
  - [x] Auto-user mode (load `config/user_agent.yml` as FlatAgent)
- [x] Implement `character_card/js/src/character_card/main.ts` (CLI)
- [x] README: persona/messages files + usage

## 7) coding_agent
- [x] Create `coding_agent/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `coding_agent/js/src/coding_agent/hooks.ts`
  - [x] Actions: `explore_codebase`, `run_tree`, `run_ripgrep`, `read_file`, `read_plan_files`, `human_review_plan`, `human_review_result`, `apply_changes`
  - [x] SEARCH/REPLACE diff parser + safe apply
  - [x] Path boundary checks + single-match enforcement
- [x] Implement `coding_agent/js/src/coding_agent/main.ts` (CLI)
- [x] Decide config strategy (use same YAML + pass JS hooks, or copy config)
- [x] README: CLI flags + safety behavior

## 8) mdap
- [x] Create `mdap/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `mdap/js/src/mdap/mdap.ts`
  - [x] First-to-ahead-by-k voting
  - [x] Regex parsing from metadata + JSON parse
  - [x] Schema validation (Ajv)
  - [x] Red-flag tracking + metrics
- [x] Implement `mdap/js/src/mdap/demo.ts`
  - [x] Load `config/hanoi.yml`
  - [x] Run Hanoi loop + print stats
- [x] README: MDAP config + expected output

## 9) rlm
- [x] Create `rlm/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `rlm/js/src/rlm/repl.ts`
  - [x] Sandboxed REPL using `vm`
  - [x] Provide `INPUT`, safe builtins, stdout capture
- [x] Implement `rlm/js/src/rlm/hooks.ts`
  - [x] Actions: `init_repl`, `execute_repl`, `extract_chunk`, `log_error`, `log_chunk_error`
- [x] Implement `rlm/js/src/rlm/main.ts` (CLI + demo)
- [x] Config strategy: JS-friendly hook config or override at runtime

## 10) research_paper_analysis
- [x] Create `research_paper_analysis/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement `pdf.ts` for download + cached extraction (`data/`)
- [x] Implement `parse.ts` (regex parse of title/authors/sections/refs)
- [x] Implement `main.ts` (load machine, save report)
- [x] README: notes on PDF extraction deps

## 11) multi_paper_synthesizer
- [x] Create `multi_paper_synthesizer/js/` folder
- [x] Add standard JS scaffolding files
- [x] Implement PDF download/extract + programmatic parsing for multiple papers
- [x] Implement per-paper analysis via peer machine
- [x] Implement synthesis loop + critique + formatter
- [x] Save `data/synthesis_report.md`
- [x] README: pipeline overview + dependency notes

## 12) gepa_self_optimizer (hardest)
- [x] Create `gepa_self_optimizer/js/` folder
- [x] Add standard JS scaffolding files
- [x] Port algorithm modules:
  - [x] `optimizer.ts`
  - [x] `data_generator.ts`
  - [x] `evaluator.ts`
  - [x] `prompt_evolver.ts`
  - [x] `utils.ts` (YAML/JSON load/save)
- [x] Implement `main.ts` CLI (`run`, `generate-data`, `evaluate`, `optimize`)
- [x] Use FlatAgents for all LLM calls (judge, generator, updater, summary)
- [x] Ensure `data/` + `output/` artifacts match Python behavior
