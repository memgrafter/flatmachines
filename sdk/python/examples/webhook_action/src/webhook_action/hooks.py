"""
Webhook Action Hooks

Demonstrates using hook actions to integrate with external webhook endpoints.
This example shows how to:
- Make HTTP requests to webhooks
- Handle responses and errors gracefully
- Update context with webhook results
- Implement retry logic
"""

from typing import Any, Dict
from datetime import datetime
import httpx
from flatagents import MachineHooks, get_logger

logger = get_logger(__name__)


class WebhookActionHooks(MachineHooks):
    """
    Hooks for webhook action integration.

    The webhook_sentiment_analysis action sends text to an external
    sentiment analysis webhook and processes the response.
    """

    def __init__(self, timeout: float = 10.0, mock_mode: bool = False):
        """
        Initialize webhook hooks.

        Args:
            timeout: HTTP request timeout in seconds
            mock_mode: If True, simulate webhook responses without making real HTTP calls
        """
        self.timeout = timeout
        self.mock_mode = mock_mode

    def on_action(self, action_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom actions."""
        if action_name == "webhook_sentiment_analysis":
            return self._webhook_sentiment_analysis(context)
        return context

    def _webhook_sentiment_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call external webhook for sentiment analysis.

        This demonstrates:
        1. Reading configuration from context
        2. Making HTTP POST requests
        3. Handling successful responses
        4. Graceful error handling
        5. Updating context with results

        Args:
            context: Current machine context containing:
                - text: The text to analyze
                - webhook_endpoint: The webhook URL
                - retry_count: Current retry attempt

        Returns:
            Updated context with sentiment results or error information
        """
        text = context.get("text", "")
        endpoint = context.get("webhook_endpoint", "http://localhost:8000/analyze")
        retry_count = context.get("retry_count", 0)

        logger.info(f"Calling webhook (attempt {retry_count + 1}): {endpoint}")
        logger.info(f"Text to analyze: {text[:100]}...")

        try:
            if self.mock_mode:
                # Mock response for testing/demo purposes
                result = self._mock_sentiment_analysis(text)
            else:
                # Make actual HTTP request
                result = self._call_webhook(endpoint, text)

            # Update context with successful results
            context["sentiment_score"] = result.get("score")
            context["sentiment_label"] = result.get("label")
            context["webhook_timestamp"] = datetime.utcnow().isoformat()

            logger.info(f"✓ Webhook succeeded: {result.get('label')} "
                       f"(score: {result.get('score')})")

        except httpx.TimeoutException as e:
            logger.error(f"✗ Webhook timeout after {self.timeout}s: {e}")
            context["webhook_error"] = f"Timeout after {self.timeout}s"

        except httpx.HTTPError as e:
            logger.error(f"✗ Webhook HTTP error: {e}")
            context["webhook_error"] = f"HTTP error: {str(e)}"

        except Exception as e:
            logger.error(f"✗ Webhook unexpected error: {e}")
            context["webhook_error"] = f"Error: {str(e)}"

        return context

    def _call_webhook(self, endpoint: str, text: str) -> Dict[str, Any]:
        """
        Make synchronous HTTP POST request to webhook.

        Args:
            endpoint: Webhook URL
            text: Text to send for analysis

        Returns:
            Response JSON containing sentiment results

        Raises:
            httpx.HTTPError: If request fails
        """
        with httpx.Client() as client:
            response = client.post(
                endpoint,
                json={"text": text},
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()

    def _mock_sentiment_analysis(self, text: str) -> Dict[str, Any]:
        """
        Simulate webhook response for testing.

        This is useful for:
        - Running the example without external dependencies
        - Testing error handling
        - Demonstrations

        Args:
            text: Text to analyze

        Returns:
            Mocked sentiment analysis result
        """
        # Simple keyword-based mock sentiment
        text_lower = text.lower()

        positive_words = {"great", "excellent", "amazing", "wonderful", "love", "happy", "good"}
        negative_words = {"bad", "terrible", "awful", "hate", "horrible", "poor", "sad"}

        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)

        # Calculate mock score
        if positive_count > negative_count:
            score = 0.5 + (positive_count * 0.15)
            label = "positive"
        elif negative_count > positive_count:
            score = -0.5 - (negative_count * 0.15)
            label = "negative"
        else:
            score = 0.0
            label = "neutral"

        # Clamp score to [-1, 1]
        score = max(-1.0, min(1.0, score))

        logger.info(f"Mock analysis: {label} (score: {score:.2f})")

        return {
            "score": round(score, 2),
            "label": label,
            "confidence": 0.85,
            "mock": True
        }

    def on_state_enter(self, state: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Log when entering states for visibility."""
        logger.info(f"→ Entering state: {state}")
        return context

    def on_state_exit(self, state: str, context: Dict[str, Any], output: Any) -> Any:
        """Log when exiting states for visibility."""
        logger.info(f"← Exiting state: {state}")
        return output
