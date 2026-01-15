# Dynamic Agent Example

Demonstrates **On-The-Fly (OTF) agent generation** with pre-execution supervision and human-in-the-loop review.

## What It Does

1. **Generator Agent** creates a specialized writing agent based on your task
2. **Supervisor Agent** analyzes the generated spec BEFORE execution
3. **Human Review** with conditional options:
   - If supervisor **approved**: You can approve or deny
   - If supervisor **rejected**: You can only acknowledge (no override)
4. **OTF Agent** executes if approved, otherwise loops back with feedback

## Flow Diagram

```
┌─────────────────┐
│     Start       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate Agent  │◄──────────────────┐
│   (generator)   │                   │
└────────┬────────┘                   │
         │                            │
         ▼                            │
┌─────────────────┐                   │
│ Supervise Spec  │                   │
│  (supervisor)   │                   │
└────────┬────────┘                   │
         │                            │
         ▼                            │
┌─────────────────┐                   │
│  Human Review   │                   │
│ (conditional)   │                   │
└────────┬────────┘                   │
         │                            │
    ┌────┴────┐                       │
    │         │                       │
    ▼         ▼                       │
Approved   Rejected ──────────────────┘
    │
    ▼
┌─────────────────┐
│  OTF Execute    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│      Done       │
└─────────────────┘
```

## Usage

```bash
# Default task (haiku about mountains)
./run.sh --local

# Custom task
./run.sh --local "Write a limerick about a programmer's coffee addiction"

# With style hints
./run.sh --local "Write a short story opening" --style "noir detective"
```

## Key Files

| File | Purpose |
|------|---------|
| `config/machine.yml` | Machine orchestration with supervision flow |
| `config/generator.yml` | Agent that generates OTF agent specs |
| `config/supervisor.yml` | Pre-execution validation of specs |
| `src/dynamic_agent/hooks.py` | Human review + OTF execution logic |

## Human Review Flow

### When Supervisor Approves ✅

```
══════════════════════════════════════════════════════════════════════
OTF AGENT REVIEW
══════════════════════════════════════════════════════════════════════

📋 ORIGINAL TASK:
   Write a haiku about mountain sunrises

🤖 GENERATED AGENT: haiku-master
──────────────────────────────────────────────────────
Temperature: 0.8
System Prompt: You are a master of haiku poetry...
User Prompt Template: {{ input.task }}

✅ SUPERVISOR APPROVED

📊 ANALYSIS:
The agent has appropriate expertise in haiku form...

Your decision: [a]pprove / [d]eny / [q]uit: _
```

### When Supervisor Rejects ❌

```
❌ SUPERVISOR REJECTED

📊 ANALYSIS:
The agent lacks specific haiku expertise...

⚠️  CONCERNS:
Temperature too low for creative poetry. System prompt
doesn't mention 5-7-5 syllable structure.

The supervisor rejected this agent. You can only acknowledge.
Press Enter to acknowledge and regenerate, or 'q' to quit: _
```

## Example Output

```
══════════════════════════════════════════════════════════════════════
FINAL RESULT
══════════════════════════════════════════════════════════════════════

📝 Content:
Mountain peaks aglow
Pink fingers touch sleeping snow
Day begins to breathe

📊 Attempts: 1

📈 Metrics:
   agents_generated: 1
   agents_executed: 1
   supervisor_rejections: 0
   human_denials: 0
```

## OTF Pattern Benefits

1. **Specialization**: Each task gets a tailored agent, not a generic one
2. **Safety**: Supervisor catches problematic specs before execution
3. **Human Oversight**: Final approval with appropriate authority levels
4. **Iterative Refinement**: Feedback loops improve agent design

## Related

- [ON_THE_FLY_AGENTS.md](../../../../strategies/ON_THE_FLY_AGENTS.md) - Full strategy documentation
- [human_in_loop](../human_in_loop/) - Simpler human approval example
