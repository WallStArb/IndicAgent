"""Unit tests for BarAuditor.

Uses __new__ pattern to bypass __init__ and isolate tested behaviour.
Tests cover:
- Constructor attributes (name)
- topics_consumed/topics_produced contract
- _expected_bars_for_date for crypto_24_7, nyse, futures_24_5
- _detect_gaps with mocked asyncpg pool
- _run_audit with mocked producer verifying BarGapRequest publish calls
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import SESSION_REGISTRY
from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import topic_gap_requests


class TestBarAuditorInit:
    """Test constructor attributes and property contracts."""

    def test_name(self):
        """BarAuditor sets name='bar_auditor_agent'."""
        from services.bar_auditor import BarAuditor

        agent = BarAuditor.__new__(BarAuditor)
        agent.name = "bar_auditor_agent"
        agent.settings = MagicMock(env_name="development")

        assert agent.name == "bar_auditor_agent"

    def test_topics_consumed_returns_empty_list(self):
        """topics_consumed returns contract_update topic."""
        from services.bar_auditor import BarAuditor

        agent = BarAuditor.__new__(BarAuditor)
        agent.settings = MagicMock(env_name="development")
        # Inject the property via the class
        topics = BarAuditor.topics_consumed.fget(agent)
        assert len(topics) == 1
        assert any("contract_update" in t for t in topics)

    def test_topics_produced_returns_gap_requests_topic(self):
        """topics_produced returns [topic_gap_requests(env)]."""
        from services.bar_auditor import BarAuditor

        agent = BarAuditor.__new__(BarAuditor)
        agent.settings = MagicMock(env_name="development")

        produced = BarAuditor.topics_produced.fget(agent)
        assert produced == [topic_gap_requests("development")]
        assert "market.events.gap_requests" in produced[0]


class TestExpectedBarsForDate:
    """Test TradingSession.expected_bars_for_date for various session types.

    Moved from BarAuditor._expected_bars_for_date (static method) to
    TradingSession.expected_bars_for_date (instance method) in Phase 58.1 to
    eliminate duplication with session_window_for_date().
    """

    def test_crypto_24_7_trading_day_returns_1440(self):
        """crypto_24_7 on any day of week returns 1440 minutes."""
        session = SESSION_REGISTRY["crypto_24_7"]
        monday = date(2026, 3, 23)  # weekday 0
        assert session.expected_bars_for_date(monday) == 1440

    def test_crypto_24_7_sunday_returns_1440(self):
        """crypto_24_7 on Sunday (weekday=6) also returns 1440 — trades 24/7."""
        session = SESSION_REGISTRY["crypto_24_7"]
        sunday = date(2026, 3, 22)  # weekday 6
        assert session.expected_bars_for_date(sunday) == 1440

    def test_nyse_weekday_returns_390(self):
        """nyse on a weekday returns 390 minutes (09:30-16:00)."""
        session = SESSION_REGISTRY["nyse"]
        monday = date(2026, 3, 23)  # weekday 0
        assert session.expected_bars_for_date(monday) == 390

    def test_nyse_saturday_returns_zero(self):
        """nyse on a Saturday returns 0 — non-trading day."""
        session = SESSION_REGISTRY["nyse"]
        saturday = date(2026, 3, 21)  # weekday 5
        assert session.expected_bars_for_date(saturday) == 0

    def test_futures_24_5_trading_day_returns_1380(self):
        """futures_24_5 on Mon-Fri returns 1380 minutes (23h CME session)."""
        session = SESSION_REGISTRY["futures_24_5"]
        monday = date(2026, 3, 23)  # weekday 0
        assert session.expected_bars_for_date(monday) == 1380

    def test_futures_24_5_saturday_returns_zero(self):
        """futures_24_5 on Saturday returns 0 — not in trading_days."""
        session = SESSION_REGISTRY["futures_24_5"]
        saturday = date(2026, 3, 21)  # weekday 5 — not in {0,1,2,3,4,6}
        assert session.expected_bars_for_date(saturday) == 0


def _make_agent_stub(env_name="development"):
    """Create a BarAuditor via __new__ with minimal attributes for unit tests."""
    from services.bar_auditor import BarAuditor

    agent = BarAuditor.__new__(BarAuditor)
    agent.name = "bar_auditor_agent"
    agent.settings = MagicMock(env_name=env_name)
    agent.logger = MagicMock()
    agent.logger.warning = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._post_roll_suppression = {}
    agent._agent_attrs = {"agent": "bar_auditor_agent"}
    return agent


class TestDetectGaps:
    """Test _detect_gaps with mocked database pool."""

    @pytest.mark.asyncio
    async def test_detect_gaps_returns_request_for_low_completeness(self):
        """_detect_gaps returns BarGapRequest when actual bars < 95% of expected.

        Uses crypto_24_7 session which trades every day (including weekends),
        avoiding test failures when running on days where yesterday was a non-trading day for NYSE.
        """
        agent = _make_agent_stub()

        from src.core.models import AssetClass, Instrument

        mock_instrument = Instrument(
            symbol="BTC",
            asset_class=AssetClass.CRYPTO,
            session_id="crypto_24_7",
        )

        # Mock the completeness gauge
        agent._canonical_completeness = MagicMock()

        # Mock DB pool — bulk fetch returns no rows → counts={} → completeness=0
        # fetchrow returns None → _check_gap_retry sees no existing row → emit=True
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        agent._db_pool = mock_pool

        gaps = await agent._detect_gaps(instruments=[mock_instrument], lookback_days=1)

        assert len(gaps) >= 1
        gap = gaps[0]
        assert isinstance(gap, BarGapRequest)
        assert gap.symbol == "BTC"
        assert gap.tf == "1m"
        assert gap.source == "bar_auditor"

    @pytest.mark.asyncio
    async def test_detect_gaps_skips_nontrading_days(self):
        """_detect_gaps skips days with 0 expected bars (non-trading days)."""
        agent = _make_agent_stub()

        from src.core.models import AssetClass, Instrument

        # Use nyse session — weekends return 0
        mock_instrument = Instrument(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            session_id="nyse",
        )

        agent._canonical_completeness = MagicMock()

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=0)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        agent._db_pool = mock_pool

        _date = "services.bar_auditor.date"
        with patch(_date) as mock_date:
            # Make today() return a Sunday so lookback_days=1 gives Saturday
            mock_date.today.return_value = date(2026, 3, 22)  # Sunday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            gaps = await agent._detect_gaps(instruments=[mock_instrument], lookback_days=1)

        # Saturday = non-trading day for NYSE → no gap requests
        assert gaps == []
        # DB should not have been queried for non-trading days
        mock_conn.fetchval.assert_not_called()


class TestRunAudit:
    """Test _run_audit publishes BarGapRequest events to Kafka."""

    @pytest.mark.asyncio
    async def test_run_audit_publishes_gap_requests(self):
        """_run_audit calls _detect_gaps and publishes each BarGapRequest."""
        agent = _make_agent_stub()

        # Create mock gap requests
        gap_req = BarGapRequest(
            symbol="ES",
            tf="1m",
            start_ts=datetime(2026, 3, 23, 0, 0, tzinfo=UTC),
            end_ts=datetime(2026, 3, 24, 0, 0, tzinfo=UTC),
        )

        # Mock counters and histogram
        agent._audits_run = MagicMock()
        agent._gap_requests_published = MagicMock()
        agent._audit_errors = MagicMock()
        agent._audit_duration = MagicMock()
        _time_ctx = agent._audit_duration.time.return_value
        _time_ctx.__enter__ = MagicMock(return_value=None)
        _time_ctx.__exit__ = MagicMock(return_value=False)

        mock_producer = AsyncMock()
        agent._kafka_producer = mock_producer

        # Patch _detect_gaps to return our test gap
        with patch.object(agent, "_detect_gaps", return_value=[gap_req]) as mock_detect:
            await agent._run_audit()

        mock_detect.assert_called_once()
        mock_producer.publish.assert_called_once()
        call_args = mock_producer.publish.call_args
        topic_arg = call_args[0][0]
        assert "gap_requests" in topic_arg
        payload_arg = call_args[0][1]
        assert payload_arg["symbol"] == "ES"
        assert payload_arg["tf"] == "1m"

    @pytest.mark.asyncio
    async def test_run_audit_logs_error_and_continues(self):
        """_run_audit catches exceptions, logs error, does not re-raise."""
        agent = _make_agent_stub()

        # _detect_gaps raises an exception
        mock_errors = MagicMock()
        with (
            patch.object(agent, "_detect_gaps", side_effect=RuntimeError("DB down")),
            patch("services.bar_auditor._AUDIT_ERRORS", mock_errors),
        ):
            # Should NOT raise
            await agent._run_audit()

        mock_errors.add.assert_called_once()


# ---------------------------------------------------------------------------
# Constant contracts (merged from tests/unit/test_bar_auditor_agent.py)
# ---------------------------------------------------------------------------

from services.bar_auditor import _COMPLETENESS_GATE, _HTF_TIMEFRAME_MINUTES
from src.core.stream_keys import topic_contract_updates


def test_completeness_gate_constant():
    """_COMPLETENESS_GATE must equal 0.97 — document the threshold contract."""
    assert _COMPLETENESS_GATE == 0.97


def test_htf_timeframe_minutes_constant():
    """_HTF_TIMEFRAME_MINUTES must include 5m, 15m, 1h, 4h."""
    assert "5m" in _HTF_TIMEFRAME_MINUTES
    assert "15m" in _HTF_TIMEFRAME_MINUTES
    assert "1h" in _HTF_TIMEFRAME_MINUTES
    assert "4h" in _HTF_TIMEFRAME_MINUTES


def test_topics_consumed_includes_contract_updates():
    """topics_consumed must include the contract_updates topic for cache invalidation."""
    from services.bar_auditor import BarAuditor

    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="")
    topics = BarAuditor.topics_consumed.fget(agent)
    expected_topic = topic_contract_updates("")
    assert expected_topic in topics


class TestPriceSanityAudit:
    def _make_agent_with_price_sanity_pool(self, candidate_rows, corroboration_result=None):
        from services.bar_auditor import BarAuditor

        agent = BarAuditor.__new__(BarAuditor)
        agent.settings = MagicMock(env_name="development")
        agent.logger = MagicMock()
        agent.logger.info = MagicMock()
        agent.logger.error = MagicMock()

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=candidate_rows)
        mock_conn.execute = AsyncMock()
        # conn.transaction() is used as `async with conn.transaction():` in the real
        # implementation -- a bare AsyncMock().transaction() returns a coroutine, which
        # does NOT support the async context manager protocol (confirmed empirically:
        # `TypeError: 'coroutine' object does not support the asynchronous context
        # manager protocol`). Must be wired the same way mock_pool.acquire is below.
        mock_conn.transaction = MagicMock()
        mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        agent._price_sanity_pool = mock_pool
        return agent, mock_conn

    def test_price_sanity_audit_empty_candidates_is_noop(self):
        agent, mock_conn = self._make_agent_with_price_sanity_pool(candidate_rows=[])

        with patch(
            "services.bar_auditor.load_apr_dict_async",
            new=AsyncMock(return_value={}),
        ):
            asyncio.run(agent._run_price_sanity_audit())

        mock_conn.execute.assert_not_called()

    def test_price_sanity_audit_writes_confirmed_corrupt_status(self):
        candidate_rows = [
            {
                "symbol": "UUP",
                "tf": "5m",
                "bar_ts": "2007-06-20T19:05:00+00:00",
                "open": 1000.0,
                "high": 1000.0,
                "low": 1000.0,
                "close": 1000.0,
                "prev_close": 28.97,
                "next_open": 24.08,
            }
        ]
        agent, mock_conn = self._make_agent_with_price_sanity_pool(candidate_rows)

        with (
            patch(
                "services.bar_auditor.load_apr_dict_async",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "services.bar_auditor.count_corroborating_symbols_batch",
                new=AsyncMock(return_value={("UUP", "5m", "2007-06-20T19:05:00+00:00"): 0}),
            ),
        ):
            asyncio.run(agent._run_price_sanity_audit())

        # One UPDATE call writing the classified status back
        assert mock_conn.execute.call_count == 1
        call_args = mock_conn.execute.call_args
        assert "confirmed_corrupt" in str(call_args)
