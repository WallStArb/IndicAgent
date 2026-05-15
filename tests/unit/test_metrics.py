"""Tests for OTel metrics (Phase 67 Task 3, updated for OTel in Phase 083-03)."""

from src.observability.metrics import (
    BAR_AUDITOR_GAP_FILL_DLQ_DEPTH,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
)


class TestServiceAuditorMetrics:
    """Verify ServiceAuditorAgent observability metrics (Task 3)."""

    def test_service_auditor_service_restarts_total_registered(self):
        """SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL is an OTel counter with .add()."""
        assert hasattr(SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL, "add")
        # Should not raise
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"service_name": "indicagent-ibkr-provider"})


class TestBarAuditorMetrics:
    """Verify BarAuditorAgent observability metrics (Task 3)."""

    def test_bar_auditor_gap_fill_dlq_depth_registered(self):
        """BAR_AUDITOR_GAP_FILL_DLQ_DEPTH is an OTel up_down_counter with .add()."""
        assert hasattr(BAR_AUDITOR_GAP_FILL_DLQ_DEPTH, "add")
        # Should not raise
        BAR_AUDITOR_GAP_FILL_DLQ_DEPTH.add(1)
