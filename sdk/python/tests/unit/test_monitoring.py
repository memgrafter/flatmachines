"""Unit tests for flatagents.monitoring headful logging behavior."""

import importlib
import logging
import sys

import pytest


_ENV_KEYS = (
    "FLATAGENTS_LOG_HANDLER",
    "FLATAGENTS_LOG_LEVEL",
    "FLATAGENTS_LOG_FORMAT",
    "FLATAGENTS_LOG_DIR",
    "FLATAGENTS_METRICS_ENABLED",
    "OTEL_METRICS_EXPORTER",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_METRIC_EXPORT_INTERVAL",
)


@pytest.fixture(autouse=True)
def clean_monitoring_state(monkeypatch):
    """Keep monitoring globals and logger configuration isolated per test."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    monitoring = importlib.import_module("flatagents.monitoring")
    logger = logging.getLogger("flatagents")

    original_state = {
        "_logging_configured": monitoring._logging_configured,
        "_metrics_init_attempted": monitoring._metrics_init_attempted,
        "_metrics_enabled": monitoring._metrics_enabled,
        "_meter": monitoring._meter,
        "handlers": list(logger.handlers),
        "level": logger.level,
        "propagate": logger.propagate,
        "cached_histograms": dict(monitoring._cached_histograms),
    }

    monitoring._logging_configured = False
    monitoring._metrics_init_attempted = False
    monitoring._metrics_enabled = False
    monitoring._meter = None
    monitoring._cached_histograms.clear()
    logger.handlers.clear()
    logger.propagate = True

    yield monitoring

    monitoring._logging_configured = original_state["_logging_configured"]
    monitoring._metrics_init_attempted = original_state["_metrics_init_attempted"]
    monitoring._metrics_enabled = original_state["_metrics_enabled"]
    monitoring._meter = original_state["_meter"]
    monitoring._cached_histograms.clear()
    monitoring._cached_histograms.update(original_state["cached_histograms"])
    logger.handlers.clear()
    logger.handlers.extend(original_state["handlers"])
    logger.setLevel(original_state["level"])
    logger.propagate = original_state["propagate"]


class TestSetupLoggingHeadfulDefaults:
    def test_default_adds_no_stdout_handler_and_propagates(self):
        from flatagents.monitoring import setup_logging

        setup_logging()

        logger = logging.getLogger("flatagents")
        stdout_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and handler.stream is sys.stdout
        ]

        assert stdout_handlers == []
        assert logger.propagate is True

    def test_default_second_call_does_not_add_stdout_handler(self):
        from flatagents.monitoring import setup_logging

        setup_logging()
        setup_logging()

        logger = logging.getLogger("flatagents")
        stdout_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and handler.stream is sys.stdout
        ]

        assert stdout_handlers == []
        assert logger.propagate is True


class TestSetupLoggingConsoleOptIn:
    @pytest.mark.parametrize("opt_in_value", ["stdout", "console", "true"])
    def test_log_handler_env_adds_stdout_handler_and_disables_propagation(
        self, monkeypatch, opt_in_value
    ):
        monkeypatch.setenv("FLATAGENTS_LOG_HANDLER", opt_in_value)

        from flatagents.monitoring import setup_logging

        setup_logging()

        logger = logging.getLogger("flatagents")
        stdout_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and handler.stream is sys.stdout
        ]

        assert len(stdout_handlers) == 1
        assert logger.propagate is False

    @pytest.mark.parametrize("opt_in_value", ["", "1", "yes", "stderr", "STDLONG"])
    def test_non_opt_in_values_do_not_add_stdout_handler(
        self, monkeypatch, opt_in_value
    ):
        if opt_in_value:
            monkeypatch.setenv("FLATAGENTS_LOG_HANDLER", opt_in_value)

        from flatagents.monitoring import setup_logging

        setup_logging()

        logger = logging.getLogger("flatagents")
        stdout_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.StreamHandler)
            and handler.stream is sys.stdout
        ]

        assert stdout_handlers == []
        assert logger.propagate is True


class TestInitMetricsExporterSelection:
    def test_default_metrics_exporter_none_skips_reader_provider_and_stdout(
        self, monkeypatch, capsys
    ):
        import flatagents.monitoring as monitoring

        monkeypatch.setattr(monitoring, "_otel_available", True)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("metrics exporter setup should be skipped by default")

        monkeypatch.setattr(
            monitoring,
            "PeriodicExportingMetricReader",
            fail_if_called,
            raising=False,
        )
        monkeypatch.setattr(monitoring, "MeterProvider", fail_if_called, raising=False)
        monkeypatch.setattr(monitoring.metrics, "set_meter_provider", fail_if_called)
        monkeypatch.setattr(monitoring.metrics, "get_meter", fail_if_called)

        monitoring._init_metrics()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert monitoring._metrics_init_attempted is True
        assert monitoring._metrics_enabled is False
        assert monitoring._meter is None

    def test_console_exporter_opt_in_creates_console_exporter(self, monkeypatch):
        try:
            import opentelemetry  # noqa: F401
        except ImportError:
            pytest.skip("opentelemetry not installed")

        import flatagents.monitoring as monitoring

        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "console")
        monkeypatch.setattr(monitoring, "_otel_available", True)

        captured = {}
        fake_meter = object()

        class FakeMetricReader:
            def __init__(self, exporter, export_interval_millis):
                captured["exporter"] = exporter
                captured["export_interval_millis"] = export_interval_millis

        class FakeMeterProvider:
            def __init__(self, resource, metric_readers):
                captured["provider_resource"] = resource
                captured["metric_readers"] = metric_readers

        def fake_set_meter_provider(provider):
            captured["meter_provider"] = provider

        def fake_get_meter(name):
            captured["meter_name"] = name
            return fake_meter

        monkeypatch.setattr(
            monitoring,
            "PeriodicExportingMetricReader",
            FakeMetricReader,
            raising=False,
        )
        monkeypatch.setattr(monitoring, "MeterProvider", FakeMeterProvider, raising=False)
        monkeypatch.setattr(monitoring.metrics, "set_meter_provider", fake_set_meter_provider)
        monkeypatch.setattr(monitoring.metrics, "get_meter", fake_get_meter)

        monitoring._init_metrics()

        exporter = captured["exporter"]
        assert exporter.__class__.__name__ in {
            "ConsoleMetricExporter",
            "_CompactConsoleMetricExporter",
        }
        assert captured["export_interval_millis"] == 5000
        assert captured["metric_readers"] and isinstance(
            captured["metric_readers"][0], FakeMetricReader
        )
        assert "meter_provider" in captured
        assert monitoring._metrics_enabled is True
        assert monitoring._meter is fake_meter
