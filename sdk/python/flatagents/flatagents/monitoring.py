"""
Monitoring and observability utilities for FlatAgents.

Provides standardized logging configuration and OpenTelemetry-based metrics.
"""

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import is_dataclass, fields
from enum import Enum
from typing import Any, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Global logger registry
_loggers: Dict[str, logging.Logger] = {}
_logging_configured = False


class JSONFormatter(logging.Formatter):
    """
    Production-ready JSON log formatter.
    
    Properly escapes message content and includes exception info.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "time": self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if any
        if hasattr(record, 'extra') and record.extra:
            log_entry["extra"] = record.extra
        
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: Optional[str] = None,
    format: Optional[str] = None,
    force: bool = False
) -> None:
    """
    Configure SDK-wide logging with sensible defaults.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               Defaults to FLATAGENTS_LOG_LEVEL env var or INFO.
        format: Log format style. Options:
                - 'standard': Human-readable with timestamps
                - 'json': Structured JSON logging
                - 'simple': Just level and message
                - Custom format string
                Defaults to FLATAGENTS_LOG_FORMAT env var or 'standard'.
        force: If True, reconfigure even if already configured.
    
    Environment Variables:
        FLATAGENTS_LOG_DIR: If set, logs will be written to files in this directory.
                           Each process gets a unique log file with PID and timestamp.
        FLATAGENTS_LOG_LEVEL: Default log level (DEBUG, INFO, etc.)
        FLATAGENTS_LOG_FORMAT: Log format style
    
    Example:
        >>> from flatagents import setup_logging
        >>> setup_logging(level='DEBUG')
        >>> # Or via environment:
        >>> # export FLATAGENTS_LOG_LEVEL=DEBUG
        >>> # export FLATAGENTS_LOG_FORMAT=json
        >>> # export FLATAGENTS_LOG_DIR=/path/to/logs
    """
    global _logging_configured
    
    if _logging_configured and not force:
        return
    
    # Determine log level
    if level is None:
        level = os.getenv('FLATAGENTS_LOG_LEVEL', 'INFO').upper()
    
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Determine format
    if format is None:
        format = os.getenv('FLATAGENTS_LOG_FORMAT', 'standard')
    
    # Create appropriate formatter
    if format == 'json':
        formatter = JSONFormatter()
    elif format == 'simple':
        log_format = '%(levelname)s - %(message)s'
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
    elif format == 'standard':
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
    else:
        # Custom format string
        formatter = logging.Formatter(format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # Configure the flatagents namespace logger, not the root logger.
    # Applications own the root logger; libraries should only configure
    # their own namespace.
    lib_logger = logging.getLogger("flatagents")
    lib_logger.setLevel(log_level)
    
    # Clear existing handlers if force
    if force:
        lib_logger.handlers.clear()
    
    # Only add a handler if this logger has none yet (avoid duplicates)
    if not lib_logger.handlers:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        lib_logger.addHandler(stdout_handler)
    
    # Prevent propagation to root to avoid duplicate output when the
    # application also configures root-level handlers.
    lib_logger.propagate = False
    
    # Add file handler if FLATAGENTS_LOG_DIR is set
    log_dir = os.getenv('FLATAGENTS_LOG_DIR')
    if log_dir:
        from datetime import datetime
        
        # Create log directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)
        
        # Create unique log file per process (PID + timestamp)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pid = os.getpid()
        log_file = os.path.join(log_dir, f"flatagents_{pid}_{timestamp}.log")
        
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setFormatter(formatter)
        lib_logger.addHandler(file_handler)
        
        # Log where we're writing to
        lib_logger.info(f"Logging to file: {log_file}")
    
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a properly configured logger for a module.
    
    Args:
        name: Logger name (typically __name__ from the calling module)
    
    Returns:
        Configured logger instance
    
    Example:
        >>> from flatagents import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Agent started")
    """
    if name not in _loggers:
        # Ensure logging is configured
        if not _logging_configured:
            setup_logging()
        
        logger = logging.getLogger(name)
        _loggers[name] = logger
    
    return _loggers[name]


# ─────────────────────────────────────────────────────────────────────────────
# Metrics with OpenTelemetry
# ─────────────────────────────────────────────────────────────────────────────

# Lazy imports for OpenTelemetry (optional dependency)
_otel_available = False
_meter = None
_metrics_enabled = False
_metrics_init_attempted = False  # Prevent repeated init attempts
_cached_histograms: Dict[str, Any] = {}  # Cache for histogram instruments

try:
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    _otel_available = True
except ImportError:
    _otel_available = False


def _init_metrics() -> None:
    """Initialize OpenTelemetry metrics if enabled and available."""
    global _meter, _metrics_enabled, _metrics_init_attempted

    _metrics_init_attempted = True

    # Check if metrics should be enabled (default: true)
    enabled = os.getenv('FLATAGENTS_METRICS_ENABLED', 'true').lower() not in ('false', '0', 'no')
    
    if not enabled:
        _metrics_enabled = False
        return
    
    if not _otel_available:
        logger = get_logger(__name__)
        logger.warning(
            "Metrics enabled but OpenTelemetry not available. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
        )
        _metrics_enabled = False
        return
    
    try:
        # Get service name from environment or use default
        service_name = os.getenv('OTEL_SERVICE_NAME', 'flatagents')
        
        # Create resource with service name
        resource = Resource(attributes={
            SERVICE_NAME: service_name
        })
        
        # Check which exporter to use (default to console so metrics are visible)
        exporter_type = os.getenv('OTEL_METRICS_EXPORTER', 'console').lower()
        
        if exporter_type == 'console':
            # Use console exporter for testing/debugging
            try:
                from opentelemetry.sdk.metrics.export import (
                    ConsoleMetricExporter,
                    MetricExporter,
                    MetricExportResult,
                )

                def _to_jsonable(value):
                    if value is None or isinstance(value, (str, int, float, bool)):
                        return value
                    if isinstance(value, Enum):
                        return value.value
                    if is_dataclass(value):
                        return {f.name: _to_jsonable(getattr(value, f.name)) for f in fields(value)}
                    if isinstance(value, dict):
                        return {str(k): _to_jsonable(v) for k, v in value.items()}
                    if isinstance(value, (list, tuple, set)):
                        return [_to_jsonable(v) for v in value]
                    if hasattr(value, "__dict__"):
                        return {str(k): _to_jsonable(v) for k, v in vars(value).items()}
                    return str(value)

                def _compact_metrics_formatter(metrics_data) -> str:
                    try:
                        from opentelemetry.sdk.metrics.export import MetricsJSONEncoder
                        line = json.dumps(metrics_data, cls=MetricsJSONEncoder, separators=(",", ":"))
                    except Exception:
                        try:
                            from opentelemetry.sdk.metrics.export import metrics_to_json
                            compact = metrics_to_json(metrics_data)
                            if isinstance(compact, str):
                                line = compact.replace("\n", "")
                            else:
                                line = json.dumps(compact, separators=(",", ":"))
                        except Exception:
                            line = json.dumps(_to_jsonable(metrics_data), separators=(",", ":"))
                    if not line.endswith("\n"):
                        line = f"{line}\n"
                    return line

                class _CompactConsoleMetricExporter(MetricExporter):
                    def __init__(self, preferred_temporality=None, preferred_aggregation=None):
                        super().__init__(
                            preferred_temporality=preferred_temporality,
                            preferred_aggregation=preferred_aggregation,
                        )

                    def export(self, metrics_data):
                        try:
                            line = _compact_metrics_formatter(metrics_data)
                            sys.stdout.write(line)
                            sys.stdout.flush()
                            return MetricExportResult.SUCCESS
                        except Exception:
                            return MetricExportResult.FAILURE

                    def shutdown(self, timeout_millis: int = 30000):
                        return None

                    def force_flush(self, timeout_millis: int = 30000):
                        return True

                try:
                    import inspect
                    if "formatter" in inspect.signature(ConsoleMetricExporter).parameters:
                        exporter = ConsoleMetricExporter(formatter=_compact_metrics_formatter)
                    else:
                        exporter = _CompactConsoleMetricExporter()
                except Exception:
                    exporter = _CompactConsoleMetricExporter()
            except ImportError:
                logger = get_logger(__name__)
                logger.warning("Console exporter not available, falling back to OTLP")
                exporter = OTLPMetricExporter(
                    endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'),
                )
        else:
            # Configure OTLP exporter (supports Datadog, Honeycomb, etc.)
            exporter = OTLPMetricExporter(
                endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT'),
                # Headers can be set via OTEL_EXPORTER_OTLP_HEADERS env var
            )
        
        # Create meter provider with periodic export
        reader = PeriodicExportingMetricReader(
            exporter=exporter,
            export_interval_millis=int(os.getenv('OTEL_METRIC_EXPORT_INTERVAL', '5000' if exporter_type == 'console' else '60000'))
        )
        
        provider = MeterProvider(
            resource=resource,
            metric_readers=[reader]
        )
        
        metrics.set_meter_provider(provider)
        _meter = metrics.get_meter(__name__)
        _metrics_enabled = True
        
        logger = get_logger(__name__)
        logger.info(f"OpenTelemetry metrics enabled for service: {service_name}")
        
    except Exception as e:
        logger = get_logger(__name__)
        logger.warning(f"Failed to initialize OpenTelemetry metrics: {e}")
        _metrics_enabled = False


def get_meter():
    """
    Get the OpenTelemetry meter for creating custom metrics.
    
    Returns:
        OpenTelemetry Meter instance or None if metrics disabled
    
    Example:
        >>> from flatagents import get_meter
        >>> meter = get_meter()
        >>> if meter:
        ...     counter = meter.create_counter("my_custom_metric")
        ...     counter.add(1, {"attribute": "value"})
    """
    global _meter

    if not _metrics_init_attempted:
        _init_metrics()

    return _meter


class AgentMonitor:
    """
    Context manager for tracking agent execution metrics.
    
    Automatically tracks:
    - Execution duration
    - Success/failure status
    - Custom metrics via the metrics dict
    
    Example:
        >>> from flatagents import AgentMonitor
        >>> with AgentMonitor("my-agent") as monitor:
        ...     # Do agent work
        ...     monitor.metrics["tokens"] = 1500
        ...     monitor.metrics["cost"] = 0.03
        >>> # Metrics automatically emitted on exit
    """
    
    def __init__(self, agent_id: str, extra_attributes: Optional[Dict[str, Any]] = None):
        """
        Initialize the monitor.
        
        Args:
            agent_id: Identifier for this agent/operation
            extra_attributes: Additional attributes to attach to all metrics
        """
        self.agent_id = agent_id
        self.start_time = None
        self.metrics: Dict[str, Any] = {}
        self.extra_attributes = extra_attributes or {}
        self.logger = get_logger(f"flatagents.monitor.{agent_id}")
        
        # Get or create metric instruments
        self._meter = get_meter()
        if self._meter:
            self._duration_histogram = self._meter.create_histogram(
                "flatagents.agent.duration",
                unit="ms",
                description="Agent execution duration"
            )
            self._token_counter = self._meter.create_counter(
                "flatagents.agent.tokens",
                description="Total tokens used by agent"
            )
            self._input_token_counter = self._meter.create_counter(
                "flatagents.agent.input_tokens",
                description="Input/prompt tokens used by agent"
            )
            self._output_token_counter = self._meter.create_counter(
                "flatagents.agent.output_tokens",
                description="Output/completion tokens used by agent"
            )
            self._cache_read_token_counter = self._meter.create_counter(
                "flatagents.agent.cache_read_tokens",
                description="Cache read tokens (prompt caching)"
            )
            self._cache_write_token_counter = self._meter.create_counter(
                "flatagents.agent.cache_write_tokens",
                description="Cache write tokens (prompt caching)"
            )
            self._cost_counter = self._meter.create_counter(
                "flatagents.agent.cost",
                description="Estimated cost of agent execution"
            )
            self._status_counter = self._meter.create_counter(
                "flatagents.agent.executions",
                description="Agent execution count by status"
            )
            # Rate limit gauges
            self._ratelimit_remaining_requests = self._meter.create_gauge(
                "flatagents.ratelimit.remaining_requests",
                description="Remaining requests before rate limit"
            )
            self._ratelimit_remaining_tokens = self._meter.create_gauge(
                "flatagents.ratelimit.remaining_tokens",
                description="Remaining tokens before rate limit"
            )
            self._ratelimit_limit_requests = self._meter.create_gauge(
                "flatagents.ratelimit.limit_requests",
                description="Rate limit for requests"
            )
            self._ratelimit_limit_tokens = self._meter.create_gauge(
                "flatagents.ratelimit.limit_tokens",
                description="Rate limit for tokens"
            )
    
    def __enter__(self):
        """Start monitoring."""
        self.start_time = time.time()
        self.logger.debug(f"Agent {self.agent_id} started")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop monitoring and emit metrics."""
        duration_ms = (time.time() - self.start_time) * 1000
        status = "success" if exc_type is None else "error"
        
        # Build attributes
        attributes = {
            "agent_id": self.agent_id,
            "status": status,
            **self.extra_attributes
        }
        
        if exc_type is not None:
            attributes["error_type"] = exc_type.__name__
        
        # Log completion with optional details
        log_parts = [f"Agent {self.agent_id} completed in {duration_ms:.2f}ms - {status}"]
        
        # Add token breakdown if available (compact + explicit cache fields)
        if (
            "input_tokens" in self.metrics
            or "output_tokens" in self.metrics
            or "cache_read_tokens" in self.metrics
            or "cache_write_tokens" in self.metrics
        ):
            in_tok = self.metrics.get("input_tokens", 0)
            out_tok = self.metrics.get("output_tokens", 0)
            cache_in = self.metrics.get("cache_read_tokens", 0)
            cache_out = self.metrics.get("cache_write_tokens", 0)
            # ci=cached input, i=input, co=cached output, o=output
            tok_str = f"tok ci={cache_in} i={in_tok} co={cache_out} o={out_tok}"
            log_parts.append(tok_str)
        
        # Add rate limit info if available
        if "ratelimit_remaining_requests" in self.metrics:
            remaining = self.metrics["ratelimit_remaining_requests"]
            limit = self.metrics.get("ratelimit_limit_requests", "?")
            log_parts.append(f"ratelimit: {remaining}/{limit} reqs")
        
        self.logger.info(" | ".join(log_parts))
        
        # Emit metrics if enabled
        if self._meter:
            self._duration_histogram.record(duration_ms, attributes)
            self._status_counter.add(1, attributes)
            
            # Token metrics
            if "tokens" in self.metrics:
                self._token_counter.add(self.metrics["tokens"], attributes)
            if "input_tokens" in self.metrics:
                self._input_token_counter.add(self.metrics["input_tokens"], attributes)
            if "output_tokens" in self.metrics:
                self._output_token_counter.add(self.metrics["output_tokens"], attributes)
            if "cache_read_tokens" in self.metrics:
                self._cache_read_token_counter.add(self.metrics["cache_read_tokens"], attributes)
            if "cache_write_tokens" in self.metrics:
                self._cache_write_token_counter.add(self.metrics["cache_write_tokens"], attributes)
            
            if "cost" in self.metrics:
                self._cost_counter.add(self.metrics["cost"], attributes)
            
            # Rate limit metrics (gauges - record current value)
            if "ratelimit_remaining_requests" in self.metrics:
                self._ratelimit_remaining_requests.set(
                    self.metrics["ratelimit_remaining_requests"], attributes
                )
            if "ratelimit_remaining_tokens" in self.metrics:
                self._ratelimit_remaining_tokens.set(
                    self.metrics["ratelimit_remaining_tokens"], attributes
                )
            if "ratelimit_limit_requests" in self.metrics:
                self._ratelimit_limit_requests.set(
                    self.metrics["ratelimit_limit_requests"], attributes
                )
            if "ratelimit_limit_tokens" in self.metrics:
                self._ratelimit_limit_tokens.set(
                    self.metrics["ratelimit_limit_tokens"], attributes
                )
        
        # Don't suppress exceptions
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Convenience context manager for temporary metrics
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def track_operation(operation_name: str, **attributes):
    """
    Track duration of an operation.
    
    Args:
        operation_name: Name of the operation
        **attributes: Additional attributes to attach
    
    Example:
        >>> from flatagents.monitoring import track_operation
        >>> with track_operation("llm_call", model="gpt-4"):
        ...     response = await llm.call(messages)
    """
    meter = get_meter()
    start_time = time.time()
    
    try:
        yield
        status = "success"
    except Exception as e:
        status = "error"
        attributes["error_type"] = type(e).__name__
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        
        if meter:
            # Cache histogram to avoid recreating on each call
            cache_key = f"flatagents.{operation_name}.duration"
            if cache_key not in _cached_histograms:
                _cached_histograms[cache_key] = meter.create_histogram(
                    cache_key,
                    unit="ms",
                    description=f"Duration of {operation_name}"
                )
            _cached_histograms[cache_key].record(duration_ms, {**attributes, "status": status})


__all__ = [
    "setup_logging",
    "get_logger",
    "get_meter",
    "AgentMonitor",
    "track_operation",
]
