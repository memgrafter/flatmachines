# FlatAgents Parallelism Example

Demonstrates parallel execution capabilities in FlatAgents including machine arrays, foreach loops, and fire-and-forget patterns.

## Features Demonstrated

### 1. Parallel Machines
Run multiple machines simultaneously:
- Legal review
- Technical review  
- Financial review
All process the same document in parallel.

### 2. ForEach Dynamic Parallelism
Process an array of documents in parallel:
- Each document processed independently
- Results collected into an array
- Dynamic scaling based on input size

## Quick Start

```bash
# Setup and run the demo
./run.sh
```

## Development Options

```bash
# Use local flatagents package (for development)
./run.sh --local

# Run in development mode with tsx
./run.sh --dev

# Show help
./run.sh --help
```

## File Structure

```
parallelism/
├── config/
│   ├── reviewer.yml         # Agent configuration
│   ├── main_machine.yml     # Parallel machines demo
│   ├── legal_review.yml     # Legal review machine
│   ├── technical_review.yml # Technical review machine
│   ├── financial_review.yml # Financial review machine
│   ├── foreach_machine.yml  # Foreach demo machine
│   └── doc_processor.yml    # Document processor machine
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
  parallel_review:
    machine: [legal_review, technical_review, financial_review]
    input:
      document: "{{ context.document }}"
    output_to_context:
      reviews: "{{ output }}"
```

### ForEach Pattern
```yaml
states:
  process_all:
    foreach: "{{ context.documents }}"
    as: doc
    machine: doc_processor.yml
    input:
      document: "{{ doc.content }}"
      name: "{{ doc.name }}"
    output_to_context:
      results: "{{ output }}"
```

## Expected Output

You'll see:
1. **Parallel Machines**: Three reviews completed simultaneously
2. **ForEach Demo**: Three documents processed in parallel
3. Performance benefits of parallel execution

## Learn More

- [FlatAgents Documentation](../../README.md)
- [Other Examples](../)