"""Tests for Prometheus metrics (Phase 67 Task 3)."""

from src.observability.metrics import (
    BAR_AUDITOR_GAP_FILL_DLQ_DEPTH,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
)


class TestServiceAuditorMetrics:
    """Verify ServiceAuditorAgent observability metrics (Task 3)."""

    def test_service_auditor_service_restarts_total_registered(self):
        """SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL is registered and usable."""
        # Should not raise ValueError for duplicate registration
        metric = SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.labels(service_name="indicagent-ibkr-provider")
        metric.inc()
        # If we get here, test passes


class TestBarAuditorMetrics:
    """Verify BarAuditorAgent observability metrics (Task 3)."""

    def test_bar_auditor_gap_fill_dlq_depth_registered(self):
        """BAR_AUDITOR_GAP_FILL_DLQ_DEPTH is registered and usable."""
        # Should not raise ValueError for duplicate registration
        BAR_AUDITOR_GAP_FILL_DLQ_DEPTH.inc()
        # If we get here, test passes
