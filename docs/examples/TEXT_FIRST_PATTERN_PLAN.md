# Plan: Text-First Agent Output Pattern - All Examples

## Overview

Apply the text-first pattern (generator → extractor) to all 10 examples. Each example is **standalone** - no shared code between examples.

**Pilot completed**: `writer_critic` ✅

## Pattern (Same for All)

```
Generator Agent          Extractor Agent
(natural text)    →     (JSON output, fast model)
(no output schema)      (has output schema)
```

## Examples to Update

### 1. ✅ writer_critic (DONE)
- `writer.yml` → `tagline_extractor.yml`

### 2. error_handling
**Agents**: worker.yml, cleanup.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| worker | `result` (analysis text) | `result_extractor.yml` |
| cleanup | `summary` (error summary) | `summary_extractor.yml` |

### 3. story_writer
**Agents**: outliner.yml, drafter.yml, critic.yml, reviser.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| outliner | `title`, `chapter_outlines[]` | `outline_extractor.yml` |
| drafter | `chapter_text` (500-800 words prose) | `chapter_extractor.yml` |
| critic | `feedback` | `feedback_extractor.yml` |
| reviser | `revised_text` | `revision_extractor.yml` |

### 4. rlm
**Agents**: decomposer.yml, explorer.yml, processor.yml, synthesizer.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| decomposer | subqueries list | `subquery_extractor.yml` |
| explorer | findings | `findings_extractor.yml` |
| processor | processed results | `processed_extractor.yml` |
| synthesizer | final answer | `answer_extractor.yml` |

### 5. research_paper_analysis
**Agents**: abstract_analyzer.yml, section_analyzer.yml, critic.yml, synthesizer.yml, formatter.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| abstract_analyzer | `key_findings`, `methodology`, `contributions` | `abstract_extractor.yml` |
| section_analyzer | `technical_details`, `results` | `section_extractor.yml` |
| synthesizer | `summary` (4 paragraphs) | `summary_extractor.yml` |
| critic | `quality_score`, `critique` | `critique_extractor.yml` |
| formatter | `report` (markdown) | `report_extractor.yml` |

### 6. peering
**Agents**: worker.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| worker | result | `result_extractor.yml` |

### 7. parallelism
**Agents**: reviewer.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| reviewer | review | `review_extractor.yml` |

### 8. human-in-the-loop
**Agents**: task_agent.yml, drafter.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| task_agent | task result | `task_extractor.yml` |
| drafter | draft | `draft_extractor.yml` |

### 9. gepa_self_optimizer
**Agents**: task_generator.yml, summary_generator.yml, response_generator.yml, reflective_updater.yml, judge.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| task_generator | tasks | `task_extractor.yml` |
| summary_generator | summary | `summary_extractor.yml` |
| response_generator | response | `response_extractor.yml` |
| reflective_updater | updates | `update_extractor.yml` |
| judge | judgment | `judgment_extractor.yml` |

### 10. dynamic_agent
**Agents**: supervisor.yml

| Agent | Output | Extractor |
|-------|--------|-----------|
| supervisor | result | `result_extractor.yml` |

## Per-Example Changes

For each example:

1. **Update generator agents**: Remove `Respond with JSON:` and `output:` schema
2. **Create extractor agents**: New `*_extractor.yml` files with `model: fast`
3. **Update machine.yml**: Add extraction states, update `agents:` section
4. **Update profiles.yml**: Add `fast` profile (temp 0.1)

## Extractor Template

```yaml
spec: flatagent
spec_version: "0.7.7"

data:
  name: <name>-extractor
  model: fast
  system: Extract the <field> from the given text. Return only valid JSON.
  user: |
    Text: {{ input.text }}

    Respond with JSON: {"<field>": "<extracted value>"}
  output:
    <field>:
      type: str
      description: The extracted <field>
```

## Verification

```bash
# For each example
cd sdk/examples/<example>/js && ./run.sh
cd sdk/examples/<example>/python && ./run.sh --local
```
