# Multi-Paper Research Synthesizer

A **meta-example** that orchestrates multiple paper analyses and synthesizes insights across documents.

## Features Demonstrated

- **Machine Composition**: Uses `paper_analyzer` as a reusable peer machine
- **Multi-Document Synthesis**: Compares findings, identifies gaps, creates unified narrative
- **Self-Judging Loop**: Refines synthesis until quality score ≥ 8/10
- **Cross-Paper Analysis**: Common themes, key differences, research gaps

## Architecture

```
multi_paper_synthesizer/
├── config/
│   └── machine.yml              # Main orchestrator
├── paper_analyzer/
│   └── config/                  # Reused from research_paper_analysis
│       ├── machine.yml          # Peer machine
│       └── *.yml                # Agents
├── data/
│   ├── papers/                  # Downloaded PDFs
│   └── synthesis_report.md      # Final output
└── src/
    └── multi_paper_synthesizer/
        └── main.py              # Entry point
```

## Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                   MULTI-PAPER SYNTHESIZER                       │
│                                                                 │
│   Paper 1 ─┐                                                    │
│   Paper 2 ─┼─▶ [paper_analyzer x N] ─▶ analyses ─┐              │
│   Paper 3 ─┘                                     │              │
│                                                  ▼              │
│                              ┌─────────────────────────────┐    │
│                              │    SYNTHESIS PIPELINE       │    │
│                              │                             │    │
│                              │  comparator ─▶ gap_finder   │    │
│                              │       │            │        │    │
│                              │  ┌────▼────────────▼─────┐  │    │
│                              │  │   synthesizer          │  │    │
│                              │  │         ↕              │  │    │
│                              │  │      critic            │  │    │
│                              │  │   (loop until 8+)      │  │    │
│                              │  └───────────────────────┘  │    │
│                              │            │                │    │
│                              │     formatter               │    │
│                              └─────────────────────────────┘    │
│                                           │                     │
│                                synthesis_report.md              │
└─────────────────────────────────────────────────────────────────┘
```

## Default Papers (Prompt Optimization Research)

| Paper | Topic |
|-------|-------|
| **GEPA** (2507.19457) | Reflective prompt evolution via reflection |
| **MIPRO** (2406.11695) | DSPy multi-prompt instruction optimization |
| **TextGrad** (2406.07496) | Automatic differentiation via text |

## Research Question

> "What are the most effective techniques for optimizing LLM prompts, 
> and how do gradient-free methods like GEPA compare to gradient-based approaches?"

## Quick Start

```bash
export CEREBRAS_API_KEY="your-key"
./run.sh --local
```

## Output

The synthesizer produces:
- **Common Themes**: Patterns across all papers
- **Key Differences**: Where approaches diverge
- **Research Gaps**: Unanswered questions
- **Opportunities**: Future research directions
- **Synthesis Report**: Unified markdown document

## Agents

| Agent | Role |
|-------|------|
| `comparator` | Cross-paper comparison |
| `gap_finder` | Research gap identification |
| `synthesizer` | Unified narrative creation |
| `critic` | Quality evaluation |
| `formatter` | Markdown formatting |

## API Call Budget

Typical run: ~25 API calls
- 3 papers × 3 calls per analysis = 9
- Comparator: 1
- Gap finder: 1
- Synthesizer + Critic loop: 4-8
- Formatter: 1

Total: 16-20 calls (within 25 budget)
