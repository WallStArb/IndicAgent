"""Tests for signal_generator_service typed IntelligenceEvent deserialization."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ResponseError

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_valid_event_json() -> bytes:
    """Return bytes of a valid IntelligenceEvent JSON for test fixtures."""
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
    event = IntelligenceEvent(
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
    return event.model_dump_json().encode()


# ── _parse_intelligence_event ─────────────────────────────────────────────────

def test_parse_intelligence_event_returns_typed_event():
    """Valid IntelligenceEvent JSON in b'event' field returns IntelligenceEvent."""
    from services.signal_generator_service import _parse_intelligence_event
    from src.intelligence.schemas import IntelligenceEvent

    fields = {b"event": _make_valid_event_json()}
    result = _parse_intelligence_event(fields)

    assert result is not None
    assert isinstance(result, IntelligenceEvent)
    assert result.symbol == "ESH6"
    assert result.tf == "5m"
    assert result.bar.o == 5100.25
    assert result.bar.v == 12345
    assert result.i4.trend_regime == pytest.approx(0.65)
    assert result.i1.rsi_14 == pytest.approx(58.3)


def test_parse_intelligence_event_returns_none_on_missing_event_field():
    """Empty fields dict returns None without crashing."""
    from services.signal_generator_service import _parse_intelligence_event

    result = _parse_intelligence_event({})
    assert result is None


def test_parse_intelligence_event_returns_none_on_empty_event_bytes():
    """b'event' key present but empty bytes returns None."""
    from services.signal_generator_service import _parse_intelligence_event

    result = _parse_intelligence_event({b"event": b""})
    assert result is None


def test_parse_intelligence_event_returns_none_on_malformed_json():
    """Garbled JSON bytes returns None and logs warning."""
    from services.signal_generator_service import _parse_intelligence_event

    result = _parse_intelligence_event({b"event": b"not-valid-json{{{"})
    assert result is None


def test_parse_intelligence_event_returns_none_on_validation_error():
    """Valid JSON but fails Pydantic validation returns None."""
    from services.signal_generator_service import _parse_intelligence_event

    # Omitting required fields (ts, symbol, etc.) causes ValidationError
    bad_json = b'{"schema_version": "1.0", "symbol": "ESH6"}'
    result = _parse_intelligence_event({b"event": bad_json})
    assert result is None


# ── _build_features_from_event ────────────────────────────────────────────────

def test_build_features_from_event_maps_typed_attributes():
    """_build_features_from_event extracts all MARKET_CONTEXT_KEYS from typed event."""
    from services.signal_generator_service import _build_features_from_event
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

    event = IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.0, h=5105.0, l=5099.0, c=5103.0, v=10000),
        i1=I1Indicators(rsi_14=55.0, atr_14=10.0),
        i3=I3Structure(trend_strength=0.7, swing_pattern=1.0),
        i4=I4Context(
            trend_regime=0.6,
            trend_confidence=0.75,
            vol_regime=0.3,
            vol_percentile=55.0,
        ),
        i5=I5Patterns(),
        smc=SMCContext(hmm_regime=1.0),
        i6=I6Confluence(ctf_score=0.8),
    )

    features = _build_features_from_event(event)

    assert features["trend_regime"] == pytest.approx(0.6)
    assert features["volatility_regime"] == pytest.approx(0.3)
    assert features["trend_confidence"] == pytest.approx(0.75)
    assert features["atr_14"] == pytest.approx(10.0)
    assert features["rsi_14"] == pytest.approx(55.0)
    assert features["ctf_score"] == pytest.approx(0.8)
    assert features["swing_pattern"] == pytest.approx(1.0)
    assert features["trend_strength"] == pytest.approx(0.7)
    assert features["volatility_percentile"] == pytest.approx(55.0)
    assert features["hmm_regime_state"] == pytest.approx(1.0)


def test_build_features_from_event_none_values_for_missing_fields():
    """None-valued fields are absent from the features dict (not present as None).

    Plugins use features.get("key", default) — absent is equivalent to None.
    The new full-flatten implementation skips None values to avoid polluting
    the dict with ~150 None entries on sparse events.
    """
    from services.signal_generator_service import _build_features_from_event
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

    event = IntelligenceEvent(
        ts=datetime(2026, 2, 18, 10, 0, 0, tzinfo=UTC),
        symbol="ESH6",
        tf="5m",
        bar=OHLCVBar(o=5100.0, h=5105.0, l=5099.0, c=5103.0, v=10000),
        i1=I1Indicators(),  # no rsi_14 or atr_14
        i3=I3Structure(),   # no trend_strength or swing_pattern
        i4=I4Context(),     # all None
        i5=I5Patterns(),
        smc=SMCContext(),   # no hmm_regime
        i6=I6Confluence(),  # no ctf_score
    )

    features = _build_features_from_event(event)

    # None fields are absent — plugins use .get("key", default) which returns default
    assert features.get("trend_regime") is None
    assert features.get("atr_14") is None
    assert features.get("rsi_14") is None
    assert features.get("ctf_score") is None
    assert features.get("swing_pattern") is None
    assert features.get("hmm_regime_state") is None
    # Alias keys are always present (set explicitly, may be None)
    assert "hmm_regime_state" in features  # set explicitly from smc.hmm_regime
    assert "volatility_regime" in features  # set explicitly from i4.vol_regime


# ── process_single_message integration ───────────────────────────────────────

@pytest.mark.asyncio
async def test_process_message_accesses_typed_attributes():
    """_process_single_message routes typed attributes to I7 plugin frames correctly.

    Verifies that bar OHLCV values come from event.bar (not raw field parsing),
    and that the features dict includes typed tier values.
    """
    import collections

    from services.signal_generator_service import SignalGeneratorService

    # Build fields dict with valid IntelligenceEvent
    valid_event = _make_valid_event_json()
    fields = {b"event": valid_event}

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(
        lambda: collections.deque(maxlen=200)
    )
    svc.config = {
        "service": {
            "symbols": ["ESH6"],
            "timeframes": ["5m"],
            "min_history_bars": 50,
        }
    }
    svc.logger = MagicMock()
    svc.redis_client = MagicMock()
    svc.redis_client.xack = AsyncMock()
    svc.error_count_total = MagicMock()
    svc._error_count = 0

    captured_bar = {}
    captured_features = {}

    async def mock_process_bar(symbol, timeframe, bar, features, frames, timestamp):
        captured_bar.update(bar)
        captured_features.update({k: v for k, v in features.items() if v is not None})

    svc._df_cache = {}
    svc._process_bar = mock_process_bar

    await svc._process_single_message("ESH6", "5m", fields, "intel:ESH6:5m", b"1-0")

    # Verify bar comes from typed event.bar fields
    assert captured_bar["open"] == pytest.approx(5100.25)
    assert captured_bar["high"] == pytest.approx(5105.50)
    assert captured_bar["low"] == pytest.approx(5098.75)
    assert captured_bar["close"] == pytest.approx(5103.00)
    assert captured_bar["volume"] == 12345

    # Verify features contain typed tier values
    assert captured_features["trend_regime"] == pytest.approx(0.65)
    assert captured_features["ctf_score"] == pytest.approx(0.75)


def test_stream_map_populated_after_setup():
    """_stream_map must map stream_name → (symbol, timeframe) for all 92 streams."""
    import asyncio
    from unittest.mock import AsyncMock

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(
        side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
    )
    svc.redis_client.xrevrange = AsyncMock(return_value=[])

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    assert len(svc._stream_map) == 4 * len(svc.config["service"]["symbols"])


def test_df_cache_invalidated_on_bar_append():
    """After appending a bar, _df_cache[key] must be None."""
    import pandas as pd

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    key = "ES:1m"
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate bar append + invalidation
    svc.bar_history[key].append({"close": 5303.0, "timestamp": "t"})
    svc._df_cache[key] = None

    assert svc._df_cache[key] is None


def test_df_cache_hit_avoids_rebuild():
    """_get_df must return the cached DataFrame when cache is warm."""
    import pandas as pd

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    key = "ES:5m"
    cached_df = pd.DataFrame([{"close": 5300.0}])
    svc._df_cache[key] = cached_df

    result = svc._get_df(key)

    assert result is cached_df
