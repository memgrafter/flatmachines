# Research Paper Analysis Pipeline

A **production-quality** machine topology demo with **2 peer machines**, **5 agents**, and a **self-judging improvement loop**.

Analyzes the full "Attention Is All You Need" paper (40KB, 15 pages) without truncation.

## Features Demonstrated

- **Machine Peering**: Main machine launches and coordinates 2 peer machines
- **Self-Judging Loop**: Summary refined until quality score ≥ 8/10
- **Multi-Agent Pipeline**: 5 specialized agents across machines
- **Automatic PDF Download**: Downloads from arXiv if not present
- **Formatted Output**: Saves markdown report to `data/analysis_report.md`

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    MAIN: research-pipeline                          │
│                                                                      │
│   ┌─────────┐     ┌───────────────────┐     ┌──────────────────┐   │
│   │  start  │ ──▶ │     analyze       │ ──▶ │      refine      │   │
│   └─────────┘     │  (peer machine)   │     │  (peer machine)  │   │
│                   └───────────────────┘     └──────────────────┘   │
│                           │                         │              │
│                           ▼                         ▼              │
│                   ┌───────────────────┐     ┌──────────────────┐   │
│                   │ PEER: analyzer    │     │ PEER: refiner    │   │
│                   │                   │     │ (self-judging)   │   │
│                   │ ├─ abstract_      │     │                  │   │
│                   │ │  analyzer       │     │ ├─ synthesizer   │   │
│                   │ │                 │     │ │    ↓           │   │
│                   │ └─ section_       │     │ ├─ critic        │   │
│                   │    analyzer       │     │ │    ↓ (loop)    │   │
│                   └───────────────────┘     │ └─ until         │   │
│                                             │    quality ≥ 8   │   │
│                   ┌───────────────────┐     └──────────────────┘   │
│                   │     format        │ ◀──────────────────────────│
│                   │   (agent only)    │                            │
│                   └───────────────────┘                            │
│                           │                                        │
│                   ┌───────────────────┐                            │
│                   │       done        │                            │
│                   │  (save report)    │                            │
│                   └───────────────────┘                            │
└────────────────────────────────────────────────────────────────────┘
```

## Agents

| Agent | Role | Machine |
|-------|------|---------|
| `abstract_analyzer` | Extracts findings, methodology, contributions | analyzer |
| `section_analyzer` | Extracts technical details, results | analyzer |
| `synthesizer` | Creates/improves executive summary | refiner |
| `critic` | Judges quality, suggests improvements | refiner |
| `formatter` | Creates markdown report | main |

## Self-Judging Loop

The `refiner` peer machine implements a quality improvement loop:

1. **Synthesize**: Create summary (or improve based on critique)
2. **Critique**: Rate quality 1-10, identify weaknesses
3. **Decision**: 
   - If quality ≥ 8 → done
   - If iterations < 3 → loop back to synthesize
   - If iterations ≥ 3 → done (max attempts)

Typical runs: 2-3 iterations to reach quality threshold.

## Quick Start

```bash
export CEREBRAS_API_KEY="your-key"
./run.sh
```

## Example Output

```
Title: Attention Is All You Need
Quality Score: 9/10
Citations Found: 40
Summary Preview: This paper addresses the limitations of dominant sequence 
transduction models...

📄 Report saved to: data/analysis_report.md

--- Statistics ---
Execution ID: 84e54fa3-6825-4729-a153-a59460282af0
Total API calls: 10
Estimated cost: $0.02
```

## Output Files

```
data/
├── attention_is_all_you_need.pdf  # Paper (auto-downloaded)
├── attention_is_all_you_need.txt  # Extracted text (generated)
└── analysis_report.md             # Final formatted report
```

## API Call Budget

With self-judging loop, typically uses 8-12 API calls:
- Abstract analyzer: 1
- Section analyzer: 1  
- Synthesize/Critique loop: 4-8 (2-3 iterations × 2 agents)
- Formatter: 1

Budget of 25 calls allows for worst case of 3 full improvement iterations.

## Files

```
config/
├── machine.yml              # Parent pipeline
├── analyzer_machine.yml     # Child: content analysis
├── refiner_machine.yml      # Child: self-judging loop
├── abstract_analyzer.yml    # Agent: abstract analysis
├── section_analyzer.yml     # Agent: section analysis
├── synthesizer.yml          # Agent: summary creation
├── critic.yml               # Agent: quality judgment
└── formatter.yml            # Agent: markdown formatting
```
