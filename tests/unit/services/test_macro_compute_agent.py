"""Unit tests for MacroAnalyzer.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests _publish_macro_signal and _persist_to_db methods.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    """Build a minimal MacroAnalyzer bypassing __init__."""
    from services.macro_compute_agent import MacroAnalyzer

    agent = MacroAnalyzer.__new__(MacroAnalyzer)
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._settings.macro_window_bars = 10
    agent._window_bars = 10
    agent._kafka_bootstrap = "localhost:19092"
    agent._database_url = "postgresql://postgres@localhost/indicagent"
    agent._bar_windows = defaultdict(lambda: deque(maxlen=11))
    agent._consumer = None
    agent._producer = None
    agent._db_manager = None
    agent._bars_processed = MagicMock()
    agent._macro_published = MagicMock()
    return agent


# ---------------------------------------------------------------------------
# _publish_macro_signal tests
# ---------------------------------------------------------------------------


class TestPublishMacroSignal:
    """Tests for MacroAnalyzer._publish_macro_signal()."""

    @pytest.mark.asyncio
    async def test_publish_yield_curve_calls_producer(self):
        """_publish_macro_signal() calls producer.publish for yield curve result."""
        agent = _make_agent()
        mock_producer = AsyncMock()
        agent._producer = mock_producer

        macro_result = {
            "yield_curve_slope": 0.75,
            "yield_curve_regime": "steepening",
        }
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

        mock_producer.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_uses_correct_topic(self):
        """_publish_macro_signal() publishes to topic_macro_signals topic."""
        agent = _make_agent()
        mock_producer = AsyncMock()
        agent._producer = mock_producer

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

        call_kwargs = mock_producer.publish.call_args[1]
        assert "macro_signals" in call_kwargs["topic"]

    @pytest.mark.asyncio
    async def test_publish_payload_contains_macro_fields(self):
        """_publish_macro_signal() payload contains yield curve fields."""
        agent = _make_agent()
        mock_producer = AsyncMock()
        agent._producer = mock_producer

        macro_result = {
            "yield_curve_slope": 1.25,
            "yield_curve_regime": "steepening",
        }
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

        call_kwargs = mock_producer.publish.call_args[1]
        payload = call_kwargs["msg"]
        assert payload["yield_curve_slope"] == 1.25
        assert payload["yield_curve_regime"] == "steepening"
        assert payload["symbol"] == "ZT"
        assert payload["ts"] == "2026-04-27T12:00:00Z"

    @pytest.mark.asyncio
    async def test_publish_ftq_payload_contains_ftq_fields(self):
        """_publish_macro_signal() payload contains FTQ fields for FTQ results."""
        agent = _make_agent()
        mock_producer = AsyncMock()
        agent._producer = mock_producer

        macro_result = {
            "ftq_score": -0.5,
            "ftq_regime": "risk_off",
        }
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "FTQ", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

        call_kwargs = mock_producer.publish.call_args[1]
        payload = call_kwargs["msg"]
        assert payload["ftq_score"] == -0.5
        assert payload["ftq_regime"] == "risk_off"

    @pytest.mark.asyncio
    async def test_publish_no_producer_no_error(self):
        """_publish_macro_signal() returns silently when producer is None."""
        agent = _make_agent()
        agent._producer = None

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

    @pytest.mark.asyncio
    async def test_publish_uses_symbol_tf_message_key(self):
        """_publish_macro_signal() uses message_key(symbol, tf) as Kafka key."""
        agent = _make_agent()
        mock_producer = AsyncMock()
        agent._producer = mock_producer

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._publish_macro_signal(macro_result, bar)

        call_kwargs = mock_producer.publish.call_args[1]
        assert call_kwargs["key"] == "ZT:1m"


# ---------------------------------------------------------------------------
# _persist_to_db tests
# ---------------------------------------------------------------------------


class TestPersistToDb:
    """Tests for MacroAnalyzer._persist_to_db()."""

    def _make_mock_pool_conn(self):
        """Create mock asyncpg connection accessed via pool.acquire() context manager."""
        mock_conn = AsyncMock()
        mock_acquire = AsyncMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_acquire)
        return mock_pool, mock_conn

    @pytest.mark.asyncio
    async def test_persist_yield_curve_executes_insert(self):
        """_persist_to_db() executes INSERT for yield curve result."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {"yield_curve_slope": 0.75, "yield_curve_regime": "steepening"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_yield_curve_inserts_into_macro_features(self):
        """_persist_to_db() inserts into macro_features table for yield curve."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {"yield_curve_slope": 1.0, "yield_curve_regime": "steepening"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        call_args = mock_conn.execute.call_args[0]
        sql = call_args[0]
        assert "macro_features" in sql
        assert "yield_curve_slope" in sql

    @pytest.mark.asyncio
    async def test_persist_ftq_inserts_ftq_columns(self):
        """_persist_to_db() inserts FTQ columns for FTQ result."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {"ftq_score": -0.5, "ftq_regime": "risk_off"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "FTQ", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        sql = call_args[0]
        assert "macro_features" in sql
        assert "ftq_score" in sql

    @pytest.mark.asyncio
    async def test_persist_ts_string_parsed_to_datetime(self):
        """_persist_to_db() converts ISO-8601 ts string to datetime object for asyncpg."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        call_args = mock_conn.execute.call_args[0]
        ts_param = call_args[1]  # First positional parameter after SQL
        assert isinstance(ts_param, datetime)
        assert ts_param.tzinfo is not None  # Must be timezone-aware

    @pytest.mark.asyncio
    async def test_persist_no_db_manager_no_error(self):
        """_persist_to_db() returns silently when db_manager is None."""
        agent = _make_agent()
        agent._db_manager = None

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

    @pytest.mark.asyncio
    async def test_persist_uses_upsert_on_conflict(self):
        """_persist_to_db() uses ON CONFLICT DO UPDATE (upsert semantics)."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": "2026-04-27T12:00:00Z", "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        call_args = mock_conn.execute.call_args[0]
        sql = call_args[0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    @pytest.mark.asyncio
    async def test_persist_datetime_ts_used_directly(self):
        """_persist_to_db() uses datetime ts directly without re-parsing."""
        agent = _make_agent()
        mock_pool, mock_conn = self._make_mock_pool_conn()
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        ts = datetime(2026, 4, 27, 12, 0, 0, tzinfo=UTC)
        macro_result = {"yield_curve_slope": 0.5, "yield_curve_regime": "flat"}
        bar = {"ts": ts, "symbol": "ZT", "tf": "1m"}

        await agent._persist_to_db(macro_result, bar)

        call_args = mock_conn.execute.call_args[0]
        ts_param = call_args[1]
        assert isinstance(ts_param, datetime)
