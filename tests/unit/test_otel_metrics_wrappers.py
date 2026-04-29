"""Tests for OTel metric wrapper classes (OTelCounter, OTelGauge, OTelHistogram)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_otel_meter():
    """Provide a mock meter so tests run without OTel Collector."""
    mock_meter = MagicMock()
    mock_counter = MagicMock()
    mock_gauge = MagicMock()
    mock_histogram = MagicMock()
    mock_meter.create_counter.return_value = mock_counter
    mock_meter.create_gauge.return_value = mock_gauge
    mock_meter.create_histogram.return_value = mock_histogram

    with patch("src.observability.metrics.otel_metrics.get_meter", return_value=mock_meter):
        yield {
            "meter": mock_meter,
            "counter": mock_counter,
            "gauge": mock_gauge,
            "histogram": mock_histogram,
        }


def test_otel_counter_labels_inc():
    from src.observability.metrics import OTelCounter

    c = OTelCounter("test_counter", "test help", ["agent"])
    labeled = c.labels(agent="test")
    labeled.inc()
    c._counter.add.assert_called()


def test_otel_counter_inc_amount():
    from src.observability.metrics import OTelCounter

    c = OTelCounter("test_counter2", "test help", ["agent"])
    labeled = c.labels(agent="test")
    labeled.inc(5)
    c._counter.add.assert_called()


def test_otel_gauge_labels_set():
    from src.observability.metrics import OTelGauge

    g = OTelGauge("test_gauge", "test help", ["agent"])
    labeled = g.labels(agent="test")
    labeled.set(42)
    g._gauge.set.assert_called()


def test_otel_histogram_labels_observe():
    from src.observability.metrics import OTelHistogram

    h = OTelHistogram("test_hist", "test help", ["agent"])
    labeled = h.labels(agent="test")
    labeled.observe(0.5)
    h._histogram.record.assert_called()


def test_otel_counter_unlabeled():
    from src.observability.metrics import OTelCounter

    c = OTelCounter("test_unlabeled_counter", "test help")
    c.inc()
    c._counter.add.assert_called_with(1.0, {})


def test_otel_gauge_unlabeled():
    from src.observability.metrics import OTelGauge

    g = OTelGauge("test_unlabeled_gauge", "test help")
    g.set(99)
    g._gauge.set.assert_called_with(99, {})


def test_otel_histogram_unlabeled():
    from src.observability.metrics import OTelHistogram

    h = OTelHistogram("test_unlabeled_hist", "test help")
    h.observe(1.5)
    h._histogram.record.assert_called_with(1.5, {})


def test_init_otel_providers_graceful_degradation():
    """init_otel_providers should not crash when endpoint is unreachable."""
    from src.observability.otel import init_otel_providers

    # Should not raise even with bogus endpoint
    init_otel_providers(service_name="test", endpoint="http://localhost:9999")
