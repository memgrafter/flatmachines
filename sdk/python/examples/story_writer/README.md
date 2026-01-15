# Multi-Chapter Story Writer

A **long-running creative workflow** example demonstrating machine topology + checkpoint/resume with `flatagents`.

## Features Demonstrated

- **Machine Peering**: Parent launches and coordinates chapter-by-chapter writing
- **Checkpoint/Resume**: Stop mid-novel and resume days later
- **Iterative Refinement**: Each chapter goes through draft → critique → revise loop

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│ PARENT: story_orchestrator                                      │
│                                                                 │
│   ┌──────┐    ┌──────────┐    ┌──────────┐    ┌──────┐        │
│   │start │───▶│ outline  │───▶│ chapters │───▶│ done │        │
│   └──────┘    └──────────┘    └──────────┘    └──────┘        │
│                                     │                          │
│                    ┌────────────────┼────────────────┐         │
│                    ▼                ▼                ▼         │
│              ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│              │ CHILD:   │    │ CHILD:   │    │ CHILD:   │     │
│              │chapter 1 │    │chapter 2 │    │chapter N │     │
│              │          │    │          │    │          │     │
│              │ draft    │    │ draft    │    │ draft    │     │
│              │ critique │    │ critique │    │ critique │     │
│              │ revise   │    │ revise   │    │ revise   │     │
│              └──────────┘    └──────────┘    └──────────┘     │
└────────────────────────────────────────────────────────────────┘
```

## How It Works

1. **Outliner**: Plans the story arc with chapter summaries
2. **Chapter Writer**: For each chapter:
   - Draft the chapter
   - Critique identifies issues
   - Revise improves draft
3. **Final Output**: Compiled multi-chapter story

Checkpoints enable resuming after crashes or API rate limits.

## Quick Start

```bash
export CEREBRAS_API_KEY="your-key"
chmod +x run.sh
./run.sh
```

## Example Input

```python
# Default demo writes a 2-chapter sci-fi story
result = await run(
    genre="science fiction",
    premise="A librarian discovers books can literally transport readers into their stories",
    num_chapters=2
)
```

## Use Cases for Checkpoint/Resume

- **Long novels**: 10+ chapters = 30+ LLM calls, easily hours of work
- **Rate limits**: Resume after hitting API quotas
- **Iterative creative work**: Stop, think about direction, resume
- **Cost control**: Pause if budget exceeded

