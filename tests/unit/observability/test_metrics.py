"""Tests for OTel metrics (Phase 67 Task 3, updated for OTel in Phase 083-03)."""

from src.observability.metrics import (
    BAR_AUDITOR_GAP_FILL_DLQ_DEPTH,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
)


class TestServiceAuditorMetrics:
    """Verify ServiceAuditor observability metrics (Task 3)."""

    def test_service_auditor_service_restarts_total_registered(self):
        """SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL is an OTel counter with .add()."""
        assert hasattr(SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL, "add")
        # Should not raise
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"service_name": "indicagent-ibkr-provider"})


class TestBarAuditorMetrics:
    """Verify BarAuditor observability metrics (Task 3)."""

    def test_bar_auditor_gap_fill_dlq_depth_registered(self):
        """BAR_AUDITOR_GAP_FILL_DLQ_DEPTH is an OTel up_down_counter with .add()."""
        assert hasattr(BAR_AUDITOR_GAP_FILL_DLQ_DEPTH, "add")
        # Should not raise
        BAR_AUDITOR_GAP_FILL_DLQ_DEPTH.add(1)


# ---------------------------------------------------------------------------
# Phase-105 regression: latency instruments expose .record()
# ---------------------------------------------------------------------------


class TestLatencyMetricInstrumentTypes:
    """Latency/histogram instruments must expose .record() not .add().

    Phase-105 HF-4: OTel histograms created via create_histogram() expose .record().
    Using .add() on a histogram is incorrect — histograms measure distributions
    (latency, response time), not cumulative totals.

    Regression: PLUGIN_DURATION_MS and PERSISTENCE_BATCH_LATENCY must use .record()
    at their call sites, and the instrument must expose this method.
    """

    def test_plugin_duration_ms_exposes_record(self):
        from src.observability.metrics import PLUGIN_DURATION_MS

        assert hasattr(PLUGIN_DURATION_MS, "record"), (
            "PLUGIN_DURATION_MS must be a histogram (expose .record()) "
            "for latency distribution measurement"
        )
        PLUGIN_DURATION_MS.record(5.0, {"plugin_name": "test", "tier": "i1"})

    def test_persistence_batch_latency_exposes_record(self):
        from src.observability.metrics import PERSISTENCE_BATCH_LATENCY

        assert hasattr(
            PERSISTENCE_BATCH_LATENCY, "record"
        ), "PERSISTENCE_BATCH_LATENCY must be a histogram (expose .record())"
        PERSISTENCE_BATCH_LATENCY.record(0.05, {"agent_id": "test"})
