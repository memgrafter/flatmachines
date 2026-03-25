# JS Parity Priority Queue (Python = Golden)

Timestamp: 2026-03-24T23:26:00

Goal: keep JS examples using the **same shared `config/` machines, agents, and profiles** as Python examples.

---

## 1) Existing JS examples ordered by implementation simplicity

(Ordered by expected LLM call volume + session/state-management complexity)

1. `error_handling`
2. `support_triage_json`
3. `dynamic_agent`
4. `human-in-the-loop`
5. `peering`
6. `writer_critic`
7. `helloworld`
8. `parallelism`
9. `research_paper_analysis`
10. `story_writer`
11. `character_card`
12. `custom_coding_workflow`
13. `coding_machine_cli`
14. `rlm`
15. `multi_paper_synthesizer`
16. `mdap`
17. `gepa_self_optimizer`

---

## 2) Recommended parity update order (fastest wins first)

### Wave A — very fast parity checks
- `error_handling`
- `support_triage_json`
- `dynamic_agent`
- `human-in-the-loop`

### Wave B — medium complexity
- `peering`
- `writer_critic`
- `helloworld`
- `parallelism`
- `research_paper_analysis`
- `story_writer`

### Wave C — high complexity / high churn risk
- `character_card`
- `custom_coding_workflow`
- `coding_machine_cli`
- `rlm`
- `multi_paper_synthesizer`
- `mdap`
- `gepa_self_optimizer`

---

## 3) Parity checklist to apply to each JS example

- JS entrypoint loads machine/agent config from the same shared `../config/` used by Python.
- No JS-only shadow copies of machine/agent/profile config unless explicitly intentional.
- `profiles.yml` (or JSON variant where that example is JSON-native) is shared and consistent.
- JS run path exercises the same primary machine topology as Python (same machine file, same peer machines, same agents).
- Any JS helper logic (hooks/parsers/wrappers) does not change workflow semantics relative to Python golden tests.

---

## 4) Missing JS folders (backlog after parity on existing JS)

Current missing JS examples:
- `claude_code_adapter`
- `codex_cli_adapter`
- `coding_agent_cli`
- `dfss_deepsleep`
- `dfss_pipeline`
- `distributed_worker`
- `listener_os`
- `openai_codex_oauth`
- `tool_loop`

Suggested creation order (low to high complexity, provisional):
1. `coding_agent_cli`
2. `tool_loop`
3. `claude_code_adapter`
4. `codex_cli_adapter`
5. `openai_codex_oauth`
6. `dfss_deepsleep`
7. `distributed_worker`
8. `dfss_pipeline`
9. `listener_os`
