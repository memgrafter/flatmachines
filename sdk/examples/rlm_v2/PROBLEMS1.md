
 Clear breakdown

 ┌─────────────────────────────────────┬───────────────────────────────────┬──────────────────────────────┬──────────────────────────────────────────────────┐
 │ Problem / Artifact                  │ Recommendation                    │ In Paper?                    │ Why / Other context                              │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ NameError: dir is not defined in    │ Add dir to safe builtins or       │ No (implementation-specific) │ This came from our sandboxed REPL builtins, not  │
 │ REPL                                │ prompt model not to use it        │                              │ RLM theory                                       │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ Repeated print(context) loops       │ Add anti-loop guidance +          │ Partial                      │ Paper discusses brittle trajectories / prompt    │
 │ across iterations                   │ loop-detection hint after N       │                              │ sensitivity, but not this exact runtime symptom  │
 │                                     │ repeated code patterns            │                              │                                                  │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ 0 subcalls (llm_query) used in this │ Add explicit subcall-use policy   │ Partial                      │ Paper encourages subcalls heavily; does not      │
 │ run                                 │ in prompt and nudge after         │                              │ guarantee every trajectory will use them         │
 │                                     │ no-subcall iterations             │                              │                                                  │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ events.jsonl, manifest.json,        │ Keep and expand (summary metrics  │ No                           │ This is our research instrumentation layer, not  │
 │ --inspect, --print-iterations       │ + anomaly flags)                  │                              │ from paper implementation                        │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ Sentinel values (SUBCALL_TIMEOUT,   │ Keep standardized sentinels and   │ No                           │ Operational convention for                       │
 │ SUBCALL_CONFIG_NOT_FOUND)           │ document meanings                 │                              │ debuggability/reliability                        │
 ├─────────────────────────────────────┼───────────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────────────┤
 │ Strict Final variable termination   │ Keep (current), optionally        │ Yes (Algorithm 1) / Appendix │ Algorithm 1 says stop on REPL Final; appendix    │
 │                                     │ support tag mode later            │ differs                      │ prompt examples also use FINAL()/FINAL_VAR()     │
 │                                     │                                   │                              │ tags in some setups                              │
 └─────────────────────────────────────┴───────────────────────────────────┴──────────────────────────────┴──────────────────────────────────────────────────┘

 ────────────────────────────────────────────────────────────────────────────────

 Bottom line

 - Core loop (persistent REPL + recursive callable + final variable): paper-aligned.
 - Errors/signals/inspect plan: mostly our custom engineering layer.
 - Observed failure modes (looping, brittle behavior): consistent with paper’s negative-results spirit, but not prescribed artifacts.


