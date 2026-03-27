# FlatAgents Parallelism Example

Demonstrates parallel execution capabilities in FlatAgents including machine arrays, foreach loops, and fire-and-forget patterns.

## Features Demonstrated

### 1. Parallel Machine Execution
Run multiple machines simultaneously:
- Sentiment analysis
- Text summarization

### 2. ForEach Dynamic Parallelism
Process an array of texts in parallel:
- Each text analyzed independently
- Results collected into an array
- Dynamic scaling based on input size

### 3. Fire-and-Forget Launches
Launch background notification formatting:
- Non-blocking launches
- Results available in the backend

## Quick Start

```bash
# Setup and run the demo
./run.sh
```

## Development Options

```bash
# Use local flatmachines package (for development)
./run.sh --local
```

## File Structure

```
parallelism/
├── config/
│   ├── machine.yml             # Main parallelism machine
│   ├── sentiment_machine.yml   # Sentiment machine wrapper
│   ├── summarizer_machine.yml  # Summarizer machine wrapper
│   ├── notification_machine.yml # Notification machine wrapper
│   ├── sentiment_agent.yml     # Sentiment agent
│   ├── summarizer_agent.yml    # Summarizer agent
│   ├── notifier_agent.yml      # Notification agent
│   └── aggregator_agent.yml    # Aggregator agent
├── src/
│   └── parallelism/
│       └── main.ts          # Demo application
├── package.json             # Dependencies and scripts
├── run.sh                   # Setup and execution script
└── README.md                # This file
```

## How It Works

### Parallel Machines Pattern
```yaml
states:
  parallel_aggregate:
    machine: [summarizer_machine.yml, sentiment_machine.yml]
    input:
      texts: "{{ context.texts }}"
    output_to_context:
      parallel_results: "{{ output }}"
```

### ForEach Pattern
```yaml
states:
  foreach_analysis:
    foreach: "{{ context.texts }}"
    as: text
    machine: sentiment_machine.yml
    input:
      text: "{{ text }}"
    output_to_context:
      sentiment_results: "{{ output }}"
```

### Fire-and-Forget Pattern
```yaml
states:
  launch_notifications:
    launch: notification_machine.yml
    launch_input:
      message: "{{ context.message }}"
      recipients: ["admin@example.com", "user@example.com"]
```

## Expected Output

You'll see:
1. **Parallel Machines**: Summarization + sentiment in parallel
2. **ForEach Demo**: Sentiment analysis for each text
3. **Fire-and-Forget**: Background notification formatting

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Other Examples](../)
