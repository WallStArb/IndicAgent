"""Tests for feature_writer_service — consumer group batch writer to intelligence_features."""
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_valid_event():
    """Build a valid IntelligenceEvent for test fixtures."""
    from src.intelligence.schemas import (
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )
    return IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.25, h=5105.50, l=5098.75, c=5103.00, v=12345),
        i1=I1Indicators(rsi_14=58.3, atr_14=12.5),
        i3=I3Structure(
            nearest_support=5080.0,
            nearest_resistance=5120.0,
            trend_strength=0.65,
            swing_pattern=1.0,
        ),
        i4=I4Context(
            trend_regime=0.65,
            trend_confidence=0.8,
            vol_regime=0.5,
            vol_percentile=60.0,
        ),
        i5=I5Patterns(squeeze_active=0.0, rsi_div_bullish=False),
        smc=SMCContext(bos_detected=False, hmm_regime=1.0),
        i6=I6Confluence(ctf_score=0.75),
    )


def _make_valid_event_json() -> bytes:
    """Return bytes of a valid IntelligenceEvent JSON for stream message fields."""
    return _make_valid_event().model_dump_json().encode()


# ── _parse_intelligence_event ─────────────────────────────────────────────────

def test_parse_valid_event_returns_intelligence_event():
    """Valid IntelligenceEvent JSON in b'event' field returns IntelligenceEvent."""
    from services.feature_writer_service import _parse_intelligence_event
    from src.intelligence.schemas import IntelligenceEvent

    fields = {b"event": _make_valid_event_json()}
    result = _parse_intelligence_event(fields)

    assert result is not None
    assert isinstance(result, IntelligenceEvent)
    assert result.symbol == "ESH6"
    assert result.tf == "5m"
    assert result.bar.o == pytest.approx(5100.25)
    assert result.bar.v == 12345


def test_parse_missing_event_field_returns_none():
    """Empty fields dict (missing b'event' key) returns None without crashing."""
    from services.feature_writer_service import _parse_intelligence_event

    result = _parse_intelligence_event({})
    assert result is None


def test_parse_malformed_json_returns_none():
    """Garbled JSON bytes returns None (ack-and-skip, no crash)."""
    from services.feature_writer_service import _parse_intelligence_event

    result = _parse_intelligence_event({b"event": b"not-valid-json{{{"})
    assert result is None


# ── _event_to_insert_params ───────────────────────────────────────────────────

def test_event_to_insert_params_returns_13_tuple():
    """_event_to_insert_params returns a 13-element tuple."""
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    assert isinstance(params, tuple)
    assert len(params) == 13


def test_event_to_insert_params_first_element_is_datetime():
    """First element of insert params is a datetime (ts column)."""
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    assert isinstance(params[0], datetime)
    assert params[0].year == 2026


def test_event_to_insert_params_jsonb_columns_are_strings():
    """JSONB columns (elements 6..12) must be json.dumps() strings, not dicts.

    asyncpg does not auto-serialize dicts to JSONB — they must be strings.
    """
    from services.feature_writer_service import _event_to_insert_params

    event = _make_valid_event()
    params = _event_to_insert_params(event)

    # Elements at indices 6..12 are the 7 JSONB columns: bar, i1, i3, i4, i5, smc, i6
    for idx in range(6, 13):
        value = params[idx]
        assert isinstance(value, str), (
            f"params[{idx}] must be a JSON string, got {type(value).__name__}"
        )
        # Must be valid JSON
        parsed = json.loads(value)
        assert isinstance(parsed, dict), f"params[{idx}] must decode to a dict"


# ── FeatureWriterService._maybe_flush ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_maybe_flush_force_calls_execute_batch():
    """_maybe_flush(force=True) with 3 buffered events calls execute_batch with 3 params."""
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    svc._last_flush = 0.0  # far in the past

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params, params, params]

    await svc._maybe_flush(force=True)

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    # Second argument is the params list
    assert len(call_args[0][1]) == 3
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_time_based_calls_execute_batch():
    """_maybe_flush(force=False) with events older than FLUSH_INTERVAL_SECS calls execute_batch."""
    import time

    from services.feature_writer_service import FLUSH_INTERVAL_SECS, FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    # Set last_flush far enough in the past to trigger time-based flush
    svc._last_flush = time.monotonic() - (FLUSH_INTERVAL_SECS + 1.0)

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


@pytest.mark.asyncio
async def test_maybe_flush_recent_events_no_call():
    """_maybe_flush(force=False) with recent events does NOT call execute_batch."""
    import time

    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    # Just flushed — last_flush is current time
    svc._last_flush = time.monotonic()

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    svc.db_manager = mock_db

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params]

    await svc._maybe_flush(force=False)

    mock_db.execute_batch.assert_not_called()
    # Buffer should still have the event
    assert len(svc._buffer) == 1


# ── graceful shutdown ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graceful_shutdown_sets_flag_and_flushes():
    """_shutdown sets shutdown_requested=True and flushes buffer."""
    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService.__new__(FeatureWriterService)
    svc.logger = MagicMock()
    svc.shutdown_requested = False
    svc._last_flush = 0.0
    svc.running = True

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock()
    mock_db.close = AsyncMock()
    svc.db_manager = mock_db

    mock_redis = MagicMock()
    mock_redis.aclose = AsyncMock()
    svc.redis_client = mock_redis

    event = _make_valid_event()
    from services.feature_writer_service import _event_to_insert_params
    params = _event_to_insert_params(event)
    svc._buffer = [params, params]

    await svc._shutdown()

    assert svc.shutdown_requested is True
    # Buffer must be flushed on shutdown
    mock_db.execute_batch.assert_called_once()
    assert svc._buffer == []


def test_stream_map_populated_after_setup():
    """_stream_map must contain all 92 stream → (symbol, tf) entries after setup."""
    import asyncio
    from unittest.mock import AsyncMock

    from services.feature_writer_service import FeatureWriterService

    svc = FeatureWriterService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    tfs = svc.config["service"]["timeframes"]
    assert len(svc._stream_map) == len(symbols) * len(tfs)
