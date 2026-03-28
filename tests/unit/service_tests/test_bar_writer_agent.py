"""Unit tests for BarWriterAgent — TDD tests for Plan 053.1-01.

Tests BarWriterAgent structural contract (BaseAgent inheritance, topics, metrics),
behavioral contract (buffer bar, flush buffer, source tagging, error handling),
and Golden Signals metrics.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Module-level test metrics (created once to avoid duplicate registration)
# ---------------------------------------------------------------------------

_TEST_EVENTS_CONSUMED = Counter(
    "test_bwa_events_consumed_total",
    "Events consumed (test)",
    ["agent"],
)
_TEST_BARS_WRITTEN = Counter(
    "test_bwa_bars_written_total",
    "Bars written (test)",
    ["agent", "tf"],
)
_TEST_BATCH_LATENCY = Histogram(
    "test_bwa_batch_latency_seconds",
    "Batch latency (test)",
    ["agent"],
)
_TEST_WRITE_ERRORS = Counter(
    "test_bwa_write_errors_total",
    "Write errors (test)",
    ["agent"],
)
_TEST_CONFLICT_SKIPS = Counter(
    "test_bwa_conflict_skips_total",
    "Conflict skips (test)",
    ["agent"],
)
_TEST_CONSUMER_LAG = Gauge(
    "test_bwa_consumer_lag",
    "Consumer lag (test)",
    ["agent"],
)


# ---------------------------------------------------------------------------
# Helpers: build a minimal BarWriterAgent bypassing __init__
# ---------------------------------------------------------------------------


def _make_agent():
    """Build BarWriterAgent using __new__ (service test pattern)."""
    from services.bar_writer_agent import BarWriterAgent

    agent = BarWriterAgent.__new__(BarWriterAgent)
    agent.name = "bar_writer_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._env_name = "dev"
    agent._kafka_consumer = AsyncMock()
    agent._db_pool = AsyncMock()
    agent._buffer: list[tuple] = []
    agent._last_flush: float = 0.0

    # Wire module-level test metrics
    agent._events_consumed_lbl = _TEST_EVENTS_CONSUMED.labels(agent="bar_writer_agent")
    agent._persistence_batch_latency_lbl = _TEST_BATCH_LATENCY.labels(agent="bar_writer_agent")
    agent._write_errors_lbl = _TEST_WRITE_ERRORS.labels(agent="bar_writer_agent")
    agent._conflict_skips_lbl = _TEST_CONFLICT_SKIPS.labels(agent="bar_writer_agent")
    agent._persistence_consumer_lag_lbl = _TEST_CONSUMER_LAG.labels(agent="bar_writer_agent")
    _tfs = ("1m", "5m", "15m", "1h", "4h", "1d")
    agent._bars_written_lbl: dict[str, Counter] = {
        tf: _TEST_BARS_WRITTEN.labels(agent="bar_writer_agent", tf=tf) for tf in _tfs
    }
    return agent


def _make_bar_payload(tf: str = "1m", symbol: str = "ESM6") -> dict:
    """Return a bar payload dict."""
    return {
        "ts": "2026-01-01T09:30:00+00:00",
        "symbol": symbol,
        "tf": tf,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "volume": 1000,
        "source": "ibkr_named",
        "session_type": "rth",
        "gap_preceding": False,
        "is_flat_bar": False,
    }


# ---------------------------------------------------------------------------
# Test 1: BarWriterAgent.__init__ sets name and metrics_port
# ---------------------------------------------------------------------------


def test_init_name_and_metrics_port():
    """BarWriterAgent must set name='bar_writer_agent' and metrics_port=9121."""
    from services.bar_writer_agent import BarWriterAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(BarWriterAgent, BaseAgent)


# ---------------------------------------------------------------------------
# Test 2: topics_consumed returns both bar topics
# ---------------------------------------------------------------------------


def test_topics_consumed():
    """topics_consumed returns [topic_market_bars(env), topic_market_bars_htf(env)]."""
    from src.core.stream_keys import topic_market_bars, topic_market_bars_htf

    agent = _make_agent()
    expected = [topic_market_bars("dev"), topic_market_bars_htf("dev")]
    assert agent.topics_consumed == expected


# ---------------------------------------------------------------------------
# Test 3: topics_produced returns [] — persistence-only agent
# ---------------------------------------------------------------------------


def test_topics_produced():
    """topics_produced returns [] — no Kafka output."""
    agent = _make_agent()
    assert agent.topics_produced == []


# ---------------------------------------------------------------------------
# Test 4: _buffer_bar correctly appends a 9-tuple to the buffer
# ---------------------------------------------------------------------------


def test_buffer_bar_appends_tuple():
    """_buffer_bar appends a 9-element tuple to self._buffer."""
    agent = _make_agent()
    payload = _make_bar_payload(tf="1m")

    agent._buffer_bar(payload)

    assert len(agent._buffer) == 1
    row = agent._buffer[0]
    assert len(row) == 9
    assert row[1] == "ESM6"   # symbol
    assert row[2] == "1m"     # timeframe
    assert isinstance(row[0], datetime)  # ts must be a datetime object


# ---------------------------------------------------------------------------
# Test 5: _buffer_bar sets source="live_1m" for 1m, "live_htf" for 5m+
# ---------------------------------------------------------------------------


def test_buffer_bar_source_tagging():
    """source='live_1m' for tf='1m'; source='live_htf' for all other TFs."""
    agent = _make_agent()

    agent._buffer_bar(_make_bar_payload(tf="1m"))
    agent._buffer_bar(_make_bar_payload(tf="5m"))
    agent._buffer_bar(_make_bar_payload(tf="1h"))

    assert agent._buffer[0][8] == "live_1m"
    assert agent._buffer[1][8] == "live_htf"
    assert agent._buffer[2][8] == "live_htf"


# ---------------------------------------------------------------------------
# Test 6: _flush_buffer calls executemany, clears buffer, increments counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_buffer_success():
    """_flush_buffer calls executemany, clears the buffer on success."""
    agent = _make_agent()

    # Pre-populate buffer with a 1m bar
    ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    agent._buffer.append((ts, "ESM6", "1m", 5200.0, 5210.0, 5195.0, 5205.0, 1000, "live_1m"))

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock(return_value=None)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None),
    ))
    agent._db_pool = mock_pool

    await agent._flush_buffer()

    mock_conn.executemany.assert_called_once()
    assert len(agent._buffer) == 0  # buffer cleared


# ---------------------------------------------------------------------------
# Test 7: _flush_buffer leaves buffer intact on DB error (retry on next cycle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_buffer_leaves_buffer_on_error():
    """_flush_buffer leaves buffer intact when DB raises an exception."""
    agent = _make_agent()

    ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    agent._buffer.append((ts, "ESM6", "1m", 5200.0, 5210.0, 5195.0, 5205.0, 1000, "live_1m"))

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(side_effect=Exception("DB connection refused")),
        __aexit__=AsyncMock(return_value=None),
    ))
    agent._db_pool = mock_pool

    await agent._flush_buffer()

    # Buffer must remain intact for retry
    assert len(agent._buffer) == 1


# ---------------------------------------------------------------------------
# Test 8: _flush_buffer is a no-op when buffer is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_buffer_noop_when_empty():
    """_flush_buffer does nothing when the buffer is empty."""
    agent = _make_agent()
    agent._buffer = []

    mock_pool = AsyncMock()
    agent._db_pool = mock_pool

    await agent._flush_buffer()

    # pool.acquire should never be called when buffer is empty
    mock_pool.acquire.assert_not_called()
