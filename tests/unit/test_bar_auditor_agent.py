"""Unit tests for BarAuditorAgent — session-aligned gap detection.

Phase 58.1-03: Upgrades BarAuditorAgent to use session_window_for_date() for gap
detection windows and derive per-session completeness thresholds from max_achievable_pct().

Tests verify:
- Session-aligned UTC windows (not midnight-to-midnight)
- Derived threshold prevents false positives for CME overnight sessions
- Non-trading days are skipped
- Contract update subscription is registered
- HTF completeness metrics are observed without issuing gap requests
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.bar_auditor_agent import (
    _COMPLETENESS_GATE,
    _HTF_TIMEFRAME_MINUTES,
    BarAuditorAgent,
)
from src.core.models import AssetClass, Instrument
from src.core.stream_keys import topic_contract_updates


@pytest.fixture()
def agent():
    """Create BarAuditorAgent without calling __init__ (bypasses DB/Kafka setup)."""
    a = BarAuditorAgent.__new__(BarAuditorAgent)
    a.name = "bar_auditor_agent"
    a.logger = MagicMock()
    a.settings = MagicMock(env_name="")
    a._db_pool = AsyncMock()
    a._kafka_producer = AsyncMock()
    a._contract_consumer = None
    a._record_message_consumed = MagicMock()
    a._requested_today: set[tuple[str, str]] = set()
    a._requested_today_date = ""
    a._canonical_completeness = MagicMock()
    a._canonical_completeness.labels.return_value = MagicMock()
    a._audits_run = MagicMock()
    a._gap_requests_published = MagicMock()
    a._audit_duration = MagicMock()
    a._audit_errors = MagicMock()
    a._post_roll_suppression = {}
    return a


def _make_instrument(session_id: str, symbol: str = "ES") -> Instrument:
    """Create a minimal Instrument with the given session_id."""
    return Instrument(
        symbol=symbol,
        asset_class=AssetClass.FUTURES,
        session_id=session_id,
    )


def _make_conn_mock(
    fetchval_return: int = 0,
    htf_counts: dict[str, int] | None = None,
):
    """Build an asyncpg connection mock with configurable 1m and HTF responses.

    fetchval_return: value returned by fetchval (used for 1m COUNT query).
    htf_counts: dict of {timeframe: count} for the batched HTF fetch query.
        Returns rows as dicts with "timeframe" and "cnt" keys.
    """
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=fetchval_return)
    if htf_counts is not None:
        mock_conn.fetch = AsyncMock(
            return_value=[{"timeframe": tf, "cnt": cnt} for tf, cnt in htf_counts.items()]
        )
    else:
        mock_conn.fetch = AsyncMock(return_value=[])
    return mock_conn


def _set_db_pool(agent: BarAuditorAgent, mock_conn) -> None:
    """Wire the agent's db_pool so that `async with pool.acquire() as conn` yields mock_conn.

    asyncpg pool.acquire() returns an asyncpg.pool.PoolConnectionProxy which
    is an async context manager. When mocking, pool.acquire must be a MagicMock
    (not an AsyncMock) so that `async with pool.acquire()` treats the return
    value as the context manager, not a coroutine that needs to be awaited.
    """
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    agent._db_pool.acquire = MagicMock(return_value=ctx)


# ---------------------------------------------------------------------------
# Constant checks
# ---------------------------------------------------------------------------


def test_completeness_gate_constant():
    """_COMPLETENESS_GATE must equal 0.97 — document the threshold contract."""
    assert _COMPLETENESS_GATE == 0.97


def test_htf_timeframe_minutes_constant():
    """_HTF_TIMEFRAME_MINUTES must include 5m, 15m, 1h, 4h."""
    assert "5m" in _HTF_TIMEFRAME_MINUTES
    assert "15m" in _HTF_TIMEFRAME_MINUTES
    assert "1h" in _HTF_TIMEFRAME_MINUTES
    assert "4h" in _HTF_TIMEFRAME_MINUTES


# ---------------------------------------------------------------------------
# topics_consumed
# ---------------------------------------------------------------------------


def test_topics_consumed_includes_contract_updates(agent):
    """topics_consumed must include the contract_updates topic for cache invalidation."""
    expected_topic = topic_contract_updates("")
    assert expected_topic in agent.topics_consumed


# ---------------------------------------------------------------------------
# Session-aligned gap detection — NYSE (same-day session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_gaps_session_aligned_nyse(agent):
    """NYSE gap detection uses 13:30-20:00 UTC window (not midnight).

    March 23, 2026 is a Monday (weekday=0). NYSE opens 09:30 EDT = 13:30 UTC,
    closes 16:00 EDT = 20:00 UTC. expected = 390 bars. Mock returns 350 (below
    0.97 * 1.0 = 0.97 threshold), so exactly one BarGapRequest should be generated
    with start_ts=13:30 UTC, end_ts=20:00 UTC — NOT midnight UTC.
    """
    instrument = _make_instrument("nyse")

    # 350 for 1m (below threshold), HTF: all above threshold
    mock_conn = _make_conn_mock(
        fetchval_return=350,
        htf_counts={"5m": 78, "15m": 26, "1h": 6, "4h": 1},
    )
    _set_db_pool(agent, mock_conn)

    # Patch date.today() to return the day after target so days_back=1 hits target_date
    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)  # Tuesday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.symbol == "ES"
    assert gap.tf == "1m"

    # start_ts must be 13:30 UTC (NOT midnight UTC)
    assert gap.start_ts == datetime(
        2026, 3, 23, 13, 30, tzinfo=UTC
    ), f"Expected 13:30 UTC, got {gap.start_ts}"
    # end_ts must be 20:00 UTC (NOT next midnight)
    assert gap.end_ts == datetime(
        2026, 3, 23, 20, 0, tzinfo=UTC
    ), f"Expected 20:00 UTC, got {gap.end_ts}"


@pytest.mark.asyncio
async def test_detect_gaps_session_aligned_futures_overnight(agent):
    """CME futures gap detection uses overnight window spanning two calendar days.

    March 23, 2026 (Monday): session opens Sunday March 22 18:00 CST (UTC-6) = 00:00 UTC Monday.
    Closes Monday 17:00 CST = 23:00 UTC Monday. expected = 1380 bars.
    Mock returns 1300 (below threshold), so start_ts must be 00:00 UTC March 23 (not midnight
    of March 22).
    """
    instrument = _make_instrument("futures_24_5")

    # 1300 for 1m (below threshold), HTF counts
    mock_conn = _make_conn_mock(
        fetchval_return=1300,
        htf_counts={"5m": 260, "15m": 86, "1h": 21, "4h": 5},
    )
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert len(gaps) == 1
    gap = gaps[0]

    # Overnight session: start = previous day 18:00 CST = 00:00 UTC of target_date
    assert gap.start_ts == datetime(
        2026, 3, 23, 0, 0, tzinfo=UTC
    ), f"Expected 00:00 UTC March 23, got {gap.start_ts}"
    # End = 17:00 CST = 23:00 UTC of target_date
    assert gap.end_ts == datetime(
        2026, 3, 23, 23, 0, tzinfo=UTC
    ), f"Expected 23:00 UTC March 23, got {gap.end_ts}"


# ---------------------------------------------------------------------------
# Derived threshold — false positive elimination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_gaps_derived_threshold_no_false_positive(agent):
    """CME futures: 1350/1380 = 0.978 completeness > 0.97 threshold — NO gap request.

    Old hardcoded 0.95 threshold would have flagged this as a gap (0.978 > 0.95, so
    actually it would NOT with the old threshold either — but 0.97 is still higher).
    This test specifically verifies that for a session where completeness is above the
    derived threshold, no gap request is generated.
    """
    instrument = _make_instrument("futures_24_5")

    # 1350 for 1m = 1350/1380 = 0.978 > 0.97 threshold (no gap)
    mock_conn = _make_conn_mock(
        fetchval_return=1350,
        htf_counts={"5m": 270, "15m": 90, "1h": 22, "4h": 5},
    )
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    # 0.978 > 0.97 threshold — no gap request
    assert len(gaps) == 0, f"Expected no gap requests for 0.978 completeness, got {len(gaps)}"


@pytest.mark.asyncio
async def test_detect_gaps_below_derived_threshold_triggers_request(agent):
    """NYSE: completeness below derived threshold triggers gap request.

    NYSE max_achievable_pct() = 1.0. Threshold = 1.0 * 0.97 = 0.97.
    330/390 = 0.846 < 0.97 -> gap request issued.
    """
    instrument = _make_instrument("nyse")

    mock_conn = _make_conn_mock(
        fetchval_return=330,
        htf_counts={"5m": 78, "15m": 26, "1h": 6, "4h": 1},
    )
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert len(gaps) == 1


# ---------------------------------------------------------------------------
# Non-trading day handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_gaps_skips_non_trading_day(agent):
    """NYSE Saturday: session_window_for_date returns (None, None).

    No gap request generated and no DB query made for non-trading days.
    """
    instrument = _make_instrument("nyse")

    mock_conn = _make_conn_mock(fetchval_return=0)
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        # days_back=1 -> target_date = Saturday March 21
        mock_date.today.return_value = date(2026, 3, 22)  # Sunday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert len(gaps) == 0
    # No DB query should be made for non-trading days
    mock_conn.fetchval.assert_not_called()
    mock_conn.fetch.assert_not_called()


# ---------------------------------------------------------------------------
# HTF completeness observation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_htf_completeness_metric_emitted(agent):
    """HTF completeness metrics are set for 5m/15m/1h/4h tf labels.

    NYSE: expected 1m = 390. DB returns 390 for 1m, 78 for 5m (all above threshold).
    _canonical_completeness.labels() must be called with tf='5m'.
    """
    instrument = _make_instrument("nyse")

    # 1m=390 (above threshold), HTF: all above threshold
    mock_conn = _make_conn_mock(
        fetchval_return=390,
        htf_counts={"5m": 78, "15m": 26, "1h": 6, "4h": 1},
    )
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert len(gaps) == 0  # 390/390 = 1.0 > threshold for 1m

    # Verify tf='5m' label was set
    label_calls = agent._canonical_completeness.labels.call_args_list
    tf_labels = [call.kwargs.get("tf") or call.args[2] for call in label_calls]
    assert "5m" in tf_labels, f"Expected tf='5m' in label calls, got: {tf_labels}"


@pytest.mark.asyncio
async def test_htf_gap_logged_not_requested(agent):
    """HTF gaps below threshold log a warning but do NOT publish a BarGapRequest.

    NYSE: 1m=390 (above threshold). 5m=50 (50/78 = 0.64, below 0.97 threshold).
    Expect: logger.warning called with 'bar_auditor_agent.htf_gap_detected'.
    Expect: no BarGapRequest in returned gaps (only 1m gaps are requestable).
    """
    instrument = _make_instrument("nyse")

    # 1m=390 (passes), 5m=50 (below threshold), rest above
    mock_conn = _make_conn_mock(
        fetchval_return=390,
        htf_counts={"5m": 50, "15m": 26, "1h": 6, "4h": 1},
    )
    _set_db_pool(agent, mock_conn)

    with patch("services.bar_auditor_agent.date") as mock_date:
        mock_date.today.return_value = date(2026, 3, 24)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        gaps = await agent._detect_gaps([instrument], lookback_days=1)

    # No gap REQUESTS for HTF (gap fill is 1m-only)
    assert len(gaps) == 0, f"Expected 0 BarGapRequests for HTF gap, got {len(gaps)}"

    # But a warning MUST be logged for the HTF gap
    warning_calls = agent.logger.warning.call_args_list
    htf_warnings = [
        c for c in warning_calls if c.args and c.args[0] == "bar_auditor_agent.htf_gap_detected"
    ]
    assert (
        len(htf_warnings) >= 1
    ), f"Expected at least one 'htf_gap_detected' warning log, got: {warning_calls}"


# ---------------------------------------------------------------------------
# Contract update cache invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_contract_updates_invalidates_module_cache(agent):
    """Receiving a contract update calls invalidate_active_contracts_cache()."""
    import unittest.mock as mock

    mock_consumer = MagicMock()
    # getmany returns {TopicPartition: [messages]} — we just need non-empty values
    mock_consumer.getmany = AsyncMock(return_value={"tp0": [MagicMock()]})
    agent._contract_consumer = mock_consumer

    with mock.patch("services.bar_auditor_agent.invalidate_active_contracts_cache") as mock_inv:
        await agent._drain_contract_updates()
        mock_inv.assert_called_once()


@pytest.mark.asyncio
async def test_drain_contract_updates_noop_when_no_consumer(agent):
    """_drain_contract_updates is a no-op when _contract_consumer is None."""
    import unittest.mock as mock

    agent._contract_consumer = None

    with mock.patch("services.bar_auditor_agent.invalidate_active_contracts_cache") as mock_inv:
        await agent._drain_contract_updates()
        mock_inv.assert_not_called()
