"""Unit tests for BarWriter — TDD tests for Plan 053.1-01 + Plan 63-06.

Tests BarWriter structural contract (BaseWriter inheritance, topics, metrics),
behavioral contract (parse payload, flush batch, source tagging, error handling),
Golden Signals metrics, and contract cache invalidation.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a minimal BarWriter bypassing __init__
# ---------------------------------------------------------------------------


def _make_agent():
    """Build BarWriter using __new__ (service test pattern)."""
    from services.bar_writer_agent import BarWriter

    agent = BarWriter.__new__(BarWriter)
    agent.name = "bar_writer_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent._kafka_consumer = AsyncMock()
    agent._db_pool = AsyncMock()
    agent._buffer: list[tuple] = []
    agent._last_flush: float = 0.0
    agent.BATCH_SIZE = 50
    agent.FLUSH_INTERVAL_SECS = 5.0

    # OTel attrs dicts (mirrors __init__ pattern)
    agent._events_consumed_attrs = {"agent": "bar_writer_agent"}
    agent._batch_latency_attrs = {"agent": "bar_writer_agent"}
    agent._write_errors_attrs = {"agent": "bar_writer_agent"}
    agent._conflict_skips_attrs = {"agent": "bar_writer_agent"}
    _tfs = ("1m", "5m", "15m", "1h", "4h", "1d")
    agent._bars_written_attrs: dict[str, dict] = {
        tf: {"agent": "bar_writer_agent", "tf": tf} for tf in _tfs
    }
    # Contract cache (SoT: contract_metadata)
    agent._contract_cache: dict[str, str] = {
        "ESM6": "ES",
        "ESU6": "ES",
        "NQM6": "NQ",
        "NQU6": "NQ",
        "CLK6": "CL",
        "CLM6": "CL",
        "GCJ6": "GC",
    }
    agent._contract_cache_size_attrs = {"agent": "bar_writer_agent"}
    agent._contract_cache_reloads_attrs = {"agent": "bar_writer_agent"}
    agent._consumer_lag_attrs = {"agent": "bar_writer_agent"}
    agent._buffer_depth_gauge = MagicMock()
    agent._buffer_overflow_total = MagicMock()

    # Write-path observability metrics (Phase 69)
    agent._flush_latency = MagicMock()
    agent._commit_latency = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._commit_errors_total = MagicMock()
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
# Test 1: BarWriter inherits from BaseWriter
# ---------------------------------------------------------------------------


def test_init_name():
    """BarWriter must inherit from BaseWriter (and BaseDaemon)."""
    from services.bar_writer_agent import BarWriter
    from src.core.agent.base import BaseDaemon
    from src.core.agent.base_writer import BaseWriter

    assert issubclass(BarWriter, BaseWriter)
    assert issubclass(BarWriter, BaseDaemon)


# ---------------------------------------------------------------------------
# Test 2: topics_consumed returns all 3 subscribed topics
# ---------------------------------------------------------------------------


def test_topics_consumed():
    """topics_consumed returns [topic_market_bars, topic_market_bars_htf, topic_contract_updates]."""
    from src.core.stream_keys import (
        topic_contract_updates,
        topic_market_bars,
        topic_market_bars_htf,
    )

    agent = _make_agent()
    expected = [
        topic_market_bars("dev"),
        topic_market_bars_htf("dev"),
        topic_contract_updates("dev"),
    ]
    assert agent.topics_consumed == expected


# ---------------------------------------------------------------------------
# Test 3: topics_produced returns [] — persistence-only agent
# ---------------------------------------------------------------------------


def test_topics_produced():
    """topics_produced returns [] — no Kafka output."""
    agent = _make_agent()
    assert agent.topics_produced == []


# ---------------------------------------------------------------------------
# Test 4: _parse_payload correctly returns a list with a 10-tuple
# ---------------------------------------------------------------------------


def test_parse_payload_appends_tuple():
    """_parse_payload returns a list with a 10-element tuple."""
    agent = _make_agent()
    payload = _make_bar_payload(tf="1m")

    rows = agent._parse_payload(payload)

    assert rows is not None
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == 10
    assert row[1] == "ESM6"  # symbol
    assert row[3] == "1m"  # timeframe (index 3 after base added at index 2)
    assert isinstance(row[0], datetime)  # ts must be a datetime object


# ---------------------------------------------------------------------------
# Test 5: _parse_payload sets source="live_1m" for 1m, "live_htf" for 5m+
# ---------------------------------------------------------------------------


def test_parse_payload_source_tagging():
    """source='live_1m' for tf='1m'; source='live_htf' for all other TFs."""
    agent = _make_agent()

    rows_1m = agent._parse_payload(_make_bar_payload(tf="1m"))
    rows_5m = agent._parse_payload(_make_bar_payload(tf="5m"))
    rows_1h = agent._parse_payload(_make_bar_payload(tf="1h"))

    assert rows_1m[0][9] == "live_1m"
    assert rows_5m[0][9] == "live_htf"
    assert rows_1h[0][9] == "live_htf"


# ---------------------------------------------------------------------------
# Test 6: _flush_batch calls executemany and increments counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_batch_success():
    """_flush_batch calls executemany."""
    agent = _make_agent()

    ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    batch = [(ts, "ESM6", "ES", "1m", 5200.0, 5210.0, 5195.0, 5205.0, 1000, "live_1m")]

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock(return_value=None)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    agent._db_pool = mock_pool

    await agent._flush_batch(batch)

    mock_conn.executemany.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7: _do_flush leaves buffer intact on DB error (retry on next cycle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_batch_leaves_buffer_on_error():
    """_flush_batch raises on DB error; caller (maybe_flush) leaves buffer intact."""
    agent = _make_agent()

    ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    row = (ts, "ESM6", "ES", "1m", 5200.0, 5210.0, 5195.0, 5205.0, 1000, "live_1m")
    agent._buffer.append(row)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(side_effect=Exception("DB connection refused")),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    agent._db_pool = mock_pool

    with pytest.raises(Exception, match="DB connection refused"):
        await agent._flush_batch(list(agent._buffer))

    # Buffer untouched — _flush_batch does not mutate it; caller handles retry
    assert len(agent._buffer) == 1


# ---------------------------------------------------------------------------
# Test 8: _do_flush is a no-op when buffer is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_batch_noop_when_empty():
    """_do_flush does nothing when the buffer is empty."""
    agent = _make_agent()
    agent._buffer = []

    mock_pool = AsyncMock()
    agent._db_pool = mock_pool

    await agent._do_flush()

    # pool.acquire should never be called when buffer is empty
    mock_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Test 9: _parse_payload resolves futures contract code to base symbol
# ---------------------------------------------------------------------------


def test_parse_payload_resolves_futures_base():
    """_parse_payload resolves futures contract code to base symbol via _contract_cache."""
    agent = _make_agent()
    payload = _make_bar_payload(tf="1m", symbol="ESM6")

    rows = agent._parse_payload(payload)

    row = rows[0]
    assert row[1] == "ESM6"  # symbol unchanged
    assert row[2] == "ES"  # base resolved from contract_cache
    assert row[3] == "1m"  # timeframe at correct index


def test_parse_payload_fallback_for_non_futures():
    """_parse_payload falls back to symbol as base for non-futures (ETF, FX)."""
    agent = _make_agent()
    payload = _make_bar_payload(tf="1m", symbol="DIA")

    rows = agent._parse_payload(payload)

    row = rows[0]
    assert row[1] == "DIA"  # symbol
    assert row[2] == "DIA"  # base == symbol (fallback — DIA not in contract_metadata)


# ---------------------------------------------------------------------------
# Test 10: _handle_contract_update reloads cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_contract_update_updates_cache():
    """_handle_contract_update() adds new contract and removes old one from cache."""
    agent = _make_agent()

    # ESZ6 (December) is not in the fixture — clean test of add+remove
    payload = {
        "base_symbol": "ES",
        "old_contract": "ESM6",
        "new_contract": "ESZ6",
        "promoted_at": "2026-09-19T14:30:00Z",
    }
    assert "ESM6" in agent._contract_cache
    assert "ESZ6" not in agent._contract_cache

    await agent._handle_contract_update(payload)

    assert "ESZ6" in agent._contract_cache
    assert agent._contract_cache["ESZ6"] == "ES"
    assert "ESM6" not in agent._contract_cache


@pytest.mark.asyncio
async def test_handle_contract_update_survives_malformed_payload():
    """_handle_contract_update() logs error and does not raise on bad payload."""
    agent = _make_agent()

    # Should not raise
    await agent._handle_contract_update({"garbage": "data"})
    agent.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Test 11: _flush_batch increments correct TF counter (row[3], not row[2])
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_batch_increments_tf_counter():
    """_flush_batch calls BARS_WRITTEN.add(1, attrs) for the correct timeframe."""
    from unittest.mock import patch

    agent = _make_agent()

    ts = datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC)
    # 10-tuple: (ts, symbol, base, tf, open, high, low, close, volume, source)
    batch = [(ts, "ESM6", "ES", "1m", 5200.0, 5210.0, 5195.0, 5205.0, 1000, "live_1m")]

    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock(return_value=None)
    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    agent._db_pool = mock_pool

    with patch("services.bar_writer_agent._BARS_WRITTEN") as mock_bars:
        await agent._flush_batch(batch)

    # OTel counter: .add(1, {"agent": ..., "tf": "1m"}) must have been called
    mock_bars.add.assert_called_once_with(1, agent._bars_written_attrs["1m"])


# ---------------------------------------------------------------------------
# Phase-105 regression: _record_message_consumed() called in _run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_calls_record_message_consumed() -> None:
    """_run() must call _record_message_consumed() for each consumed bar message.

    Phase-105 HF-5 regression: _record_message_consumed() updates the stall clock
    and liveness gauge. Without it, _stall_watchdog() would fire false positives
    and kill the service even while it is processing bars.
    """
    from unittest.mock import patch

    agent = _make_agent()

    # Provide a bar payload that parse will succeed on
    payload = _make_bar_payload(tf="1m", symbol="ESM6")

    # Consumer yields one bar message then exhausts (generator stops naturally)
    async def one_bar():
        yield ("dev.market.bars", None, payload)

    mock_consumer = MagicMock()
    mock_consumer.messages = one_bar
    agent._kafka_consumer = mock_consumer

    # _stop_event must not be set (running = True derived from it)
    agent._stop_event = asyncio.Event()

    recorded_calls = []

    def spy_record():
        recorded_calls.append(1)

    agent._record_message_consumed = spy_record

    # Patch _buffer_rows and _maybe_route_to_dlq so no actual DB is needed
    with (
        patch.object(agent, "_buffer_rows"),
        patch.object(agent, "_maybe_route_to_dlq", new_callable=AsyncMock),
        patch.object(agent, "maybe_flush", new_callable=AsyncMock),
        patch("services.bar_writer_agent._EVENTS_CONSUMED"),
        patch("services.bar_writer_agent._CONSUMER_LAG"),
    ):
        await agent._run()

    assert len(recorded_calls) == 1, (
        "_record_message_consumed() must be called once per consumed bar message "
        "(required for stall detection liveness tracking)"
    )
