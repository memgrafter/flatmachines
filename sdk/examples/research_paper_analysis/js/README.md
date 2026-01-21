# Research Paper Analysis (JavaScript)

Production-quality demo that downloads a paper, extracts text, parses structure programmatically, and runs a multi-stage analysis pipeline.

## Prerequisites

1. **Node.js & npm**: Node.js 16+ and npm installed.
2. **LLM API Key**: This demo uses Cerebras by default, so set `CEREBRAS_API_KEY` (or update `config/profiles.yml`).

## Quick Start (with `run.sh`)

```bash
# Set your API key
export CEREBRAS_API_KEY="your-api-key-here"

# Make the script executable (if you haven't already)
chmod +x run.sh

# Run the demo
./run.sh
```

## Manual Setup

```bash
cd sdk/examples/research_paper_analysis/js
npm install
npm run build
node dist/research_paper_analysis/main.js
```

## File Structure

```
research_paper_analysis/
├── config/
│   └── machine.yml          # Analysis pipeline
├── data/
│   ├── attention_is_all_you_need.pdf
│   ├── attention_is_all_you_need.txt
│   └── analysis_report.md
├── js/
│   ├── src/
│   │   └── research_paper_analysis/
│   │       ├── pdf.ts        # Download + text extraction
│   │       ├── parse.ts      # Regex-based parsing
│   │       └── main.ts       # Pipeline runner
│   ├── package.json
│   ├── tsconfig.json
│   ├── run.sh
│   └── README.md
└── python/
```

## Notes

- The pipeline uses programmatic parsing for speed and determinism.
- The final report is saved to `data/analysis_report.md`.
