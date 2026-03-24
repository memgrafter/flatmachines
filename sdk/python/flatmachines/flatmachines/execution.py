"""
Execution Types for FlatMachine.

Provides different execution strategies for agent calls:
- Default: Single call
- Parallel: Multiple calls, first success or aggregate
- Retry: Multiple attempts with backoff
- MDAP Voting: Multi-sampling with majority vote
"""

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .monitoring import get_logger
from .agents import AgentExecutor, AgentResult, coerce_agent_result

logger = get_logger(__name__)


def _coerce_status_code(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_status_code(error: Optional[BaseException]) -> Optional[int]:
    if error is None:
        return None

    for attr in ("status_code", "status", "http_status", "statusCode"):
        code = _coerce_status_code(getattr(error, attr, None))
        if code is not None:
            return code

    response = getattr(error, "response", None)
    if response is not None:
        for attr in ("status_code", "status", "http_status", "statusCode"):
            code = _coerce_status_code(getattr(response, attr, None))
            if code is not None:
                return code
        if isinstance(response, dict):
            for key in ("status_code", "status", "http_status", "statusCode"):
                code = _coerce_status_code(response.get(key))
                if code is not None:
                    return code

    match = re.search(r"\b([4-5]\d{2})\b", str(error))
    if match:
        return int(match.group(1))
    return None


def _normalize_headers(raw_headers: Any) -> Dict[str, str]:
    if raw_headers is None:
        return {}

    if isinstance(raw_headers, dict):
        items = raw_headers.items()
    elif hasattr(raw_headers, "items"):
        items = raw_headers.items()
    elif isinstance(raw_headers, (list, tuple)):
        items = raw_headers
    else:
        return {}

    normalized: Dict[str, str] = {}
    for key, value in items:
        if key is None:
            continue
        key_text = str(key).lower()
        if isinstance(value, (list, tuple)):
            value_text = ",".join(str(item) for item in value)
        else:
            value_text = str(value)
        normalized[key_text] = value_text

    return normalized


def _extract_error_headers(error: Optional[BaseException]) -> Dict[str, str]:
    if error is None:
        return {}

    response = getattr(error, "response", None)
    headers: Dict[str, str] = {}
    if response is not None:
        headers.update(_normalize_headers(getattr(response, "headers", None)))
        if not headers and isinstance(response, dict):
            headers.update(_normalize_headers(response.get("headers")))

    headers.update(_normalize_headers(getattr(error, "headers", None)))
    return headers


def _extract_api_calls(result: AgentResult) -> int:
    usage = result.usage or {}
    if isinstance(usage, dict):
        return int(usage.get("api_calls") or usage.get("requests") or usage.get("calls") or 0)
    return 0


def _extract_cost(result: AgentResult) -> float:
    if result.cost is not None:
        try:
            return float(result.cost)
        except (TypeError, ValueError):
            return 0.0
    usage = result.usage or {}
    if isinstance(usage, dict):
        cost = usage.get("cost")
        if isinstance(cost, (int, float)):
            return float(cost)
        if isinstance(cost, dict):
            total = cost.get("total")
            if isinstance(total, (int, float)):
                return float(total)
    return 0.0


def _merge_usage(result: AgentResult, api_calls: int) -> Optional[Dict[str, Any]]:
    if api_calls == 0 and result.usage is None:
        return result.usage
    usage: Dict[str, Any] = {}
    if isinstance(result.usage, dict):
        usage.update(result.usage)
    if api_calls:
        usage["api_calls"] = api_calls
    return usage


# Registry of execution types
_EXECUTION_TYPES: Dict[str, type] = {}


def register_execution_type(name: str):
    """Decorator to register an execution type."""
    def decorator(cls):
        _EXECUTION_TYPES[name] = cls
        return cls
    return decorator


def get_execution_type(config: Optional[Dict[str, Any]] = None) -> "ExecutionType":
    """Get an execution type instance from config."""
    if config is None:
        return DefaultExecution()
    
    type_name = config.get("type", "default")
    if type_name not in _EXECUTION_TYPES:
        raise ValueError(f"Unknown execution type: {type_name}")
    
    cls = _EXECUTION_TYPES[type_name]
    return cls.from_config(config)


class ExecutionType(ABC):
    """Base class for execution types."""
    
    @classmethod
    @abstractmethod
    def from_config(cls, config: Dict[str, Any]) -> "ExecutionType":
        """Create instance from YAML config."""
        pass
    
    @abstractmethod
    async def execute(
        self,
        executor: AgentExecutor,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Execute the agent with this execution type.

        Args:
            executor: The AgentExecutor to call
            input_data: Input data for the agent
            context: Current machine context
            session_id: Cache key for prompt prefix caching

        Returns:
            AgentResult
        """
        pass


@register_execution_type("default")
class DefaultExecution(ExecutionType):
    """Standard single agent call."""
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DefaultExecution":
        return cls()
    
    async def execute(
        self,
        executor: AgentExecutor,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Single agent call."""
        result = await executor.execute(input_data, context=context, session_id=session_id)
        return coerce_agent_result(result)


# Parallel Execution Type

@register_execution_type("parallel")
class ParallelExecution(ExecutionType):
    """
    Run N samples in parallel, return all results.
    
    Useful for getting multiple diverse responses to compare or aggregate.
    
    Example YAML:
        execution:
          type: parallel
          n_samples: 5
    """
    
    def __init__(self, n_samples: int = 3):
        self.n_samples = n_samples
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "ParallelExecution":
        return cls(
            n_samples=config.get("n_samples", 3)
        )
    
    async def execute(
        self,
        executor: AgentExecutor,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Run N agent calls in parallel, return all results."""
        async def single_call() -> AgentResult:
            result = await executor.execute(input_data, context=context, session_id=session_id)
            return coerce_agent_result(result)

        # Run all samples in parallel
        tasks = [single_call() for _ in range(self.n_samples)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = [r for r in results if not isinstance(r, Exception)]

        if not valid_results:
            return AgentResult()

        payloads = [result.output_payload() for result in valid_results]
        total_api_calls = sum(_extract_api_calls(result) for result in valid_results)
        total_cost = sum(_extract_cost(result) for result in valid_results)

        usage = {"api_calls": total_api_calls} if total_api_calls else None
        cost = total_cost if total_cost else None

        return AgentResult(
            output={"results": payloads, "count": len(payloads)},
            raw={"results": valid_results},
            usage=usage,
            cost=cost,
        )


# Retry Execution Type

@register_execution_type("retry")
class RetryExecution(ExecutionType):
    """
    Retry on failure with configurable backoff delays and jitter.
    
    Default backoffs [2, 8, 16, 35] total 61 seconds, intended to wait
    for a fresh RPM (requests per minute) bucket.
    
    Example YAML:
        execution:
          type: retry
          backoffs: [2, 8, 16, 35]  # Backoff delays in seconds
          jitter: 0.1  # Random jitter factor (0.1 = ±10%)
    """
    
    # Default backoffs: 2 + 8 + 16 + 35 = 61 seconds (wait for fresh RPM bucket)
    DEFAULT_BACKOFFS = [2, 8, 16, 35]
    
    def __init__(
        self,
        backoffs: Optional[List[float]] = None,
        jitter: float = 0.1,
        retry_on_empty: bool = False
    ):
        self.backoffs = backoffs if backoffs is not None else self.DEFAULT_BACKOFFS
        self.jitter = jitter
        self.retry_on_empty = retry_on_empty
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RetryExecution":
        return cls(
            backoffs=config.get("backoffs"),
            jitter=config.get("jitter", 0.1),
            retry_on_empty=config.get("retry_on_empty", False)
        )
    
    def _apply_jitter(self, delay: float) -> float:
        """Apply random jitter to a delay."""
        import random
        jitter_range = delay * self.jitter
        return delay + random.uniform(-jitter_range, jitter_range)
    
    async def execute(
        self,
        executor: AgentExecutor,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """Execute with retries on failure."""
        last_error = None
        last_error_result: Optional[AgentResult] = None  # For structured errors from adapter
        max_attempts = len(self.backoffs) + 1  # Initial attempt + retries
        total_api_calls = 0
        total_cost = 0.0

        for attempt in range(max_attempts):
            try:
                result = await executor.execute(input_data, context=context, session_id=session_id)
                agent_result = coerce_agent_result(result)
                total_api_calls += _extract_api_calls(agent_result)
                total_cost += _extract_cost(agent_result)
                
                # Check for structured error from adapter (e.g., rate limit)
                if agent_result.error:
                    error_info = agent_result.error
                    is_retryable = error_info.get("retryable", False)
                    
                    log_msg = (
                        f"Attempt {attempt + 1}/{max_attempts} failed: "
                        f"{error_info.get('type', 'Error')}: {error_info.get('message', 'Unknown error')}"
                    )
                    if agent_result.rate_limit:
                        raw_headers = agent_result.rate_limit.get("raw_headers")
                        if raw_headers is not None:
                            log_msg += f" | headers={dict(raw_headers)}"
                    logger.warning(log_msg)
                    
                    if is_retryable and attempt < len(self.backoffs):
                        # Use retry_after from rate_limit if available
                        delay = self.backoffs[attempt]
                        if agent_result.rate_limit:
                            retry_after = agent_result.rate_limit.get("retry_after")
                            if retry_after:
                                delay = max(delay, retry_after)
                        
                        delay = self._apply_jitter(delay)
                        logger.info(f"Retrying in {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        last_error_result = agent_result
                        continue
                    else:
                        # Non-retryable or out of retries
                        last_error_result = agent_result
                        if not is_retryable:
                            break  # Don't retry non-retryable errors
                        continue
                
                # Success case
                payload = agent_result.output_payload()
                merged_usage = _merge_usage(agent_result, total_api_calls)
                merged_cost = total_cost if total_cost else agent_result.cost

                if payload:
                    return AgentResult(
                        output=agent_result.output,
                        content=agent_result.content,
                        raw=agent_result.raw,
                        usage=merged_usage,
                        cost=merged_cost,
                        metadata=agent_result.metadata,
                        finish_reason=agent_result.finish_reason,
                        rate_limit=agent_result.rate_limit,
                        provider_data=agent_result.provider_data,
                    )

                if self.retry_on_empty:
                    raise ValueError("Empty response from agent")

                return AgentResult(
                    output=agent_result.output,
                    content=agent_result.content,
                    raw=agent_result.raw,
                    usage=merged_usage,
                    cost=merged_cost,
                    metadata=agent_result.metadata,
                    finish_reason=agent_result.finish_reason,
                    rate_limit=agent_result.rate_limit,
                    provider_data=agent_result.provider_data,
                )

            except Exception as e:
                last_error = e
                log_msg = f"Attempt {attempt + 1}/{max_attempts} failed: {e}"
                # Extract headers from error response if available
                response = getattr(e, "response", None)
                if response is not None:
                    headers = getattr(response, "headers", None)
                    if headers is not None:
                        log_msg += f" | headers={dict(headers)}"
                logger.warning(log_msg)

                # If we have more retries, wait with jitter
                if attempt < len(self.backoffs):
                    delay = self._apply_jitter(self.backoffs[attempt])
                    logger.info(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(f"All {max_attempts} attempts failed.")
        
        usage = {"api_calls": total_api_calls} if total_api_calls else None
        cost = total_cost if total_cost else None
        
        # Prefer structured error from adapter over exception
        if last_error_result and last_error_result.error:
            return AgentResult(
                output=last_error_result.output,
                content=last_error_result.content,
                raw=last_error_result.raw,
                usage=_merge_usage(last_error_result, total_api_calls),
                cost=cost,
                metadata=last_error_result.metadata,
                finish_reason="error",
                error=last_error_result.error,
                rate_limit=last_error_result.rate_limit,
                provider_data=last_error_result.provider_data,
            )
        
        # Fall back to exception-based error
        error_dict: Dict[str, Any] = {
            "code": "server_error",
            "type": type(last_error).__name__ if last_error else "UnknownError",
            "message": str(last_error) if last_error else "LLM call failed",
            "retryable": False,  # Already exhausted retries
        }
        status_code = _extract_status_code(last_error)
        if status_code is not None:
            error_dict["status_code"] = status_code
            if status_code == 429:
                error_dict["code"] = "rate_limit"
        
        # Build provider_data with raw headers from exception
        provider_data = None
        headers = _extract_error_headers(last_error)
        if headers:
            provider_data = {"raw_headers": headers}

        return AgentResult(
            output=None,
            raw=last_error,
            usage=usage,
            cost=cost,
            finish_reason="error",
            error=error_dict,
            provider_data=provider_data,
        )


# MDAP Voting Execution Type

@dataclass
class MDAPMetrics:
    """Execution metrics collected during MDAP runs."""
    total_samples: int = 0
    total_red_flags: int = 0
    red_flags_by_reason: Dict[str, int] = field(default_factory=dict)
    samples_per_step: List[int] = field(default_factory=list)

    def record_red_flag(self, reason: str):
        self.total_red_flags += 1
        self.red_flags_by_reason[reason] = self.red_flags_by_reason.get(reason, 0) + 1


@register_execution_type("mdap_voting")
class MDAPVotingExecution(ExecutionType):
    """
    Multi-sample with first-to-ahead-by-k voting.
    
    Implements the voting algorithm from the MAKER paper.
    """
    
    def __init__(
        self,
        k_margin: int = 3,
        max_candidates: int = 10,
        max_response_tokens: Optional[int] = None
    ):
        self.k_margin = k_margin
        self.max_candidates = max_candidates
        self.max_response_tokens = max_response_tokens
        self.metrics = MDAPMetrics()
        
        # Loaded from agent metadata
        self._patterns: Dict[str, Tuple[re.Pattern, str]] = {}
        self._validation_schema: Optional[Dict] = None
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MDAPVotingExecution":
        return cls(
            k_margin=config.get("k_margin", 3),
            max_candidates=config.get("max_candidates", 10),
            max_response_tokens=config.get("max_response_tokens")
        )
    
    def _configure_from_executor(self, executor: AgentExecutor):
        """Load parsing and validation config from executor metadata."""
        metadata = getattr(executor, "metadata", {}) or {}

        # Check if metadata overrides execution config
        mdap_config = metadata.get('mdap', {}) if isinstance(metadata, dict) else {}
        if mdap_config.get('k_margin'):
            self.k_margin = mdap_config['k_margin']
        if mdap_config.get('max_candidates'):
            self.max_candidates = mdap_config['max_candidates']
        if mdap_config.get('max_response_tokens'):
            self.max_response_tokens = mdap_config['max_response_tokens']

        # Load parsing patterns
        parsing_config = metadata.get('parsing', {}) if isinstance(metadata, dict) else {}
        self._patterns = {}
        for field_name, field_config in parsing_config.items():
            pattern = field_config.get('pattern')
            if pattern:
                self._patterns[field_name] = (
                    re.compile(pattern, re.DOTALL),
                    field_config.get('type', 'str')
                )

        # Load validation schema
        self._validation_schema = metadata.get('validation', None) if isinstance(metadata, dict) else None
    
    def _parse_response(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response using regex patterns."""
        if not self._patterns:
            return None

        result = {}
        for field_name, (pattern, field_type) in self._patterns.items():
            match = pattern.search(content)
            if match:
                value = match.group(1)
                if field_type == 'json':
                    try:
                        result[field_name] = json.loads(value)
                    except json.JSONDecodeError:
                        return None
                elif field_type == 'int':
                    try:
                        result[field_name] = int(value)
                    except ValueError:
                        return None
                else:
                    result[field_name] = value
            else:
                return None

        return result
    
    def _validate_parsed(self, parsed: Dict[str, Any]) -> bool:
        """Validate parsed result against JSON Schema."""
        if not self._validation_schema:
            return True

        try:
            import jsonschema
            jsonschema.validate(instance=parsed, schema=self._validation_schema)
            return True
        except Exception:
            return False
    
    def _check_red_flags(self, content: str, parsed: Optional[Dict[str, Any]]) -> Optional[str]:
        """Check response for red flags per MAKER paper."""
        if parsed is None:
            return "format_error"

        if not self._validate_parsed(parsed):
            return "validation_failed"

        # Only check response length if max_response_tokens is set
        if self.max_response_tokens is not None:
            estimated_tokens = len(content) // 4
            if estimated_tokens > self.max_response_tokens:
                return "length_exceeded"

        return None

    def _extract_candidate(self, result: AgentResult) -> tuple[Optional[Dict[str, Any]], str]:
        """Extract candidate payload and content for voting."""
        content = result.content or ""

        if self._patterns:
            parsed = self._parse_response(content) if content else None
            return parsed, content

        if result.output is not None:
            payload = result.output
            content_for_length = content or json.dumps(payload, sort_keys=True)
            return payload, content_for_length

        if content:
            return {"content": content}, content

        return None, content

    async def execute(
        self,
        executor: AgentExecutor,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> AgentResult:
        """
        Multi-sample with voting - replaces single agent call.

        Returns the winning parsed response or empty AgentResult.
        """
        self._configure_from_executor(executor)

        votes: Counter = Counter()
        responses: Dict[str, Any] = {}
        num_samples = 0
        total_api_calls = 0
        total_cost = 0.0

        for _ in range(self.max_candidates):
            try:
                result = await executor.execute(input_data, context=context, session_id=session_id)
                agent_result = coerce_agent_result(result)
                num_samples += 1
                self.metrics.total_samples += 1
                total_api_calls += _extract_api_calls(agent_result)
                total_cost += _extract_cost(agent_result)

                candidate, content = self._extract_candidate(agent_result)
                if candidate is None:
                    flag_reason = "format_error"
                else:
                    flag_reason = self._check_red_flags(content, candidate)

                if flag_reason:
                    self.metrics.record_red_flag(flag_reason)
                    continue

                key = json.dumps(candidate, sort_keys=True) if not isinstance(candidate, str) else candidate
                votes[key] += 1
                responses[key] = candidate

                if votes[key] >= self.k_margin:
                    self.metrics.samples_per_step.append(num_samples)
                    usage = {"api_calls": total_api_calls} if total_api_calls else None
                    cost = total_cost if total_cost else None
                    return AgentResult(
                        output=responses[key],
                        raw=agent_result.raw,
                        usage=usage,
                        cost=cost,
                    )

                if len(votes) >= 2:
                    top = votes.most_common(2)
                    if top[0][1] - top[1][1] >= self.k_margin:
                        self.metrics.samples_per_step.append(num_samples)
                        usage = {"api_calls": total_api_calls} if total_api_calls else None
                        cost = total_cost if total_cost else None
                        return AgentResult(
                            output=responses[top[0][0]],
                            usage=usage,
                            cost=cost,
                        )

            except Exception as e:
                logger.warning(f"Sample failed: {e}")
                continue

        # Majority fallback
        self.metrics.samples_per_step.append(num_samples)
        usage = {"api_calls": total_api_calls} if total_api_calls else None
        cost = total_cost if total_cost else None

        if votes:
            winner_key = votes.most_common(1)[0][0]
            return AgentResult(output=responses[winner_key], usage=usage, cost=cost)

        return AgentResult(usage=usage, cost=cost)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return {
            "total_samples": self.metrics.total_samples,
            "total_red_flags": self.metrics.total_red_flags,
            "red_flags_by_reason": self.metrics.red_flags_by_reason,
            "samples_per_step": self.metrics.samples_per_step,
        }


__all__ = [
    "ExecutionType",
    "DefaultExecution",
    "ParallelExecution",
    "RetryExecution",
    "MDAPVotingExecution",
    "get_execution_type",
    "register_execution_type",
]
