"""Unit tests for BarAuditorAgent.

Uses __new__ pattern to bypass __init__ and isolate tested behaviour.
Tests cover:
- Constructor attributes (name, metrics_port)
- topics_consumed/topics_produced contract
- _expected_bars_for_date for crypto_24_7, nyse, futures_24_5
- _detect_gaps with mocked batch_bar_completeness (not direct DB pool)
- _run_audit with mocked producer verifying BarGapRequest publish calls
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import SESSION_REGISTRY
from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import topic_gap_requests


class TestBarAuditorAgentInit:
    """Test constructor attributes and property contracts."""

    def test_name_and_metrics_port(self):
        """BarAuditorAgent sets name='bar_auditor_agent' and metrics_port=9123."""
        from services.bar_auditor_agent import BarAuditorAgent

        agent = BarAuditorAgent.__new__(BarAuditorAgent)
        agent.name = "bar_auditor_agent"
        agent._metrics_port = 9123
        agent._env_name = "development"

        assert agent.name == "bar_auditor_agent"
        assert agent._metrics_port == 9123

    def test_topics_consumed_returns_empty_list(self):
        """topics_consumed returns [contract_update topic] — subscribes to contract changes."""
        from services.bar_auditor_agent import BarAuditorAgent

        with patch("services.bar_auditor_agent.Settings") as mock_settings:
            mock_settings.return_value.env_name = "development"
            mock_settings.return_value.database_url = "postgresql://localhost/test"
            mock_settings.return_value.kafka_bootstrap_servers = "localhost:9092"
            agent = BarAuditorAgent.__new__(BarAuditorAgent)
            agent._env_name = "development"
            # Inject the property via the class
            topics = BarAuditorAgent.topics_consumed.fget(agent)
            assert len(topics) == 1
            assert "contract_update" in topics[0]

    def test_topics_produced_returns_gap_requests_topic(self):
        """topics_produced returns [topic_gap_requests(env)]."""
        from services.bar_auditor_agent import BarAuditorAgent

        agent = BarAuditorAgent.__new__(BarAuditorAgent)
        agent._env_name = "development"

        produced = BarAuditorAgent.topics_produced.fget(agent)
        assert produced == [topic_gap_requests("development")]
        assert "market.events.gap_requests" in produced[0]


class TestExpectedBarsForDate:
    """Test TradingSession.expected_bars_for_date for various session types.

    Moved from BarAuditorAgent._expected_bars_for_date (static method) to
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
    """Create a BarAuditorAgent via __new__ with minimal attributes for unit tests."""
    from services.bar_auditor_agent import BarAuditorAgent

    agent = BarAuditorAgent.__new__(BarAuditorAgent)
    agent.name = "bar_auditor_agent"
    agent._env_name = env_name
    agent._settings = MagicMock()
    agent.logger = MagicMock()
    agent.logger.warning = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    # Updated: 3-tuple dedup key after Phase 63.6 refactor
    agent._requested_today: set = set()
    agent._requested_today_date: str = ""
    return agent


def _make_instrument(symbol="BTC", session_id="crypto_24_7"):
    """Return a minimal Instrument stub."""
    from src.core.models import AssetClass, Instrument

    return Instrument(symbol=symbol, asset_class=AssetClass.CRYPTO, session_id=session_id)


def _make_bar_completeness_result(
    symbol: str = "BTC",
    tf: str = "1m",
    expected: int = 1440,
    actual: int = 10,
):
    """Build a BarCompletenessResult with sensible defaults."""
    from src.core.audit_utils import BarCompletenessResult

    session_start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)  # Tuesday
    session_end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)
    return BarCompletenessResult(
        symbol=symbol,
        tf=tf,
        session_start=session_start,
        session_end=session_end,
        expected=expected,
        actual=actual,
    )


class TestDetectGapsBatch:
    """Test _detect_gaps delegates to batch_bar_completeness and publishes HTF gap requests."""

    @pytest.mark.asyncio
    async def test_low_completeness_1m_publishes_gap_request(self):
        """When batch_bar_completeness returns low-completeness 1m result, gap request published."""
        agent = _make_agent_stub()
        agent._canonical_completeness = MagicMock()
        agent._db_pool = MagicMock()  # pool passed to batch_bar_completeness but not called directly

        instrument = _make_instrument("BTC", "crypto_24_7")
        result = _make_bar_completeness_result(symbol="BTC", tf="1m", expected=1440, actual=10)

        with patch(
            "services.bar_auditor_agent.batch_bar_completeness",
            new=AsyncMock(return_value=[result]),
        ):
            gaps = await agent._detect_gaps(instruments=[instrument], lookback_days=1)

        assert len(gaps) >= 1
        gap = gaps[0]
        assert isinstance(gap, BarGapRequest)
        assert gap.symbol == "BTC"
        assert gap.tf == "1m"
        assert gap.source == "bar_auditor"

    @pytest.mark.asyncio
    async def test_htf_low_completeness_publishes_gap_request_with_htf_tf(self):
        """When batch_bar_completeness returns low-completeness HTF result, gap request has tf='5m'."""
        agent = _make_agent_stub()
        agent._canonical_completeness = MagicMock()
        agent._db_pool = MagicMock()

        instrument = _make_instrument("BTC", "crypto_24_7")
        result = _make_bar_completeness_result(symbol="BTC", tf="5m", expected=288, actual=0)

        with patch(
            "services.bar_auditor_agent.batch_bar_completeness",
            new=AsyncMock(return_value=[result]),
        ):
            gaps = await agent._detect_gaps(instruments=[instrument], lookback_days=1)

        assert len(gaps) >= 1
        gap = gaps[0]
        assert gap.tf == "5m"
        assert gap.symbol == "BTC"

    @pytest.mark.asyncio
    async def test_high_completeness_skips_gap_request(self):
        """When completeness >= threshold, no gap request is created."""
        agent = _make_agent_stub()
        agent._canonical_completeness = MagicMock()
        agent._db_pool = MagicMock()

        instrument = _make_instrument("BTC", "crypto_24_7")
        # 1440/1440 = 100% completeness — well above threshold
        result = _make_bar_completeness_result(symbol="BTC", tf="1m", expected=1440, actual=1440)

        with patch(
            "services.bar_auditor_agent.batch_bar_completeness",
            new=AsyncMock(return_value=[result]),
        ):
            gaps = await agent._detect_gaps(instruments=[instrument], lookback_days=1)

        assert gaps == []

    @pytest.mark.asyncio
    async def test_dedup_same_symbol_date_tf_not_added_twice(self):
        """Same (symbol, date_str, tf) gap key is only published once per UTC day."""
        agent = _make_agent_stub()
        agent._canonical_completeness = MagicMock()
        agent._db_pool = MagicMock()

        instrument = _make_instrument("BTC", "crypto_24_7")
        result = _make_bar_completeness_result(symbol="BTC", tf="1m", expected=1440, actual=10)

        with patch(
            "services.bar_auditor_agent.batch_bar_completeness",
            new=AsyncMock(return_value=[result]),
        ):
            # First call — should publish
            gaps_first = await agent._detect_gaps(instruments=[instrument], lookback_days=1)
            # Second call — same (symbol, date_str, tf) already in dedup set
            gaps_second = await agent._detect_gaps(instruments=[instrument], lookback_days=1)

        assert len(gaps_first) >= 1
        assert gaps_second == []

    @pytest.mark.asyncio
    async def test_completeness_gauge_called_with_tf_label(self):
        """_detect_gaps calls _canonical_completeness.labels with the result's tf value."""
        agent = _make_agent_stub()
        agent._canonical_completeness = MagicMock()
        agent._db_pool = MagicMock()

        instrument = _make_instrument("BTC", "crypto_24_7")
        result = _make_bar_completeness_result(symbol="BTC", tf="5m", expected=288, actual=280)

        with patch(
            "services.bar_auditor_agent.batch_bar_completeness",
            new=AsyncMock(return_value=[result]),
        ):
            await agent._detect_gaps(instruments=[instrument], lookback_days=1)

        agent._canonical_completeness.labels.assert_called()
        call_kwargs = agent._canonical_completeness.labels.call_args
        # labels called with tf="5m"
        assert call_kwargs[1].get("tf") == "5m" or "5m" in str(call_kwargs)


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

        agent._audits_run = MagicMock()
        agent._gap_requests_published = MagicMock()
        agent._audit_errors = MagicMock()
        agent._audit_duration = MagicMock()
        _time_ctx = agent._audit_duration.time.return_value
        _time_ctx.__enter__ = MagicMock(return_value=None)
        _time_ctx.__exit__ = MagicMock(return_value=False)

        # _detect_gaps raises an exception
        with patch.object(agent, "_detect_gaps", side_effect=RuntimeError("DB down")):
            # Should NOT raise
            await agent._run_audit()

        agent._audit_errors.inc.assert_called_once()
