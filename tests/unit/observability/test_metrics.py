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
# Phase-105 regression: shadow gauges expose .set(), latency instruments expose .record()
# ---------------------------------------------------------------------------


class TestShadowMetricInstrumentTypes:
    """Shadow gauges must be point gauges (expose .set()), not counters or up-down-counters.

    Phase-105 HF-4: SHADOW_N_RESOLVED, SHADOW_WIN_RATE, SHADOW_EV_R, SHADOW_EV_CI_LOWER,
    SHADOW_DAYS_TO_GATE, and SHADOW_PROMOTION_READY are all point gauges created via
    point_gauge() which calls create_gauge(). create_gauge() returns an OTel Gauge object
    that exposes .set() for point-in-time absolute values.

    Regression: if any of these were created via create_counter() or
    create_up_down_counter(), they would expose .add() instead of .set(), causing
    the shadow auditor to write cumulative garbage instead of current values.
    """

    def test_shadow_n_resolved_exposes_set(self):
        from src.observability.metrics import SHADOW_N_RESOLVED

        assert hasattr(SHADOW_N_RESOLVED, "set"), (
            "SHADOW_N_RESOLVED must be a point gauge (expose .set()) "
            "for point-in-time absolute values"
        )
        # Calling .set() must not raise (OTel SDK may no-op in test mode)
        SHADOW_N_RESOLVED.set(42, {"plugin": "test"})

    def test_shadow_win_rate_exposes_set(self):
        from src.observability.metrics import SHADOW_WIN_RATE

        assert hasattr(
            SHADOW_WIN_RATE, "set"
        ), "SHADOW_WIN_RATE must be a point gauge (expose .set())"
        SHADOW_WIN_RATE.set(0.58, {"plugin": "test"})

    def test_shadow_ev_r_exposes_set(self):
        from src.observability.metrics import SHADOW_EV_R

        assert hasattr(SHADOW_EV_R, "set"), "SHADOW_EV_R must be a point gauge (expose .set())"
        SHADOW_EV_R.set(0.12, {"plugin": "test"})

    def test_shadow_ev_ci_lower_exposes_set(self):
        from src.observability.metrics import SHADOW_EV_CI_LOWER

        assert hasattr(
            SHADOW_EV_CI_LOWER, "set"
        ), "SHADOW_EV_CI_LOWER must be a point gauge (expose .set())"
        SHADOW_EV_CI_LOWER.set(0.05, {"plugin": "test"})

    def test_shadow_days_to_gate_exposes_set(self):
        from src.observability.metrics import SHADOW_DAYS_TO_GATE

        assert hasattr(
            SHADOW_DAYS_TO_GATE, "set"
        ), "SHADOW_DAYS_TO_GATE must be a point gauge (expose .set())"
        SHADOW_DAYS_TO_GATE.set(14.5, {"plugin": "test"})

    def test_shadow_promotion_ready_exposes_set(self):
        from src.observability.metrics import SHADOW_PROMOTION_READY

        assert hasattr(
            SHADOW_PROMOTION_READY, "set"
        ), "SHADOW_PROMOTION_READY must be a point gauge (expose .set())"
        SHADOW_PROMOTION_READY.set(1, {"plugin": "test"})


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

    def test_llm_call_duration_exposes_record(self):
        from src.observability.metrics import LLM_CALL_DURATION

        assert hasattr(
            LLM_CALL_DURATION, "record"
        ), "LLM_CALL_DURATION must be a histogram (expose .record())"
        LLM_CALL_DURATION.record(250.0, {"provider": "ollama", "call_type": "per_signal"})
