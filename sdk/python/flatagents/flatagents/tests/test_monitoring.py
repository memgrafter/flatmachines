"""Tests for monitoring.py — headful logging opt-in and metrics defaults."""

import logging
import sys
import importlib

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

_ENV_KEYS = (
    "FLATAGENTS_LOG_HANDLER",
    "FLATAGENTS_LOG_LEVEL",
    "FLATAGENTS_LOG_FORMAT",
    "FLATAGENTS_LOG_DIR",
    "FLATAGENTS_METRICS_ENABLED",
    "OTEL_METRICS_EXPORTER",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
)


def _reset_env(monkeypatch):
    """Clear flatagents-related env vars."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _reset_module(mod):
    """Reset flatagents.monitoring internal state."""
    mod._logging_configured = False
    mod._metrics_init_attempted = False
    mod._metrics_enabled = False
    mod._meter = None
    mod._cached_histograms.clear()
    lib_logger = logging.getLogger("flatagents")
    lib_logger.handlers.clear()
    lib_logger.propagate = True


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_flatagents(monkeypatch):
    """Auto-reset env and module state for every test."""
    _reset_env(monkeypatch)
    mod = importlib.import_module("flatagents.monitoring")
    _reset_module(mod)
    yield


# ── Issue 1: setup_logging ──────────────────────────────────────────────────


class TestSetupLoggingDefault:
    """setup_logging() adds no stdout handler and sets propagate=True."""

    def test_no_console_handler_by_default(self):
        from flatagents.monitoring import setup_logging

        setup_logging()
        lib_logger = logging.getLogger("flatagents")

        stdout_handlers = [
            h
            for h in lib_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and h.stream is sys.stdout
        ]
        assert len(stdout_handlers) == 0

    def test_propagate_is_true_by_default(self):
        from flatagents.monitoring import setup_logging

        setup_logging()
        lib_logger = logging.getLogger("flatagents")

        assert lib_logger.propagate is True

    def test_no_duplicate_handlers_on_second_call(self):
        from flatagents.monitoring import setup_logging

        setup_logging()
        setup_logging()
        lib_logger = logging.getLogger("flatagents")

        stdout_handlers = [
            h
            for h in lib_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and h.stream is sys.stdout
        ]
        assert len(stdout_handlers) <= 1


class TestSetupLoggingOptIn:
    """FLATAGENTS_LOG_HANDLER=stdout adds handler and sets propagate=False."""

    @pytest.mark.parametrize(
        "opt_in_value, should_add_handler",
        [
            ("stdout", True),
            ("console", True),
            ("true", True),
            ("STDLONG", False),
            ("1", False),
            ("", False),
        ],
    )
    def test_opt_in_variations(self, opt_in_value, should_add_handler, monkeypatch):
        """Test various env values for FLATAGENTS_LOG_HANDLER."""
        if opt_in_value:
            monkeypatch.setenv("FLATAGENTS_LOG_HANDLER", opt_in_value)

        from flatagents.monitoring import setup_logging

        setup_logging()
        lib_logger = logging.getLogger("flatagents")

        stdout_handlers = [
            h
            for h in lib_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and h.stream is sys.stdout
        ]
        assert len(stdout_handlers) == (1 if should_add_handler else 0)
        # When handler added: propagate=False; when not: propagate=True
        assert lib_logger.propagate == (not should_add_handler)


# ── Issue 2: _init_metrics ─────────────────────────────────────────────────

class TestInitMetricsDefault:
    """_init_metrics() with default env does NOT create console exporter."""

    def test_metrics_disabled_by_default(self):
        """Even when otel is installed, default exporter=none disables metrics."""
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        import flatagents.monitoring as mod
        from flatagents.monitoring import _init_metrics

        _init_metrics()
        assert mod._metrics_enabled is False

    def test_get_meter_returns_none_when_metrics_disabled(self):
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        from flatagents.monitoring import get_meter

        assert get_meter() is None


class TestInitMetricsConsoleExporter:
    """OTEL_METRICS_EXPORTER=console creates a console exporter."""

    def test_metrics_enabled_with_console_exporter(self, monkeypatch):
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "console")

        import flatagents.monitoring as mod
        from flatagents.monitoring import _init_metrics

        _init_metrics()
        assert mod._metrics_enabled is True

    def test_get_meter_returns_meter_with_console_exporter(self, monkeypatch):
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "console")

        from flatagents.monitoring import get_meter

        assert get_meter() is not None
