# Webhook Action Example

A comprehensive example demonstrating webhook hook actions in flatmachines.

## Overview

This example shows how to:
1. **Trigger webhook calls** via hook actions in specific states
2. **Handle HTTP requests and responses** in custom hooks
3. **Implement retry logic** for failed webhook calls
4. **Process webhook results** and feed them to AI agents
5. **Graceful error handling** for external service integration

## Use Case

Sentiment analysis workflow that:
- Sends text to an external sentiment analysis webhook
- Receives sentiment scores and labels
- Uses an AI agent to provide detailed interpretation
- Handles failures and retries gracefully

## Architecture

```
┌─────────────────┐
│      start      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  call_webhook   │ ◄──────────┐
│ (hook action)   │            │
└────────┬────────┘            │
         │                     │
         ├─ success ──────┐    │
         │                │    │
         ├─ max retries   │    │
         │       │        │    │
         │       ▼        ▼    │
         │  ┌─────────────────┐│
         │  │  webhook_failed ││
         │  └─────────────────┘│
         │                     │
         └─ retry ───┐         │
                     │         │
                     ▼         │
              ┌─────────────┐  │
              │retry_webhook├──┘
              └─────────────┘

         (success path)
                     │
                     ▼
              ┌─────────────┐
              │analyze_result│
              │  (AI agent) │
              └──────┬──────┘
                     │
                     ▼
              ┌─────────────┐
              │    done     │
              └─────────────┘
```

## Key Components

### 1. Hook Action State

In `config/machine.yml`, the `call_webhook` state triggers the hook action:

```yaml
call_webhook:
  action: webhook_sentiment_analysis  # Calls WebhookActionHooks.on_action()
  transitions:
    - condition: "context.sentiment_score != null"
      to: analyze_result
    - condition: "context.retry_count >= context.max_retries"
      to: webhook_failed
    - to: retry_webhook
```

### 2. Custom Webhook Hooks

In `src/webhook_action/hooks.py`:

```python
class WebhookActionHooks(MachineHooks):
    def on_action(self, action_name: str, context: Dict) -> Dict:
        if action_name == "webhook_sentiment_analysis":
            return self._webhook_sentiment_analysis(context)
        return context

    def _webhook_sentiment_analysis(self, context: Dict) -> Dict:
        # Make HTTP POST request
        result = self._call_webhook(endpoint, text)

        # Update context with results
        context["sentiment_score"] = result.get("score")
        context["sentiment_label"] = result.get("label")

        return context
```

### 3. AI Agent Integration

The `analyze_result` state uses an AI agent to interpret webhook results:

```yaml
analyze_result:
  agent: analyzer
  input:
    text: "{{ context.text }}"
    sentiment_score: "{{ context.sentiment_score }}"
    sentiment_label: "{{ context.sentiment_label }}"
  output_to_context:
    analysis: "{{ output.analysis }}"
    recommendations: "{{ output.recommendations }}"
```

## Usage

### Basic Usage (Mock Mode)

Run without external dependencies using built-in mock responses:

```bash
cd sdk/python/examples/webhook_action

# Run with default text (mock mode)
python -m webhook_action.main --mock

# Analyze custom text
python -m webhook_action.main "This product is terrible!" --mock
```

### With Real Webhook

If you have a sentiment analysis webhook running:

```bash
# Use custom endpoint
python -m webhook_action.main "Great service!" \
    --endpoint https://api.example.com/sentiment

# With custom retry settings
python -m webhook_action.main "Testing the system" \
    --endpoint http://localhost:8000/analyze \
    --max-retries 3
```

### Expected Webhook API

Your webhook should accept POST requests:

**Request:**
```json
{
  "text": "I love this product!"
}
```

**Response:**
```json
{
  "score": 0.85,
  "label": "positive",
  "confidence": 0.92
}
```

## Features Demonstrated

### 1. HTTP Request Handling

The hooks make synchronous HTTP requests using `httpx`:

```python
def _call_webhook(self, endpoint: str, text: str) -> Dict[str, Any]:
    with httpx.Client() as client:
        response = client.post(
            endpoint,
            json={"text": text},
            timeout=self.timeout,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return response.json()
```

### 2. Error Handling

Gracefully handles various error types:

```python
try:
    result = self._call_webhook(endpoint, text)
    context["sentiment_score"] = result.get("score")
except httpx.TimeoutException:
    context["webhook_error"] = "Timeout"
except httpx.HTTPError as e:
    context["webhook_error"] = f"HTTP error: {str(e)}"
```

### 3. Retry Logic

The state machine implements retry logic via transitions:

```yaml
call_webhook:
  action: webhook_sentiment_analysis
  transitions:
    - condition: "context.sentiment_score != null"
      to: analyze_result  # Success path
    - condition: "context.retry_count >= context.max_retries"
      to: webhook_failed  # Give up after max retries
    - to: retry_webhook   # Default: try again

retry_webhook:
  output_to_context:
    retry_count: "{{ context.retry_count + 1 }}"
  transitions:
    - to: call_webhook
```

### 4. Mock Mode

For testing and demos without external dependencies:

```python
def _mock_sentiment_analysis(self, text: str) -> Dict[str, Any]:
    # Simple keyword-based sentiment
    positive_words = {"great", "excellent", "amazing", ...}
    negative_words = {"bad", "terrible", "awful", ...}

    # Calculate mock score based on keywords
    score = calculate_score(text, positive_words, negative_words)

    return {"score": score, "label": label, "mock": True}
```

## Context Flow

The hook action modifies context which drives state transitions:

1. **Initial context:**
   ```python
   {
       "text": "I love this!",
       "webhook_endpoint": "http://...",
       "sentiment_score": null,  # Not set yet
       "retry_count": 0
   }
   ```

2. **After webhook success:**
   ```python
   {
       "text": "I love this!",
       "sentiment_score": 0.85,      # Set by hook
       "sentiment_label": "positive", # Set by hook
       "webhook_timestamp": "2024-...", # Set by hook
       "retry_count": 0
   }
   ```

3. **After AI analysis:**
   ```python
   {
       ...,
       "analysis": "The text shows strong...",  # From agent
       "recommendations": "Respond with..."     # From agent
   }
   ```

## Integration Patterns

### Pattern 1: Simple Webhook Call

```yaml
states:
  process:
    action: my_webhook_action
    transitions:
      - to: next_state
```

```python
def on_action(self, action_name, context):
    if action_name == "my_webhook_action":
        result = call_external_api(context["data"])
        context["result"] = result
    return context
```

### Pattern 2: Conditional Processing

```yaml
states:
  validate:
    action: external_validation
    transitions:
      - condition: "context.valid == true"
        to: proceed
      - to: handle_invalid
```

### Pattern 3: Async Hook Actions

For async HTTP calls, make the hook method async:

```python
async def on_action(self, action_name, context):
    if action_name == "async_webhook":
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
        context["result"] = response.json()
    return context
```

## Running a Test Webhook Server

For testing, you can create a simple Flask server:

```python
# test_webhook.py
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/analyze', methods=['POST'])
def analyze():
    text = request.json.get('text', '')

    # Simple mock sentiment
    score = 0.5 if 'good' in text.lower() else -0.5
    label = 'positive' if score > 0 else 'negative'

    return jsonify({
        'score': score,
        'label': label,
        'confidence': 0.85
    })

if __name__ == '__main__':
    app.run(port=8000)
```

Run it with:
```bash
python test_webhook.py
```

Then run the example:
```bash
python -m webhook_action.main "This is good!"
```

## Extending This Example

### Add Authentication

```python
def _call_webhook(self, endpoint, text):
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json"
    }
    response = client.post(endpoint, json={"text": text}, headers=headers)
    ...
```

### Multiple Webhook Calls

```yaml
states:
  enrich_data:
    action: call_multiple_webhooks
    transitions:
      - to: process_results

# In hooks:
def on_action(self, action_name, context):
    if action_name == "call_multiple_webhooks":
        context["sentiment"] = call_webhook_1(...)
        context["entities"] = call_webhook_2(...)
        context["topics"] = call_webhook_3(...)
    return context
```

### Webhook Response Validation

```python
def _webhook_sentiment_analysis(self, context):
    result = self._call_webhook(endpoint, text)

    # Validate response structure
    if "score" not in result or "label" not in result:
        raise ValueError("Invalid webhook response format")

    # Validate score range
    if not (-1 <= result["score"] <= 1):
        raise ValueError("Sentiment score out of range")

    context["sentiment_score"] = result["score"]
    return context
```

## Troubleshooting

**Webhook timeout:**
- Increase timeout in hooks: `WebhookActionHooks(timeout=30.0)`
- Check network connectivity
- Verify webhook endpoint is accessible

**Max retries reached:**
- Check webhook server logs
- Verify request format matches webhook API
- Test webhook endpoint with curl/httpie

**JSON parsing errors:**
- Verify webhook returns valid JSON
- Check Content-Type header
- Inspect raw response in logs

## See Also

- Built-in `WebhookHooks` class for dispatching all machine events
- `human_in_loop` example for blocking hook actions
- `dynamic_agent` example for complex hook action patterns
