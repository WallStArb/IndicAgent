"""Unit tests for SignalAuditorAgent.

Covers:
- topics_produced includes signal_audit and signal_replay_requests topics
- _process_coverage_results: zero-signal result triggers SignalReplayRequest publish
- _process_coverage_results: non-zero signal result does NOT trigger replay request
- _process_coverage_results: p95 > threshold triggers WARNING log
- _run_audit calls batch_signal_coverage and publishes gap events + replay requests
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.audit_utils import SignalCoverageResult
from src.core.schemas.market_events import SignalReplayRequest
from src.core.stream_keys import topic_signal_audit, topic_signal_replay_requests


def _make_agent(env_name: str = "development"):
    """Create SignalAuditorAgent via __new__ bypassing __init__."""
    from services.signal_auditor_agent import SignalAuditorAgent

    agent = SignalAuditorAgent.__new__(SignalAuditorAgent)
    agent.name = "signal_auditor_agent"
    agent._env_name = env_name
    agent._settings = MagicMock()
    agent._kafka_producer = AsyncMock()
    agent._db_pool = MagicMock()
    agent.logger = MagicMock()
    agent.logger.warning = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.error = MagicMock()
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = True

    # Inject Prometheus metric stubs to avoid duplicate-registration in tests
    agent._audits_run = MagicMock()
    agent._coverage_gaps_published = MagicMock()
    agent._audit_errors = MagicMock()
    agent._audit_duration = MagicMock()
    # context manager for _audit_duration.time()
    _time_ctx = agent._audit_duration.time.return_value.__enter__ = MagicMock(return_value=None)
    agent._audit_duration.time.return_value.__exit__ = MagicMock(return_value=False)
    agent._signal_coverage_pct = MagicMock()
    agent._pipeline_lag_p50 = MagicMock()
    agent._pipeline_lag_p95 = MagicMock()
    agent._cis_mean = MagicMock()
    agent._cis_stddev = MagicMock()

    return agent


def _make_coverage_result(
    symbol: str = "ES",
    tf: str = "1m",
    signal_count: int = 0,
    p50_lag_ms: float | None = None,
    p95_lag_ms: float | None = None,
) -> SignalCoverageResult:
    return SignalCoverageResult(
        symbol=symbol,
        tf=tf,
        session_start=datetime(2026, 4, 9, 14, 30, tzinfo=UTC),
        session_end=datetime(2026, 4, 9, 21, 0, tzinfo=UTC),
        signal_count=signal_count,
        p50_lag_ms=p50_lag_ms,
        p95_lag_ms=p95_lag_ms,
    )


class TestTopicsProduced:
    """topics_produced must include both audit and replay_requests topics."""

    def test_topics_produced_includes_signal_audit(self):
        """topics_produced contains topic_signal_audit(env)."""
        from services.signal_auditor_agent import SignalAuditorAgent

        agent = SignalAuditorAgent.__new__(SignalAuditorAgent)
        agent._env_name = "development"

        produced = SignalAuditorAgent.topics_produced.fget(agent)
        assert topic_signal_audit("development") in produced

    def test_topics_produced_includes_signal_replay_requests(self):
        """topics_produced contains topic_signal_replay_requests(env)."""
        from services.signal_auditor_agent import SignalAuditorAgent

        agent = SignalAuditorAgent.__new__(SignalAuditorAgent)
        agent._env_name = "development"

        produced = SignalAuditorAgent.topics_produced.fget(agent)
        assert topic_signal_replay_requests("development") in produced

    def test_topics_produced_has_two_topics(self):
        """topics_produced returns exactly 2 topics."""
        from services.signal_auditor_agent import SignalAuditorAgent

        agent = SignalAuditorAgent.__new__(SignalAuditorAgent)
        agent._env_name = "development"

        produced = SignalAuditorAgent.topics_produced.fget(agent)
        assert len(produced) == 2


class TestProcessCoverageResults:
    """_process_coverage_results: gauge updates, gap events, replay requests."""

    def test_zero_signal_returns_gap_event_and_replay_request(self):
        """Zero signal_count → 1 gap event + 1 SignalReplayRequest returned."""
        agent = _make_agent()
        result = _make_coverage_result(symbol="ES", tf="1m", signal_count=0)

        gap_events, replay_requests = agent._process_coverage_results([result])

        assert len(gap_events) == 1
        assert len(replay_requests) == 1
        req = replay_requests[0]
        assert isinstance(req, SignalReplayRequest)
        assert req.symbol == "ES"
        assert req.tf == "1m"

    def test_nonzero_signal_returns_no_replay_request(self):
        """signal_count > 0 → no replay request emitted."""
        agent = _make_agent()
        result = _make_coverage_result(symbol="ES", tf="1m", signal_count=5)

        gap_events, replay_requests = agent._process_coverage_results([result])

        assert len(replay_requests) == 0
        assert len(gap_events) == 0

    def test_p95_above_threshold_logs_warning(self):
        """p95_lag_ms > _LAG_P95_WARN_MS triggers logger.warning."""
        agent = _make_agent()
        result = _make_coverage_result(
            symbol="NQ",
            tf="5m",
            signal_count=10,
            p50_lag_ms=200.0,
            p95_lag_ms=600.0,
        )

        agent._process_coverage_results([result])

        agent.logger.warning.assert_called_once()
        call_kwargs = agent.logger.warning.call_args
        # First positional arg is the log event key
        assert "lag_threshold_exceeded" in call_kwargs[0][0]

    def test_p95_below_threshold_no_warning(self):
        """p95_lag_ms <= _LAG_P95_WARN_MS → no warning logged."""
        agent = _make_agent()
        result = _make_coverage_result(
            symbol="NQ",
            tf="5m",
            signal_count=10,
            p50_lag_ms=100.0,
            p95_lag_ms=499.0,
        )

        agent._process_coverage_results([result])

        agent.logger.warning.assert_not_called()

    def test_coverage_gauge_set_for_each_result(self):
        """_signal_coverage_pct.labels(...).set() called for each result."""
        agent = _make_agent()
        results = [
            _make_coverage_result(symbol="ES", tf="1m", signal_count=0),
            _make_coverage_result(symbol="ES", tf="5m", signal_count=3),
        ]

        agent._process_coverage_results(results)

        assert agent._signal_coverage_pct.labels.call_count == 2

    def test_p50_p95_gauge_set_when_not_none(self):
        """Lag gauges set when p50/p95 are not None."""
        agent = _make_agent()
        result = _make_coverage_result(
            symbol="ES",
            tf="1m",
            signal_count=5,
            p50_lag_ms=150.0,
            p95_lag_ms=350.0,
        )

        agent._process_coverage_results([result])

        agent._pipeline_lag_p50.labels.assert_called_once()
        agent._pipeline_lag_p95.labels.assert_called_once()

    def test_p50_p95_gauge_not_set_when_none(self):
        """Lag gauges NOT set when p50/p95 are None (no lag data)."""
        agent = _make_agent()
        result = _make_coverage_result(
            symbol="ES",
            tf="1m",
            signal_count=0,
            p50_lag_ms=None,
            p95_lag_ms=None,
        )

        agent._process_coverage_results([result])

        agent._pipeline_lag_p50.labels.assert_not_called()
        agent._pipeline_lag_p95.labels.assert_not_called()

    def test_multiple_zero_signal_results_create_multiple_replay_requests(self):
        """Multiple zero-signal results → multiple replay requests."""
        agent = _make_agent()
        results = [
            _make_coverage_result(symbol="ES", tf="1m", signal_count=0),
            _make_coverage_result(symbol="NQ", tf="5m", signal_count=0),
        ]

        gap_events, replay_requests = agent._process_coverage_results(results)

        assert len(replay_requests) == 2
        symbols = {r.symbol for r in replay_requests}
        assert symbols == {"ES", "NQ"}


class TestRunAudit:
    """_run_audit: calls batch_signal_coverage, publishes gap events + replay requests."""

    @pytest.mark.asyncio
    async def test_run_audit_publishes_replay_request_on_zero_signal(self):
        """_run_audit publishes SignalReplayRequest to topic_signal_replay_requests."""
        agent = _make_agent()
        zero_result = _make_coverage_result(symbol="ES", tf="1m", signal_count=0)

        mock_instruments = [MagicMock()]
        mock_instruments[0].symbol = "ES"

        with (
            patch(
                "services.signal_auditor_agent.batch_signal_coverage",
                new=AsyncMock(return_value=[zero_result]),
            ),
            patch(
                "services.signal_auditor_agent.get_active_contracts",
                return_value=mock_instruments,
            ),
            patch.object(agent, "_check_cis_distribution", new=AsyncMock()),
        ):
            await agent._run_audit(instruments=mock_instruments)

        # Verify at least one publish call to signal_replay_requests topic
        publish_calls = agent._kafka_producer.publish.call_args_list
        replay_topics = [
            c[0][0]
            for c in publish_calls
            if "signal_replay_requests" in c[0][0]
        ]
        assert len(replay_topics) >= 1

    @pytest.mark.asyncio
    async def test_run_audit_no_replay_request_on_nonzero_signal(self):
        """_run_audit does NOT publish replay request when signals exist."""
        agent = _make_agent()
        covered_result = _make_coverage_result(symbol="ES", tf="1m", signal_count=5)

        mock_instruments = [MagicMock()]

        with (
            patch(
                "services.signal_auditor_agent.batch_signal_coverage",
                new=AsyncMock(return_value=[covered_result]),
            ),
            patch(
                "services.signal_auditor_agent.get_active_contracts",
                return_value=mock_instruments,
            ),
            patch.object(agent, "_check_cis_distribution", new=AsyncMock()),
        ):
            await agent._run_audit(instruments=mock_instruments)

        publish_calls = agent._kafka_producer.publish.call_args_list
        replay_topics = [
            c[0][0]
            for c in publish_calls
            if "signal_replay_requests" in c[0][0]
        ]
        assert len(replay_topics) == 0

    @pytest.mark.asyncio
    async def test_run_audit_publishes_gap_event_to_signal_audit_topic(self):
        """_run_audit publishes gap event dict to topic_signal_audit on zero signals."""
        agent = _make_agent()
        zero_result = _make_coverage_result(symbol="ES", tf="1m", signal_count=0)

        mock_instruments = [MagicMock()]

        with (
            patch(
                "services.signal_auditor_agent.batch_signal_coverage",
                new=AsyncMock(return_value=[zero_result]),
            ),
            patch(
                "services.signal_auditor_agent.get_active_contracts",
                return_value=mock_instruments,
            ),
            patch.object(agent, "_check_cis_distribution", new=AsyncMock()),
        ):
            await agent._run_audit(instruments=mock_instruments)

        publish_calls = agent._kafka_producer.publish.call_args_list
        audit_topics = [
            c[0][0]
            for c in publish_calls
            if "signal.audit" in c[0][0]
        ]
        assert len(audit_topics) >= 1

    @pytest.mark.asyncio
    async def test_run_audit_handles_exception_gracefully(self):
        """_run_audit catches exceptions, increments error counter, does not re-raise."""
        agent = _make_agent()

        with (
            patch(
                "services.signal_auditor_agent.batch_signal_coverage",
                new=AsyncMock(side_effect=RuntimeError("DB down")),
            ),
            patch(
                "services.signal_auditor_agent.get_active_contracts",
                return_value=[],
            ),
        ):
            # Should NOT raise
            await agent._run_audit()

        agent._audit_errors.inc.assert_called_once()
