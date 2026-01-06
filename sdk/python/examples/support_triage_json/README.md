# Support Triage JSON Demo

A minimal support triage workflow that uses JSON FlatMachine and FlatAgent configs.

This demo showcases:
- JSON configs for both `flatmachine` and `flatagent`
- A nested child machine for response drafting
- Agent-only execution states (no custom hooks)

## How It Works

1. **Triage Agent**: Classifies the ticket and decides if a response is needed
2. **Response Flow**: A child machine drafts and polishes a response
3. **Final Output**: Parent machine emits the triage decision and response

## Prerequisites

1. **Python & `uv`**: Ensure you have Python 3.10+ and the `uv` package manager installed.
2. **LLM API Key**: This demo uses Cerebras by default. Set `CEREBRAS_API_KEY` in your environment.

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

1. **Navigate into this project directory**:
    ```bash
    cd examples/support_triage_json
    ```
2. **Install dependencies** using `uv`:
    ```bash
    uv venv
    uv pip install -e .
    ```
3. **Set your LLM API key**:
    ```bash
    export CEREBRAS_API_KEY="your-api-key-here"
    ```
4. **Run the demo**:
    ```bash
    uv run python -m support_triage_json.main
    ```

## Input and Output

The parent machine consumes an input object like:

```json
{
  "ticket_id": "TCK-1042",
  "customer_message": "My account was charged twice for last month.",
  "customer_tier": "pro",
  "preferred_tone": "friendly"
}
```

The output includes the triage decision and, when needed, a drafted response:

```json
{
  "ticket_id": "TCK-1042",
  "category": "billing",
  "urgency": "medium",
  "needs_response": true,
  "triage_summary": "Duplicate billing charge reported for last month.",
  "response": {
    "subject": "We are looking into the duplicate charge",
    "body": "Thanks for flagging this. We are reviewing your billing history...",
    "actions": ["refund_request_created", "billing_team_notified"]
  }
}
```

## Files

- `config/machine.json` - Parent machine (triage + nested response flow)
- `config/response_machine.json` - Child machine for drafting and polishing
- `config/triage_agent.json` - Triage classifier
- `config/response_drafter.json` - Draft generator
- `config/response_polisher.json` - Response refiner
