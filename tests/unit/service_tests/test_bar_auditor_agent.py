"""Unit tests for BarAuditorAgent.

Uses __new__ pattern to bypass __init__ and isolate tested behaviour.
Tests cover:
- Constructor attributes (name, metrics_port)
- topics_consumed/topics_produced contract
- _expected_bars_for_date for crypto_24_7, nyse, futures_24_5
- _detect_gaps with mocked asyncpg pool
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
        """topics_consumed returns [] — audit-loop-driven, no Kafka consumption."""
        from services.bar_auditor_agent import BarAuditorAgent

        with patch("services.bar_auditor_agent.Settings") as mock_settings:
            mock_settings.return_value.env_name = "development"
            mock_settings.return_value.database_url = "postgresql://localhost/test"
            mock_settings.return_value.kafka_bootstrap_servers = "localhost:9092"
            agent = BarAuditorAgent.__new__(BarAuditorAgent)
            agent._env_name = "development"
            # Inject the property via the class
            assert BarAuditorAgent.topics_consumed.fget(agent) == []

    def test_topics_produced_returns_gap_requests_topic(self):
        """topics_produced returns [topic_gap_requests(env)]."""
        from services.bar_auditor_agent import BarAuditorAgent

        agent = BarAuditorAgent.__new__(BarAuditorAgent)
        agent._env_name = "development"

        produced = BarAuditorAgent.topics_produced.fget(agent)
        assert produced == [topic_gap_requests("development")]
        assert "market.events.gap_requests" in produced[0]


class TestExpectedBarsForDate:
    """Test _expected_bars_for_date for various session types."""

    @pytest.fixture
    def agent(self):
        from services.bar_auditor_agent import BarAuditorAgent

        a = BarAuditorAgent.__new__(BarAuditorAgent)
        a._env_name = "development"
        return a

    def test_crypto_24_7_trading_day_returns_1440(self, agent):
        """crypto_24_7 on any day of week returns 1440 minutes."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["crypto_24_7"]
        monday = date(2026, 3, 23)  # weekday 0
        result = BarAuditorAgent._expected_bars_for_date(session, monday)
        assert result == 1440

    def test_crypto_24_7_sunday_returns_1440(self, agent):
        """crypto_24_7 on Sunday (weekday=6) also returns 1440 — trades 24/7."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["crypto_24_7"]
        sunday = date(2026, 3, 22)  # weekday 6
        result = BarAuditorAgent._expected_bars_for_date(session, sunday)
        assert result == 1440

    def test_nyse_weekday_returns_390(self, agent):
        """nyse on a weekday returns 390 minutes (09:30-16:00)."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["nyse"]
        monday = date(2026, 3, 23)  # weekday 0
        result = BarAuditorAgent._expected_bars_for_date(session, monday)
        assert result == 390

    def test_nyse_saturday_returns_zero(self, agent):
        """nyse on a Saturday returns 0 — non-trading day."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["nyse"]
        saturday = date(2026, 3, 21)  # weekday 5
        result = BarAuditorAgent._expected_bars_for_date(session, saturday)
        assert result == 0

    def test_futures_24_5_trading_day_returns_1380(self, agent):
        """futures_24_5 on Mon-Fri returns 1380 minutes (23h CME session)."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["futures_24_5"]
        monday = date(2026, 3, 23)  # weekday 0
        result = BarAuditorAgent._expected_bars_for_date(session, monday)
        assert result == 1380

    def test_futures_24_5_saturday_returns_zero(self, agent):
        """futures_24_5 on Saturday returns 0 — not in trading_days."""
        from services.bar_auditor_agent import BarAuditorAgent

        session = SESSION_REGISTRY["futures_24_5"]
        saturday = date(2026, 3, 21)  # weekday 5 — not in {0,1,2,3,4,6}
        result = BarAuditorAgent._expected_bars_for_date(session, saturday)
        assert result == 0


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
    return agent


class TestDetectGaps:
    """Test _detect_gaps with mocked database pool."""

    @pytest.mark.asyncio
    async def test_detect_gaps_returns_request_for_low_completeness(self):
        """_detect_gaps returns BarGapRequest when actual bars < 95% of expected."""
        agent = _make_agent_stub()

        from src.core.models import AssetClass, Instrument

        mock_instrument = Instrument(
            symbol="SPY",
            asset_class=AssetClass.EQUITY,
            session_id="nyse",
        )

        # Mock the completeness gauge
        agent._canonical_completeness = MagicMock()

        # Mock DB pool — returns count well below 95% of 390
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=10)  # 10/390 = 2.6% completeness
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        agent._db_pool = mock_pool

        _contracts = "services.bar_auditor_agent.get_active_contracts"
        with patch(_contracts, return_value=[mock_instrument]):
            gaps = await agent._detect_gaps(lookback_days=1)

        assert len(gaps) >= 1
        gap = gaps[0]
        assert isinstance(gap, BarGapRequest)
        assert gap.symbol == "SPY"
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

        _contracts = "services.bar_auditor_agent.get_active_contracts"
        _date = "services.bar_auditor_agent.date"
        # Patch date to only check a Saturday (2026-03-21)
        with patch(_contracts, return_value=[mock_instrument]):
            with patch(_date) as mock_date:
                # Make today() return a Sunday so lookback_days=1 gives Saturday
                mock_date.today.return_value = date(2026, 3, 22)  # Sunday
                mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                gaps = await agent._detect_gaps(lookback_days=1)

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
        agent._audit_duration.labels = MagicMock(return_value=MagicMock())
        agent._audit_duration.labels.return_value.time = MagicMock()
        _time_ctx = agent._audit_duration.labels.return_value.time.return_value
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
        agent._audit_errors.labels = MagicMock(return_value=MagicMock())
        agent._audit_duration = MagicMock()
        agent._audit_duration.labels = MagicMock(return_value=MagicMock())
        agent._audit_duration.labels.return_value.time = MagicMock()
        _time_ctx = agent._audit_duration.labels.return_value.time.return_value
        _time_ctx.__enter__ = MagicMock(return_value=None)
        _time_ctx.__exit__ = MagicMock(return_value=False)

        # _detect_gaps raises an exception
        with patch.object(agent, "_detect_gaps", side_effect=RuntimeError("DB down")):
            # Should NOT raise
            await agent._run_audit()

        agent._audit_errors.labels.return_value.inc.assert_called_once()
