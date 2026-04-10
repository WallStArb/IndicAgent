"""Unit tests for BarReplayAgent.

Uses __new__ pattern to bypass __init__ and isolate tested behaviour.
Tests cover:
- 1m routing: tf="1m" → publishes to topic_market_bars
- HTF routing: tf="5m" → publishes to topic_market_bars_htf
- Dedup: second request with same (symbol, tf, date) returns early, no DB call
- Empty DB: conn.fetch returns [] → 0 publish calls, no error counter increment
- topics_consumed / topics_produced contract
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.schemas.market_events import SignalReplayRequest
from src.core.stream_keys import topic_market_bars, topic_market_bars_htf, topic_signal_replay_requests


def _make_agent(env_name: str = "development"):
    """Create BarReplayAgent via __new__ with minimal attributes for unit tests."""
    from services.bar_replay_agent import BarReplayAgent

    agent = BarReplayAgent.__new__(BarReplayAgent)
    agent.name = "bar_replay_agent"
    agent._env_name = env_name
    agent._settings = MagicMock()
    agent._kafka_producer = AsyncMock()
    agent._db_pool = MagicMock()
    agent._replay_in_progress: set[str] = set()
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.warning = MagicMock()
    agent.logger.error = MagicMock()

    # Stub Prometheus metric children to avoid duplicate-registration errors
    agent._bar_replay_requests_total = MagicMock()
    agent._bar_replay_bars_published = MagicMock()
    agent._bar_replay_errors = MagicMock()
    agent._bar_replay_duration = MagicMock()
    _time_ctx = MagicMock()
    _time_ctx.__enter__ = MagicMock(return_value=None)
    _time_ctx.__exit__ = MagicMock(return_value=False)
    agent._bar_replay_duration.labels.return_value.time.return_value = _time_ctx

    return agent


def _make_replay_request(
    symbol: str = "ES",
    tf: str = "1m",
    session_start: datetime | None = None,
    session_end: datetime | None = None,
) -> SignalReplayRequest:
    if session_start is None:
        session_start = datetime(2026, 4, 9, 14, 30, tzinfo=UTC)
    if session_end is None:
        session_end = datetime(2026, 4, 9, 21, 0, tzinfo=UTC)
    return SignalReplayRequest(
        symbol=symbol,
        tf=tf,
        session_start=session_start,
        session_end=session_end,
    )


def _make_db_row(
    symbol: str = "ES",
    tf: str = "1m",
    ts: datetime | None = None,
    open_: float = 5100.0,
    high: float = 5105.0,
    low: float = 5098.0,
    close: float = 5102.0,
    volume: int = 1000,
):
    """Build a minimal asyncpg-style record dict for market_data_ohlcv."""
    if ts is None:
        ts = datetime(2026, 4, 9, 14, 31, tzinfo=UTC)
    row = MagicMock()
    row.__getitem__ = lambda self_, key: {
        "symbol": symbol,
        "timeframe": tf,
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }[key]
    return row


class TestTopicsContract:
    """topics_consumed and topics_produced."""

    def test_topics_consumed_includes_signal_replay_requests(self):
        """topics_consumed returns [topic_signal_replay_requests(env)]."""
        from services.bar_replay_agent import BarReplayAgent

        agent = BarReplayAgent.__new__(BarReplayAgent)
        agent._env_name = "development"

        consumed = BarReplayAgent.topics_consumed.fget(agent)
        assert topic_signal_replay_requests("development") in consumed

    def test_topics_produced_includes_market_bars(self):
        """topics_produced includes topic_market_bars(env)."""
        from services.bar_replay_agent import BarReplayAgent

        agent = BarReplayAgent.__new__(BarReplayAgent)
        agent._env_name = "development"

        produced = BarReplayAgent.topics_produced.fget(agent)
        assert topic_market_bars("development") in produced

    def test_topics_produced_includes_market_bars_htf(self):
        """topics_produced includes topic_market_bars_htf(env)."""
        from services.bar_replay_agent import BarReplayAgent

        agent = BarReplayAgent.__new__(BarReplayAgent)
        agent._env_name = "development"

        produced = BarReplayAgent.topics_produced.fget(agent)
        assert topic_market_bars_htf("development") in produced


class TestDoReplay1mRouting:
    """1m bars must publish to topic_market_bars."""

    @pytest.mark.asyncio
    async def test_1m_request_publishes_to_market_bars_topic(self):
        """_do_replay with tf='1m' → kafka_producer.publish called with market.bars topic."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        # Build mock DB conn via pool context manager
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="ES", tf="1m")])

        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        # Should have published once
        assert agent._kafka_producer.publish.call_count == 1
        call_topic = agent._kafka_producer.publish.call_args[0][0]
        assert "market.bars" in call_topic
        assert "htf" not in call_topic

    @pytest.mark.asyncio
    async def test_1m_request_publishes_correct_topic_value(self):
        """_do_replay with tf='1m' → topic is exactly topic_market_bars(env)."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="ES", tf="1m")])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        call_topic = agent._kafka_producer.publish.call_args[0][0]
        assert call_topic == topic_market_bars("development")


class TestDoReplayHtfRouting:
    """HTF bars must publish to topic_market_bars_htf."""

    @pytest.mark.asyncio
    async def test_5m_request_publishes_to_market_bars_htf_topic(self):
        """_do_replay with tf='5m' → kafka_producer.publish called with market.bars.htf topic."""
        agent = _make_agent()
        req = _make_replay_request(symbol="NQ", tf="5m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="NQ", tf="5m")])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        assert agent._kafka_producer.publish.call_count == 1
        call_topic = agent._kafka_producer.publish.call_args[0][0]
        assert call_topic == topic_market_bars_htf("development")

    @pytest.mark.asyncio
    async def test_1h_request_publishes_to_market_bars_htf_topic(self):
        """_do_replay with tf='1h' → kafka_producer.publish called with market.bars.htf topic."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1h")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="ES", tf="1h")])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        call_topic = agent._kafka_producer.publish.call_args[0][0]
        assert call_topic == topic_market_bars_htf("development")


class TestDedupGuard:
    """Duplicate (symbol, tf, date) requests must be skipped."""

    @pytest.mark.asyncio
    async def test_duplicate_request_skipped_no_db_call(self):
        """Second request with same (symbol, tf, date) returns early, no DB call."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        # Pre-populate the dedup set with this request's key
        dedup_key = f"{req.symbol}:{req.tf}:{req.session_start.date()}"
        agent._replay_in_progress.add(dedup_key)

        mock_conn = AsyncMock()
        agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)

        await agent._do_replay(req)

        # DB should not have been called
        mock_conn.fetch.assert_not_called()
        # Producer should not have been called
        agent._kafka_producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_request_adds_to_dedup_set(self):
        """_do_replay adds the dedup key to _replay_in_progress before fetching."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")
        expected_key = f"{req.symbol}:{req.tf}:{req.session_start.date()}"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        # After completion, dedup key should remain (caller manages cleanup)
        assert expected_key in agent._replay_in_progress


class TestEmptyDb:
    """When DB returns 0 rows, publish 0 bars and no error counter increment."""

    @pytest.mark.asyncio
    async def test_empty_db_publishes_no_bars(self):
        """When conn.fetch returns [], 0 kafka_producer.publish calls."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        agent._kafka_producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_db_logs_warning(self):
        """When DB returns 0 rows, a warning is logged."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        agent.logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_db_no_error_counter_increment(self):
        """0 rows from DB → _bar_replay_errors counter NOT incremented."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        agent._bar_replay_errors.labels.assert_not_called()


class TestBarPublishContent:
    """Published BarMessage payload must have source='replay' and correct routing key."""

    @pytest.mark.asyncio
    async def test_published_bar_has_replay_source(self):
        """BarMessage payload published to Kafka has source='replay'."""
        agent = _make_agent()
        req = _make_replay_request(symbol="ES", tf="1m")

        ts = datetime(2026, 4, 9, 14, 31, tzinfo=UTC)
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="ES", tf="1m", ts=ts)])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        payload = agent._kafka_producer.publish.call_args[0][1]
        assert payload["source"] == "replay"

    @pytest.mark.asyncio
    async def test_published_bar_has_correct_symbol_and_tf(self):
        """BarMessage payload has symbol and tf from the DB row."""
        agent = _make_agent()
        req = _make_replay_request(symbol="NQ", tf="5m")

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[_make_db_row(symbol="NQ", tf="5m")])
        mock_pool_ctx = MagicMock()
        mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
        agent._db_pool.acquire.return_value = mock_pool_ctx

        await agent._do_replay(req)

        payload = agent._kafka_producer.publish.call_args[0][1]
        assert payload["symbol"] == "NQ"
        assert payload["tf"] == "5m"
