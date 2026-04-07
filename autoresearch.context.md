# Autoresearch Context — Self-Improving flatmachines_cli

## Source Analysis

### HyperAgents (Meta Research, ~/clones/HyperAgents/)

**What it is**: A self-referential self-improving agent system from Meta. An LLM agent (the "meta agent") modifies its own codebase to improve at solving tasks, then gets evaluated, and the cycle repeats.

**Architecture** (3 layers):

1. **generate_loop.py** — The outer loop. Runs generations in sequence:
   - Select parent from archive (score-proportional or random)
   - Spin up Docker container with the codebase
   - Apply lineage diffs (all ancestor patches)
   - Run meta agent to produce code changes (diff)
   - Evaluate the modified agent on task benchmarks
   - Staged evaluation: small sample first, full eval only if promising
   - Update archive, select next parent, repeat

2. **meta_agent.py** — Extremely simple. 7 lines of real code:
   ```python
   class MetaAgent(AgentSystem):
       def forward(self, repo_path, eval_path, iterations_left=None):
           instruction = f"Modify any part of the codebase at `{repo_path}`."
           chat_with_agent(instruction, model=self.model, tools_available='all')
   ```
   The meta agent gets the repo path, the eval results folder, and a tool-use chat loop. That's it. The LLM decides what to change.

3. **task_agent.py** — The agent being improved. Also simple — takes task input, calls LLM, returns prediction. This is what the meta agent modifies.

**Key design decisions**:
- **Docker isolation**: Every generation runs in a fresh container. Changes can't corrupt the host.
- **Diff-based lineage**: Changes stored as git diffs, not full snapshots. Ancestors' diffs applied in order.
- **Archive with parent selection**: Not just latest — score-proportional selection across all generations. Enables exploring from any promising ancestor.
- **Staged evaluation**: Small sample first (fast, cheap). Full eval only if staged eval passes a threshold. Saves compute.
- **Tools**: Just `bash` and `editor` (view/create/str_replace/insert/undo_edit). The editor has undo history.
- **The meta agent is the LLM itself**: No orchestration logic for what to analyze or implement. One instruction: "Modify any part of the codebase." The LLM figures out what to do by reading eval results and code.

**What's remarkable**: The meta agent has zero domain knowledge. It gets told "modify the codebase" and figures out improvements by reading evaluation results from previous generations. The entire self-improvement logic lives in the LLM's reasoning, not in code.

### pi-autoresearch (~/.pi/agent/git/github.com/davebcn87/pi-autoresearch/)

**What it is**: A pi extension (2,575 lines TypeScript) that turns any pi coding session into an autonomous experiment loop.

**Architecture**: 
- **3 tools**: `init_experiment`, `run_experiment`, `log_experiment`
- **A skill prompt** (SKILL.md): Teaches the LLM agent the experiment loop pattern
- **The LLM agent IS the loop**: It reads code, hypothesizes, implements, benchmarks, keeps/discards

**Key design decisions**:
- **No orchestration code**: The loop is the LLM calling tools in sequence, guided by the skill prompt
- **JSONL persistence**: Append-only log with config headers and experiment entries
- **Segments**: Re-init without losing history (new baseline, old results stay)
- **Context management**: Tracks token usage, auto-stops before exhaustion, auto-resumes with fresh context
- **Backpressure checks**: Optional `autoresearch.checks.sh` runs after every passing benchmark
- **Confidence scoring**: MAD-based (Median Absolute Deviation) — robust to outliers
- **Git integration**: `keep` auto-commits via changeset_commit, `discard`/`crash` auto-reverts
- **TUI dashboard**: Collapsible widget with experiment table, spinner, metrics

**Core insight shared by both systems**: The LLM is the agent. You give it tools (bash, edit, run_experiment) and context (eval results, code), and it figures out what to improve. You don't need to code an analyze→implement→evaluate state machine — the LLM does that naturally when given the right tools and instructions.

## Implications for flatmachines_cli

The current implementation (experiment.py, improve.py, self_improve.yml) over-engineered the orchestration. It built:
- A `SelfImprover` class that wraps experiment tracking
- A `SelfImproveHooks` class for FlatMachine action dispatch  
- An `ImprovementRunner` class for programmatic loops
- An 8-state FlatMachine config describing analyze→implement→evaluate→archive

But neither HyperAgents nor pi-autoresearch have orchestration code for the improvement loop. Both rely on the LLM to drive the cycle.

**What flatmachines_cli actually needs to be a self-improving coding machine**:
1. Work as a coding machine with any adapter (✓ already does this via backend/frontend/hooks/bus)
2. Provide experiment tracking tools the agent can call (experiment.py has the logic, but it's a library not tools)
3. The agent configs (analyzer.yml, implementer.yml) should give the agent bash+edit tools and context about eval results — like HyperAgents does
4. The self_improve.yml machine config should have the agent states use tool_loop (like coding_machine_cli) so the LLM can call tools freely

**The gap**: experiment.py is a library. It should expose its functionality as tools the coding agent can call during a tool_loop, similar to how bash.py and edit.py work in HyperAgents.
