"""Tests for source-based bar filtering in IntelligenceProcessorService."""
from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service():
    with patch("services.intelligence_processor_service.start_metrics_server"):
        from services.intelligence_processor_service import IntelligenceProcessorService
        svc = IntelligenceProcessorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xack = AsyncMock()
    svc.db_manager = None
    return svc


def _make_fields(
    ts: datetime,
    source: str | None = None,
    open_: float = 5100.0,
    high: float = 5105.0,
    low: float = 5097.0,
    close: float = 5103.0,
    volume: int = 1234,
) -> dict:
    """Build a bytes-keyed field dict like xreadgroup returns."""
    fields = {
        b"timestamp": ts.isoformat().encode(),
        b"open": str(open_).encode(),
        b"high": str(high).encode(),
        b"low": str(low).encode(),
        b"close": str(close).encode(),
        b"volume": str(volume).encode(),
    }
    if source is not None:
        fields[b"source"] = source.encode()
    return fields


@pytest.mark.asyncio
async def test_authoritative_bar_skips_pipeline():
    """source='authoritative' must NOT trigger _calculate_intelligence."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="authoritative")
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_not_called()


@pytest.mark.asyncio
async def test_authoritative_bar_updates_history():
    """source='authoritative' bar must still be added to bar_history."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="authoritative", close=5103.0)
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    history = svc.bar_history["ESH6:1m"]
    assert len(history) == 1
    assert history[-1]["close"] == 5103.0


@pytest.mark.asyncio
async def test_authoritative_bar_deduplicates_matching_timestamp():
    """Authoritative bar with same timestamp as last history entry replaces it in-place."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    # Pre-populate history with the provisional tick_derived bar
    svc.bar_history["ESH6:1m"].append({
        "timestamp": ts, "open": 5100.0, "high": 5104.0,
        "low": 5098.0, "close": 5102.0, "volume": 200,
    })

    # Authoritative correction: same timestamp, authoritative OHLCV
    fields = _make_fields(ts, source="authoritative",
                          open_=5100.25, high=5106.0, low=5097.5, close=5103.75, volume=250)
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"2-0")

    history = svc.bar_history["ESH6:1m"]
    assert len(history) == 1, "Should replace, not append"
    assert history[-1]["close"] == 5103.75
    assert history[-1]["volume"] == 250


@pytest.mark.asyncio
async def test_tick_derived_source_runs_pipeline():
    """source='tick_derived' must call _calculate_intelligence normally."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source="tick_derived")
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_called_once()


@pytest.mark.asyncio
async def test_missing_source_field_runs_pipeline():
    """Bars with no source field (old daemon, backward compat) must run the pipeline."""
    svc = _make_service()
    svc._calculate_intelligence = AsyncMock(return_value={})

    ts = datetime(2026, 2, 18, 14, 5, 0, tzinfo=timezone.utc)
    fields = _make_fields(ts, source=None)  # no source field
    await svc._process_single_bar("ESH6", "1m", fields, "market:ESH6:1m", b"1-0")

    svc._calculate_intelligence.assert_called_once()
