# Parallelism Example for FlatAgents

This example demonstrates the new parallel execution features introduced in FlatAgents v0.4.0. It shows three different patterns for running machines and agents in parallel.

## Features Demonstrated

### 1. Parallel Machine Execution
**Pattern**: `machine: [agent1, agent2, agent3]`

- Runs multiple machines simultaneously
- Waits for all to complete before proceeding
- Useful for independent tasks like sentiment analysis and summarization

**Example**: Analyzes the same text corpus with both sentiment analysis and summarization running in parallel.

### 2. Dynamic Parallelism with `foreach`
**Pattern**: 
```yaml
foreach: "{{ context.items }}"
as: item
machine: processor
```

- Dynamically creates parallel executions for each item in a list
- Scales based on input data size
- Returns results as keyed objects (if `key` provided) or arrays

**Example**: Analyzes sentiment for each text in an array, with each text processed in parallel.

### 3. Fire-and-Forget Launches
**Pattern**: 
```yaml
launch: notifier
launch_input:
  message: "{{ context.message }}"
  recipients: ["user1", "user2"]
```

- Launches machines without waiting for results
- Useful for background tasks, notifications, and non-blocking operations
- Results are available in the backend but don't block execution

**Example**: Sends notifications to multiple recipients in the background.

## Architecture

```
parallelism/
├── config/
│   ├── machine.yml          # Main machine with parallel states
│   ├── sentiment_agent.yml  # Sentiment analysis agent
│   ├── summarizer_agent.yml # Text summarization agent
│   ├── notifier_agent.yml   # Notification handling agent
│   └── aggregator_agent.yml # Results combination agent
├── src/parallelism/
│   ├── __init__.py
│   └── main.py             # Demo orchestrator
├── pyproject.toml
├── run.sh
├── README.md
└── .gitignore
```

## Usage

### Quick Start
```bash
cd sdk/python/examples/parallelism
./run.sh
```

### Advanced Usage
```bash
# Install locally during development
./run.sh --local

# Run with Python directly
python -m parallelism.main
```

## Output Examples

### Parallel Aggregation
```
=== Basic Parallel Execution ===
Parallel result: {
  "aggregated": "The texts cover technology transformation themes including machine learning, quantum computing, and AI assistants...",
  "insights": ["Technology focus", "Future-looking themes", "Practical applications"],
  "execution_summary": "Processed 3 texts with parallel sentiment and summarization"
}
```

### Foreach Analysis
```
=== Dynamic Parallelism (foreach) ===
Foreach result: [
  {"sentiment": "positive", "confidence": 0.9, "reasoning": "Expresses enthusiasm and satisfaction"},
  {"sentiment": "negative", "confidence": 0.95, "reasoning": "Strong negative language used"},
  {"sentiment": "neutral", "confidence": 0.6, "reasoning": "Lacks strong emotional indicators"},
  {"sentiment": "positive", "confidence": 0.85, "reasoning": "Positive reinforcement and praise"}
]
```

### Fire-and-Forget
```
=== Fire-and-Forget Launches ===
Fire-and-forget result: Sent notifications in background
```

## Key Concepts

### Result Backends
Parallel execution uses result backends for inter-machine communication:
- **In-memory backend**: Default for single-process execution
- **URI scheme**: `flatagents://{execution_id}/result`
- **Blocking/Non-blocking reads**: Flexible result retrieval

### Outbox Pattern
Ensures exactly-once semantics for fire-and-forget launches:
- Launch intents are checkpointed before execution
- Resume capability on machine restart
- Automatic retry of incomplete launches

### Execution Modes
- **settled**: Wait for all parallel tasks to complete
- **any**: Return when first task completes (future feature)
- **fire-and-forget**: Launch without waiting

## Performance Benefits

- **Concurrency**: Multiple agents execute simultaneously
- **Scalability**: `foreach` scales with data size
- **Responsive UI**: Fire-and-forget prevents blocking
- **Efficiency**: Better resource utilization

## Extending the Example

1. **Add more agents**: Create additional parallel worker agents
2. **Custom result backends**: Implement distributed result storage
3. **Error handling**: Add retry logic and error aggregation
4. **Performance monitoring**: Track parallel execution metrics

## Dependencies

- `flatagents[litellm] >= 0.4.0`
- Python >= 3.10
- Cerebras API credentials (or other supported LLM provider)

## Troubleshooting

- Check API key configuration in environment variables or `.env`
- Verify network connectivity for parallel LLM calls
- Monitor API rate limits when running many parallel agents
- Use debug logging to trace execution flow