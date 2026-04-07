# Deep Analysis: Autoresearch (Karpathy)

> Source: `~/clones/autoresearch/`  
> Author: Andrej Karpathy  
> Core insight: *The human writes the research program, the agent executes it autonomously.*

---

## 1. What It Is

Autoresearch is an autonomous LLM pretraining research loop. An AI agent modifies `train.py` (a GPU training script) to try to get lower validation loss (val_bpb), running 5-minute training experiments back-to-back. Overnight, it does ~100 experiments while you sleep.

The entire system is three files:
- `prepare.py` — fixed evaluation/data code (untouchable)
- `train.py` — the single file the agent edits (architecture, optimizer, hyperparams)
- `program.md` — the instructions that tell the agent how to operate

---

## 2. The Core Features That Make It Tick

### 2.1. Fixed Time Budget as the Universal Comparator

**This is the single most important design decision.** Every experiment trains for exactly 5 minutes of wall-clock time, regardless of what the agent changed. This means:

- **Model size changes are automatically comparable.** If the agent doubles the model width, it trains fewer steps but the same wall time. The metric (val_bpb) is all that matters.
- **No confounding variables.** There is no "but it trained longer" — everything is apples-to-apples.
- **No separate cost tracking needed.** Time IS the cost, and it's fixed.
- **The agent can't game duration.** It can't "train longer" to improve — it must find actual algorithmic improvements.

This is fundamentally different from "run tests and see if they pass" or "run a benchmark and compare scores." The fixed budget creates a **closed optimization surface** where the agent can search efficiently.

**What flatmachines_cli is missing:** Our `benchmark_command` is open-ended. The agent can accidentally create longer benchmarks, or benchmarks that score well but take 10× longer. There's no budget-normalized comparison.

### 2.2. Single File Scope

The agent only edits `train.py`. This is intentional friction that produces benefits:

- **Diffs are reviewable.** You can see exactly what changed.
- **The search space is bounded.** The agent can't wander into editing build configs, CI pipelines, or documentation.
- **Rollback is trivial.** `git reset --hard` undoes everything.
- **The agent can read the whole file in context.** No need for codebase exploration — everything fits in one file.

**What flatmachines_cli is missing:** Our `coder.yml` agent can edit anything in `target_dir`. There's no scoping mechanism to focus the agent on specific files.

### 2.3. The `program.md` Pattern — Human Programs the Agent

This is the insight the README calls out explicitly: *"you're not touching any of the Python files like you normally would as a researcher. Instead, you are programming the `program.md` Markdown files."*

`program.md` is not just instructions — it's a **research strategy encoded as text**. It defines:

1. **The exact loop protocol**: commit → run → grep results → keep/discard → repeat
2. **Output format expectations**: The agent knows to `grep "^val_bpb:"` 
3. **Decision rules**: "If val_bpb improved (lower), advance the branch. If equal or worse, git reset"
4. **Failure handling**: "If it's a dumb bug, fix it. If fundamentally broken, skip it and move on"
5. **Never-stop mandate**: "Do NOT pause to ask the human. The loop runs until manually stopped."
6. **Logging format**: Tab-separated, specific columns, specific semantics

The human iterates on `program.md` over time, creating a meta-optimization loop where you're optimizing the research program itself.

**What flatmachines_cli is missing:** Our `self_improve.yml` has a generic prompt. There's no equivalent of the `program.md` pattern where the human encodes domain-specific research strategy. The agent gets generic instructions like "analyze the code and identify the highest-impact improvement" rather than a concrete protocol.

### 2.4. Branch-Based State Management

The experiment loop lives on a git branch (`autoresearch/<tag>`):

```
git checkout -b autoresearch/mar5
```

State is the branch tip. If an experiment improves val_bpb, the commit stays (branch advances). If not, `git reset --hard` rewinds to the last good state. This gives you:

- **Perfect reproducibility**: Any commit on the branch is a runnable experiment
- **No separate state database**: Git IS the state
- **Easy comparison**: `git diff commit1..commit2` shows exactly what improved
- **Multiple parallel runs**: Different branches = different experiments in parallel

**What flatmachines_cli is missing:** We have an experiments.jsonl log but no branch-based state management. Our git_commit/git_revert is there but not structured around branches.

### 2.5. Fixed, Vocab-Independent Metric

val_bpb (validation bits per byte) is specifically designed so that:
- Vocabulary size changes don't affect the metric
- It's computed on a fixed validation set
- The evaluation function is in `prepare.py` (untouchable)
- The agent literally cannot game the metric — it can only improve it

**What flatmachines_cli is missing:** Our `benchmark_command` is user-defined and the agent runs it. The agent could potentially modify the benchmark or its interpretation. There's no separation between "the thing being optimized" and "the measurement apparatus."

### 2.6. Redirect-and-Grep Output Pattern

```bash
uv run train.py > run.log 2>&1  # Don't flood context
grep "^val_bpb:\|^peak_vram_mb:" run.log  # Extract only what matters
```

This is operationally critical:
- Training output is **gigabytes**. Putting it in the agent's context would destroy performance.
- The structured output format (`val_bpb: 0.997900`) makes parsing trivial
- If grep returns empty → crash → `tail -n 50 run.log` for the stack trace

**What flatmachines_cli is missing:** Our experiment runner captures full stdout/stderr. No log-redirect-and-grep pattern. The agent sees everything, which wastes context.

### 2.7. The "Never Stop" Mandate

`program.md` explicitly states: *"The human might be asleep... you are autonomous. If you run out of ideas, think harder... The loop runs until the human interrupts you, period."*

This creates true autonomy. The agent doesn't ask for permission, doesn't pause between experiments, doesn't say "should I continue?" It just runs.

**What flatmachines_cli is missing:** Our `max_iterations: 10` and `max_steps: 100` are finite limits. There's no never-stop mode.

### 2.8. Results.tsv as Append-Only Ground Truth

```
commit    val_bpb     memory_gb   status    description
a1b2c3d   0.997900    44.0        keep      baseline
b2c3d4e   0.993200    44.2        keep      increase LR to 0.04
```

Key properties:
- **Untracked by git** — it survives resets
- **Tab-separated** — parseable by the agent
- **Contains the full story** — every attempt, including failures
- **Short descriptions** — force the agent to summarize what it tried

This is the agent's institutional memory. It reads this before each experiment to avoid repeating past failures.

**What flatmachines_cli is missing:** We have experiments.jsonl but it's complex JSON. The autoresearch pattern of a simple TSV that the agent reads with `cat results.tsv` is simpler and more effective.

---

## 3. What Autoresearch Does NOT Have

- **No archive of multiple surviving variants** — only the latest best survives
- **No parent selection** — always builds on the latest best (linear, not tree)
- **No self-referential improvement** — the agent doesn't modify its own instructions
- **No Docker isolation** — runs directly on the machine
- **No ensemble** — single lineage, single winner
- **No multi-domain evaluation** — one metric only
- **No staged evaluation** — always runs the full 5-minute training

---

## 4. Key Principles Extracted

| Principle | Autoresearch Implementation | flatmachines_cli Gap |
|-----------|---------------------------|---------------------|
| **Fixed evaluation budget** | 5 min wall-clock, always | Open-ended benchmark command |
| **Untouchable evaluator** | `prepare.py` is read-only | Agent can modify anything |
| **Single optimization target** | `train.py` only | No file scoping |
| **Human-authored research program** | `program.md` | Generic agent prompt |
| **Branch-based experiments** | git branches per session | JSONL log only |
| **Structured metric output** | `val_bpb: X.XXXXXX` format | METRIC lines (exists, good) |
| **Log-redirect-and-grep** | `> run.log 2>&1` then grep | Full stdout capture |
| **Never-stop autonomy** | Explicit in program.md | Finite iteration limits |
| **Simple append-only history** | TSV, untracked | Complex JSONL |
| **Simplicity criterion** | "simpler is better, all else equal" | Not encoded |

---

## 5. The Meta-Insight

Autoresearch works because it creates a **perfectly closed optimization loop**:

1. The metric is fixed and ungameable
2. The budget is fixed and fair
3. The scope is narrow and bounded
4. The protocol is explicit and mechanical
5. The state management is simple and reliable

The agent doesn't need to be smart about research strategy — the `program.md` handles that. The agent just needs to be good at code editing and following instructions. The _system design_ does the heavy lifting, not the agent's intelligence.

**The most portable lesson for flatmachines_cli:** Separate the evaluation infrastructure from the code being improved. Make the metric fixed, the budget fixed, and the scope narrow. The agent should never be able to modify the measurement apparatus.
