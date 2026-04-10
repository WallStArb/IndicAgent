"""DEPRECATED: tests for SignalAuditorAgent._check_coverage and _check_pipeline_lag — 2026-04-10 — Phase 63.6-02 replaced these methods with batch_signal_coverage() — see tests/unit/service_tests/test_signal_auditor_agent.py

Tests verify:
- Signal coverage gap detection and event emission
- Coverage 1.0 when signals are present in the session window
- Non-trading day skipped (session_window returns (None, None))
- Pipeline lag P50/P95 metric observation and WARNING at threshold
- CIS distribution mean/stddev metric observation
- topics_produced contains signal_audit topic
- topics_consumed is empty
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_auditor_agent import (
    _COVERAGE_TFS,
    _LAG_P95_WARN_MS,
    SignalAuditorAgent,
)
from src.core.stream_keys import topic_signal_audit


@pytest.fixture()
def agent():
    """Create SignalAuditorAgent without __init__ (bypasses DB/Kafka setup)."""
    a = SignalAuditorAgent.__new__(SignalAuditorAgent)
    a.name = "signal_auditor_agent"
    a.logger = MagicMock()
    a._settings = MagicMock()
    a._settings.env_name = "dev"
    a._env_name = "dev"
    a._db_pool = AsyncMock()
    a._kafka_producer = AsyncMock()
    a._audits_run = MagicMock()
    a._coverage_gaps_published = MagicMock()
    a._audit_duration = MagicMock()
    a._audit_duration.__enter__ = MagicMock(return_value=None)
    a._audit_duration.__exit__ = MagicMock(return_value=False)
    a._audit_errors = MagicMock()
    a._signal_coverage_pct = MagicMock()
    a._signal_coverage_pct.labels.return_value = MagicMock()
    a._pipeline_lag_p50 = MagicMock()
    a._pipeline_lag_p50.labels.return_value = MagicMock()
    a._pipeline_lag_p95 = MagicMock()
    a._pipeline_lag_p95.labels.return_value = MagicMock()
    a._cis_mean = MagicMock()
    a._cis_mean.labels.return_value = MagicMock()
    a._cis_stddev = MagicMock()
    a._cis_stddev.labels.return_value = MagicMock()
    return a


def _make_instrument(symbol: str = "SPY", session_id: str = "nyse"):
    """Create a lightweight instrument mock with a mocked trading_session.

    TradingSession is a frozen dataclass, so session_window_for_date cannot be
    patched directly on an instance. We return a MagicMock that mimics the fields
    accessed by SignalAuditorAgent: instrument.symbol and
    instrument.trading_session.session_window_for_date.
    """
    instrument = MagicMock()
    instrument.symbol = symbol
    # trading_session is itself a MagicMock; callers configure
    # instrument.trading_session.session_window_for_date as needed.
    return instrument


def _make_conn_mock(coverage_count: int = 0, lag_row=None, cis_row=None):
    """Build asyncpg connection mock.

    coverage_count: returned by fetchval (coverage COUNT queries).
    lag_row: dict with keys p50, p95 returned by fetchrow for lag queries.
    cis_row: dict with keys cis_mean, cis_stddev returned by fetchrow for CIS queries.
    """
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=coverage_count)

    async def fetchrow_side(query, *args):
        if "percentile_cont" in query:
            return lag_row
        if "AVG(cis_score)" in query:
            return cis_row
        return None

    conn.fetchrow = AsyncMock(side_effect=fetchrow_side)
    return conn


def _set_db_pool(agent, mock_conn) -> None:
    """Wire the agent's db_pool so that `async with pool.acquire() as conn` yields mock_conn.

    asyncpg pool.acquire() returns a context manager (not a coroutine).
    Use MagicMock (not AsyncMock) for acquire so the return value is treated as a
    context manager, not a coroutine.
    """
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    agent._db_pool.acquire = MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_coverage_gap_when_zero_signals(agent):
    """_check_coverage returns one gap event per tf when count = 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    _set_db_pool(agent, conn)

    session_start = datetime(2026, 4, 5, 14, 30, tzinfo=UTC)
    session_end = datetime(2026, 4, 5, 21, 0, tzinfo=UTC)
    instrument.trading_session.session_window_for_date = MagicMock(
        return_value=(session_start, session_end)
    )

    gaps = await agent._check_coverage([instrument])

    assert len(gaps) == len(_COVERAGE_TFS)
    for gap in gaps:
        assert gap["symbol"] == "SPY"
        assert gap["signals_found"] == 0
        assert "session_date" in gap
        assert "ts" in gap
        assert "expected_session_start" in gap
        assert "expected_session_end" in gap

    # Gauge set to 0.0 for each tf
    assert agent._signal_coverage_pct.labels.call_count == len(_COVERAGE_TFS)
    for call in agent._signal_coverage_pct.labels.return_value.set.call_args_list:
        assert call.args[0] == 0.0


@pytest.mark.asyncio
async def test_no_gap_when_signals_present(agent):
    """_check_coverage returns no gap events when count > 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=42)
    _set_db_pool(agent, conn)

    instrument.trading_session.session_window_for_date = MagicMock(
        return_value=(
            datetime(2026, 4, 5, 14, 30, tzinfo=UTC),
            datetime(2026, 4, 5, 21, 0, tzinfo=UTC),
        )
    )

    gaps = await agent._check_coverage([instrument])

    assert gaps == []
    for call in agent._signal_coverage_pct.labels.return_value.set.call_args_list:
        assert call.args[0] == 1.0


@pytest.mark.asyncio
async def test_coverage_skips_non_trading_day(agent):
    """_check_coverage skips instruments where session_window returns (None, None)."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    _set_db_pool(agent, conn)

    instrument.trading_session.session_window_for_date = MagicMock(
        return_value=(None, None)
    )

    gaps = await agent._check_coverage([instrument])

    assert gaps == []
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_lag_warns_when_p95_exceeds_threshold(agent):
    """_check_pipeline_lag logs WARNING when P95 > _LAG_P95_WARN_MS."""
    instrument = _make_instrument()
    lag_row = {"p50": 120.0, "p95": 650.0}
    conn = _make_conn_mock(lag_row=lag_row)
    _set_db_pool(agent, conn)

    await agent._check_pipeline_lag([instrument])

    agent.logger.warning.assert_called()
    warn_call = agent.logger.warning.call_args
    assert warn_call.args[0] == "signal_auditor_agent.lag_threshold_exceeded"
    assert warn_call.kwargs["p95_ms"] == 650.0
    assert warn_call.kwargs["threshold_ms"] == _LAG_P95_WARN_MS


@pytest.mark.asyncio
async def test_pipeline_lag_no_warning_within_threshold(agent):
    """_check_pipeline_lag does not log WARNING when P95 <= _LAG_P95_WARN_MS."""
    instrument = _make_instrument()
    lag_row = {"p50": 80.0, "p95": 200.0}
    conn = _make_conn_mock(lag_row=lag_row)
    _set_db_pool(agent, conn)

    await agent._check_pipeline_lag([instrument])

    agent.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_cis_distribution_sets_gauges(agent):
    """_check_cis_distribution sets cis_mean and cis_stddev gauges per tf."""
    cis_row = {"cis_mean": 0.52, "cis_stddev": 0.18}
    conn = _make_conn_mock(cis_row=cis_row)
    _set_db_pool(agent, conn)

    await agent._check_cis_distribution()

    assert agent._cis_mean.labels.call_count == len(_COVERAGE_TFS)
    agent._cis_mean.labels.return_value.set.assert_called_with(0.52)
    agent._cis_stddev.labels.return_value.set.assert_called_with(0.18)
    assert agent._cis_stddev.labels.call_count == len(_COVERAGE_TFS)


def test_topics_produced(agent):
    """topics_produced returns the signal audit topic for the configured env."""
    assert topic_signal_audit(agent._env_name) in agent.topics_produced


def test_topics_consumed_is_empty(agent):
    """topics_consumed is empty — AuditorAgent pulls from DB, not Kafka."""
    assert agent.topics_consumed == []
