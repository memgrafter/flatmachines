# Plan: Text-First Agent Output Pattern

## Problem Statement

LLMs produce higher quality output when generating natural language versus being constrained to JSON. The current pattern of adding "Respond with JSON: {...}" to every agent prompt may degrade output quality, especially for:
- Creative writing (taglines, stories, responses)
- Complex reasoning (analysis, critique, synthesis)
- Nuanced evaluation (judgments, feedback)

## Decisions Made

- **Scope**: Pilot with `writer_critic` first, then expand
- **Extractor model**: Always use `fast` profile (extraction is simple, minimize cost)
- **Generator schema**: No output schema (fully unconstrained text)

## Pattern: Text Generation → Structured Extraction

```
┌─────────────────┐     ┌─────────────────┐
│  Generator      │     │  Extractor      │
│  Agent          │────▶│  Agent          │
│  (natural text) │     │  (JSON output)  │
│  (no schema)    │     │  (fast model)   │
└─────────────────┘     └─────────────────┘
```

## Implementation

### 1. Update writer.yml (remove JSON, remove output schema)

**Before:**
```yaml
user: |
  Write a catchy tagline for: {{ input.product }}
  Respond with JSON: {"tagline": "your tagline here"}
output:
  tagline:
    type: str
```

**After:**
```yaml
user: |
  {% if input.feedback %}
  Previous attempt: {{ input.tagline }}
  Feedback: {{ input.feedback }}
  Write an improved tagline that addresses the feedback.
  {% else %}
  Write a catchy tagline for this product: {{ input.product }}
  {% endif %}

  Write only the tagline, nothing else.
# No output schema - raw text output
```

### 2. Create tagline_extractor.yml (NEW)

```yaml
spec: flatagent
spec_version: "0.7.7"

data:
  name: tagline-extractor
  model: fast
  system: Extract the marketing tagline from the given text. Return only valid JSON.
  user: |
    Text: {{ input.text }}

    Respond with JSON: {"tagline": "the extracted tagline"}
  output:
    tagline:
      type: str
      description: The extracted tagline
```

### 3. Update machine.yml (add extraction state)

**Before:**
```yaml
write:
  agent: writer
  output_to_context:
    tagline: "{{ output.tagline }}"
  transitions:
    - to: review
```

**After:**
```yaml
write:
  agent: writer
  output_to_context:
    raw_tagline: "{{ output.content }}"
  transitions:
    - to: extract_tagline

extract_tagline:
  agent: tagline_extractor
  input:
    text: "{{ context.raw_tagline }}"
  output_to_context:
    tagline: "{{ output.tagline }}"
  transitions:
    - to: review
```

### 4. Update profiles.yml (add fast profile)

Current profiles only have `default` and `creative`. Add `fast` for extraction:

```yaml
data:
  model_profiles:
    default:
      provider: cerebras
      name: zai-glm-4.7
      temperature: 1.0
    creative:
      provider: cerebras
      name: zai-glm-4.7
      temperature: 0.6
    fast:
      provider: cerebras
      name: zai-glm-4.7
      temperature: 0.1    # Low temp for deterministic extraction

  default: default
```

## Files to Modify

| File | Action |
|------|--------|
| `writer_critic/config/writer.yml` | Remove JSON instruction, remove output schema |
| `writer_critic/config/tagline_extractor.yml` | CREATE - new extractor agent |
| `writer_critic/config/machine.yml` | Add `extract_tagline` state, update `agents` section |
| `writer_critic/config/profiles.yml` | Add `fast` profile for extraction

## Verification

```bash
# Test JS example
cd sdk/examples/writer_critic/js && ./run.sh

# Test Python example
cd sdk/examples/writer_critic/python && ./run.sh --local
```

Expected:
1. Writer produces natural text tagline (unconstrained)
2. Extractor parses it into JSON
3. Critic receives structured tagline
4. Final output shows tagline and score
