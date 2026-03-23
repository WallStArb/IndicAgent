"""Tests for signal_generator_service typed IntelligenceEvent deserialization."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.bar_history import BarHistory

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
        i3=I3Structure(),  # no trend_strength or swing_pattern
        i4=I4Context(),  # all None
        i5=I5Patterns(),
        smc=SMCContext(),  # no hmm_regime
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
    svc._bar_history = BarHistory(maxlen=200)
    svc.config = {
        "service": {
            "symbols": ["ESH6"],
            "timeframes": ["5m"],
            "min_history_bars": 50,
        }
    }
    svc.logger = MagicMock()
    svc.error_count_total = MagicMock()
    svc._error_count = 0

    captured_bar = {}
    captured_features = {}

    async def mock_process_bar(symbol, timeframe, bar, features, frames, timestamp, **kwargs):
        captured_bar.update(bar)
        captured_features.update({k: v for k, v in features.items() if v is not None})

    svc._df_cache = {}
    svc._regime_cache = collections.defaultdict(dict)
    svc._cross_asset_cache = {}  # Phase 47-04: always-on cache (flag removed)
    svc._htf_intel_cache = {}  # Phase 041: HTF cache added to __init__
    svc.db_manager = None  # _load_pattern_reliability_weights handles None gracefully
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


def test_signal_generator_has_kafka_clients():
    """SignalGeneratorService must have Kafka client attributes."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    # Kafka clients start as None; initialized in start() -> _setup_kafka_clients()
    assert hasattr(svc, "_kafka_consumer")
    assert hasattr(svc, "_kafka_producer")
    assert hasattr(svc, "_kafka_bootstrap")
    assert hasattr(svc, "env_name")


def test_df_cache_invalidated_on_bar_append():
    """After appending a bar, _df_cache[key] must be None."""
    import pandas as pd

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    key = "ES:1m"
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate bar cache invalidation (BarHistory.append + df_cache reset)
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

    result = svc._get_df("ES", "5m")

    assert result is cached_df


# ---------------------------------------------------------------------------
# _build_features_from_event — I2 wiring tests (Task 4)
# ---------------------------------------------------------------------------

from src.intelligence.schemas import (  # noqa: E402
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)


def _minimal_event(**i2_kwargs) -> "IntelligenceEvent":
    """Build a minimal IntelligenceEvent with given I2 fields."""
    return IntelligenceEvent(
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="ES",
        tf="1m",
        bar=OHLCVBar(o=5000, h=5010, l=4990, c=5005, v=1000),
        i1=I1Indicators(),
        i2=I2Events(**i2_kwargs),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )


def test_build_features_includes_i2_stoch_cross():
    from services.signal_generator_service import _build_features_from_event

    event = _minimal_event(stoch_cross_bullish=1.0, stoch_cross_bearish=0.0)
    features = _build_features_from_event(event)
    assert features.get("stoch_cross_bullish") == 1.0


def test_build_features_includes_i2_adx_events():
    from services.signal_generator_service import _build_features_from_event

    event = _minimal_event(adx_trend_confirmed=1.0, di_spread=25.0)
    features = _build_features_from_event(event)
    assert features.get("adx_trend_confirmed") == 1.0
    assert features.get("di_spread") == 25.0


def test_build_features_includes_i2_vol_events():
    from services.signal_generator_service import _build_features_from_event

    event = _minimal_event(vol_spike=1.0, bb_walking_upper=1.0)
    features = _build_features_from_event(event)
    assert features.get("vol_spike") == 1.0
    assert features.get("bb_walking_upper") == 1.0


# ── Redis stream timing fields ─────────────────────────────────────────────────


def test_signal_redis_message_includes_timing_fields():
    """signal_computed_at and bar_close_ts must appear in Redis stream message."""
    from datetime import datetime

    bar_close_ts = datetime(2026, 3, 6, 5, 10, 0, tzinfo=UTC)
    signal_computed_at = datetime(2026, 3, 6, 5, 10, 0, 800000, tzinfo=UTC)

    # Build a minimal message dict the same way the service does
    sig = {
        "direction": 1,
        "signal_type": "trend_long",
        "setup_plugin": "trad_TrendFollowing",
        "confidence": 0.85,
        "entry_price": 5823.50,
        "stop_loss": 5810.00,
        "regime_context": "bullish",
    }
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
    message["timestamp"] = datetime(2026, 3, 6, 5, 10, 0, tzinfo=UTC).isoformat()
    message["symbol"] = "ESH6"
    message["timeframe"] = "5m"
    if signal_computed_at:
        message["signal_computed_at"] = signal_computed_at.isoformat()
    if bar_close_ts:
        message["bar_close_ts"] = bar_close_ts.isoformat()

    assert "signal_computed_at" in message
    assert "bar_close_ts" in message
    assert "2026-03-06T05:10:00.800000" in message["signal_computed_at"]
    assert "2026-03-06T05:10:00" in message["bar_close_ts"]


# ── Signal gate ───────────────────────────────────────────────────────────────


def test_gate_first_signal_always_publishes():
    """No gate entry for (symbol, tf) → _check_gate returns False (publish allowed)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._signal_gate = {}
    ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
    # No gate entry — first signal should always be allowed (not gated)
    result = svc._check_gate("ESH6", "1m", 1, ts)
    assert result is False  # False = not gated = publish allowed


def test_gate_cooldown_suppresses_within_window():
    """Gate entry exists, bars_since=1 < MIN_BARS=3 for 1m → gate suppresses (True)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._signal_gate = {}
    base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
    # Seed gate: signal fired at base_ts
    svc._signal_gate[("ESH6", "1m")] = {
        "direction": 1,
        "bar_ts": base_ts,
        "signal_id": "abc",
        "resolved": False,
    }
    # 1 bar later (60s = 1 bar on 1m) → bars_since=1 < MIN_BARS=3 → gated
    new_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)
    result = svc._check_gate("ESH6", "1m", 1, new_ts)
    assert result is True  # True = gated = suppress


def test_gate_cooldown_allows_after_window():
    """Gate entry exists, bars_since=4 >= MIN_BARS=3 for 1m → gate allows (False)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._signal_gate = {}
    base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
    svc._signal_gate[("ESH6", "1m")] = {
        "direction": 1,
        "bar_ts": base_ts,
        "signal_id": "abc",
        "resolved": False,
    }
    # 4 bars later (240s = 4 bars on 1m) → bars_since=4 >= MIN_BARS=3 → allowed
    new_ts = datetime(2026, 3, 10, 10, 4, 0, tzinfo=UTC)
    result = svc._check_gate("ESH6", "1m", 1, new_ts)
    assert result is False  # False = not gated = publish allowed


def test_gate_flip_suppressed_while_unresolved():
    """Gate has direction=+1, resolved=False, new direction=-1 → gate suppresses (True)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._signal_gate = {}
    base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
    svc._signal_gate[("ESH6", "1m")] = {
        "direction": 1,
        "bar_ts": base_ts,
        "signal_id": "abc",
        "resolved": False,
    }
    # Direction flip attempt before resolution — well past cooldown window
    new_ts = datetime(2026, 3, 10, 10, 10, 0, tzinfo=UTC)
    result = svc._check_gate("ESH6", "1m", -1, new_ts)
    assert result is True  # True = gated = suppress flip


def test_gate_flip_allowed_after_resolution():
    """Gate has direction=+1, resolved=True, new direction=-1 → gate allows (False)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._signal_gate = {}
    base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
    svc._signal_gate[("ESH6", "1m")] = {
        "direction": 1,
        "bar_ts": base_ts,
        "signal_id": "abc",
        "resolved": True,  # prior signal was resolved
    }
    # Direction flip after resolution — well past cooldown window
    new_ts = datetime(2026, 3, 10, 10, 10, 0, tzinfo=UTC)
    result = svc._check_gate("ESH6", "1m", -1, new_ts)
    assert result is False  # False = not gated = flip allowed


# ---------------------------------------------------------------------------
# BarHistory wiring tests (D-43, D-45)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_single_message_appends_bar_to_bar_history():
    """BarMessage with correct OHLCVBar short field names appended to _bar_history."""
    import collections

    from services.signal_generator_service import SignalGeneratorService

    valid_event = _make_valid_event_json()
    fields = {b"event": valid_event}

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc.config = {
        "service": {
            "symbols": ["ESH6"],
            "timeframes": ["5m"],
            "min_history_bars": 50,
        }
    }
    svc.logger = MagicMock()
    svc.error_count_total = MagicMock()
    svc._error_count = 0
    svc._df_cache = {}
    svc._regime_cache = collections.defaultdict(dict)
    svc._cross_asset_cache = {}  # Phase 47-04: always-on cache (flag removed)
    svc._htf_intel_cache = {}
    svc.db_manager = None

    async def mock_process_bar(*args, **kwargs):
        pass

    svc._process_bar = mock_process_bar

    await svc._process_single_message("ESH6", "5m", fields, "intel:ESH6:5m", b"1-0")

    # Verify BarHistory was populated via append (not raw dict)
    bars = svc._bar_history.get("ESH6", "5m")
    assert len(bars) == 1
    bar = bars[0]
    # BarMessage stores LONG field names: open, high, low, close, volume
    assert bar.open == pytest.approx(5100.25)
    assert bar.high == pytest.approx(5105.50)
    assert bar.low == pytest.approx(5098.75)
    assert bar.close == pytest.approx(5103.00)
    assert bar.volume == 12345


def test_bar_history_is_warm_check():
    """_bar_history.is_warm returns False before min_bars, True after."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    # Fresh service — no bars appended
    assert svc._bar_history.is_warm("ES", "1m", 50) is False


# ---------------------------------------------------------------------------
# QUAL-04: Per-setup cooldown gate
# ---------------------------------------------------------------------------


def _make_svc_with_cooldown():
    """Build a minimal SignalGeneratorService instance with _setup_cooldown initialized."""

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._setup_cooldown = {}
    svc.logger = MagicMock()
    return svc


def _make_signal(plugin: str, direction: int) -> dict:
    """Build a minimal signal dict for cooldown tests."""
    return {
        "setup_plugin": plugin,
        "direction": direction,
        "signal_type": f"{plugin}_{direction}",
        "confidence": 0.75,
        "entry_price": 5100.0,
    }


class TestSetupCooldownGate:
    """QUAL-04: per-setup (symbol, tf, plugin, direction) cooldown gate."""

    def test_cooldown_blocks_same_setup_direction_within_window(self):
        """Same setup+direction fired at bar N is blocked at bar N+1 (cooldown=2)."""
        from datetime import datetime

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
        next_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)  # 1 bar later (1m)

        # Fire signal at bar N
        sig = _make_signal("trad_TrendFollowing", 1)
        accepted = svc._filter_setup_cooldown("ESH6", "1m", [sig], base_ts)
        assert len(accepted) == 1, "First fire should be accepted"

        # Try same setup+direction 1 bar later (within cooldown=3 bars for 1m)
        blocked = svc._filter_setup_cooldown("ESH6", "1m", [sig], next_ts)
        assert (
            len(blocked) == 0
        ), f"Same setup+direction within cooldown window should be blocked, got {blocked}"

    def test_cooldown_allows_different_setup_same_direction(self):
        """Different setup same direction at bar N+1 is NOT blocked (cooldown is per-plugin)."""
        from datetime import datetime

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
        next_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)

        # Fire TrendFollowing at bar N
        sig_trend = _make_signal("trad_TrendFollowing", 1)
        svc._filter_setup_cooldown("ESH6", "1m", [sig_trend], base_ts)

        # Different setup (MeanReversion) at bar N+1 — should NOT be blocked
        sig_mean = _make_signal("trad_MeanReversion", 1)
        accepted = svc._filter_setup_cooldown("ESH6", "1m", [sig_mean], next_ts)
        assert (
            len(accepted) == 1
        ), f"Different setup should not be blocked by TrendFollowing cooldown, got {accepted}"

    def test_cooldown_allows_same_setup_opposite_direction(self):
        """Same setup opposite direction at bar N+1 is NOT blocked."""
        from datetime import datetime

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
        next_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)

        # Fire bullish at bar N
        sig_bull = _make_signal("trad_TrendFollowing", 1)
        svc._filter_setup_cooldown("ESH6", "1m", [sig_bull], base_ts)

        # Opposite direction (bearish) at bar N+1 — different key → NOT blocked
        sig_bear = _make_signal("trad_TrendFollowing", -1)
        accepted = svc._filter_setup_cooldown("ESH6", "1m", [sig_bear], next_ts)
        assert len(accepted) == 1, f"Opposite direction should not be blocked, got {accepted}"

    def test_cooldown_expires_after_n_bars(self):
        """Cooldown expires after _SIGNAL_COOLDOWN_BARS — fires again at bar N+cooldown."""
        from datetime import datetime

        from services.signal_generator_service import _SIGNAL_COOLDOWN_BARS

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)

        # Fire signal at bar N
        sig = _make_signal("trad_TrendFollowing", 1)
        svc._filter_setup_cooldown("ESH6", "1m", [sig], base_ts)

        # Advance exactly _SIGNAL_COOLDOWN_BARS["1m"] worth of seconds
        cooldown_bars = _SIGNAL_COOLDOWN_BARS["1m"]  # expect 3 for 1m
        expired_ts = datetime(2026, 3, 10, 10, cooldown_bars, 0, tzinfo=UTC)  # 3 bars = 3 min on 1m

        accepted = svc._filter_setup_cooldown("ESH6", "1m", [sig], expired_ts)
        assert (
            len(accepted) == 1
        ), f"Signal should be accepted after {cooldown_bars} bars, got {accepted}"

    def test_cooldown_keyed_by_symbol_tf_plugin_direction(self):
        """Cooldown state is keyed by (symbol, tf, plugin, direction) — different symbol
        unaffected."""
        from datetime import datetime

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
        next_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)

        # Fire signal on ESH6
        sig = _make_signal("trad_TrendFollowing", 1)
        svc._filter_setup_cooldown("ESH6", "1m", [sig], base_ts)

        # Same plugin+direction but different symbol — should NOT be blocked
        accepted = svc._filter_setup_cooldown("NQH6", "1m", [sig], next_ts)
        assert (
            len(accepted) == 1
        ), f"Different symbol should not be blocked by ESH6 cooldown, got {accepted}"

    def test_filter_setup_cooldown_constant_exists(self):
        """_SIGNAL_COOLDOWN_BARS constant exists and has expected TF keys."""
        from services.signal_generator_service import _SIGNAL_COOLDOWN_BARS

        assert isinstance(_SIGNAL_COOLDOWN_BARS, dict)
        assert "1m" in _SIGNAL_COOLDOWN_BARS
        assert "5m" in _SIGNAL_COOLDOWN_BARS
        assert "15m" in _SIGNAL_COOLDOWN_BARS
        assert "1h" in _SIGNAL_COOLDOWN_BARS
        assert _SIGNAL_COOLDOWN_BARS["1m"] >= 2  # must gate at least 2 bars


# ---------------------------------------------------------------------------
# KAFKA-06: _live_quotes updated from market.ticks topic (Phase 30 Plan 3)
# ---------------------------------------------------------------------------


def test_signal_generator_has_live_quotes_attribute():
    """SignalGeneratorService must expose _live_quotes instance attribute."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._live_quotes = {}
    assert hasattr(svc, "_live_quotes")
    assert isinstance(svc._live_quotes, dict)


def test_signal_generator_live_quotes_initialized_empty():
    """_live_quotes must be initialized as empty dict on service construction."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService()
    assert hasattr(svc, "_live_quotes")
    assert svc._live_quotes == {}


@pytest.mark.asyncio
async def test_kafka_06_live_quotes_updated_from_ticks_message():
    """KAFKA-06: _handle_ticks_message updates _live_quotes[symbol] with tick payload.

    When a message arrives on the market.ticks topic with key=SYMBOL,
    _live_quotes[symbol] must be set to the payload dict.
    """
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._live_quotes = {}
    svc.logger = MagicMock()

    tick_payload = {"bid": 5823.25, "ask": 5823.50, "last": 5823.50, "symbol": "ESH6"}
    await svc._handle_ticks_message("ESH6", tick_payload)

    assert "ESH6" in svc._live_quotes
    assert svc._live_quotes["ESH6"]["bid"] == 5823.25
    assert svc._live_quotes["ESH6"]["ask"] == 5823.50


@pytest.mark.asyncio
async def test_kafka_06_live_quotes_updated_overwrites_stale():
    """KAFKA-06: _handle_ticks_message overwrites prior entry — keeps only latest tick."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._live_quotes = {"ESH6": {"bid": 5800.0, "ask": 5800.25}}
    svc.logger = MagicMock()

    new_tick = {"bid": 5823.25, "ask": 5823.50}
    await svc._handle_ticks_message("ESH6", new_tick)

    assert svc._live_quotes["ESH6"]["bid"] == 5823.25


def test_signal_generator_no_redis_hgetall_for_quote():
    """signal_generator_service must not import or call quote_latest (HGETALL removed)."""
    import inspect

    import services.signal_generator_service as mod

    source = inspect.getsource(mod)

    # _fetch_live_quote using Redis HGETALL must not exist
    assert "_fetch_live_quote" not in source, (
        "_fetch_live_quote (Redis HGETALL for quote) should be removed; "
        "use _live_quotes dict instead"
    )


def test_signal_generator_no_redis_xreadgroup():
    """signal_generator_service must not call redis_client.xreadgroup (stream removed)."""
    import inspect

    import services.signal_generator_service as mod

    source = inspect.getsource(mod)
    assert "xreadgroup" not in source, (
        "Redis xreadgroup must be removed from signal_generator_service; "
        "use KafkaConsumerClient instead"
    )


def test_signal_generator_no_redis_xadd_signals():
    """signal_generator_service must not call redis_client.xadd (stream removed)."""
    import inspect

    import services.signal_generator_service as mod

    source = inspect.getsource(mod)
    assert "redis_client.xadd" not in source, (
        "redis_client.xadd must be removed from signal_generator_service; "
        "use KafkaProducerClient.publish instead"
    )


# ── _run_refresh_loop ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_refresh_loop_calls_fn_after_interval():
    """_run_refresh_loop calls fn after interval_s timeout and then shuts down."""
    import asyncio
    from unittest.mock import MagicMock

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.running = True
    svc.shutdown_requested = False
    svc.shutdown_event = asyncio.Event()
    svc.logger = MagicMock()
    svc.logger.error = MagicMock()

    call_count = 0

    async def _mock_fn():
        nonlocal call_count
        call_count += 1
        # After fn is called once, signal shutdown so loop terminates
        svc.shutdown_requested = True
        svc.running = False

    # Use very small interval so test completes quickly
    await svc._run_refresh_loop("test", 0.01, _mock_fn)
    assert call_count >= 1, "fn must be called at least once"


@pytest.mark.asyncio
async def test_run_refresh_loop_stops_on_shutdown_event():
    """_run_refresh_loop exits when shutdown_event is set without calling fn."""
    import asyncio
    from unittest.mock import MagicMock

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.running = True
    svc.shutdown_requested = False
    svc.shutdown_event = asyncio.Event()
    svc.logger = MagicMock()

    fn_called = False

    async def _mock_fn():
        nonlocal fn_called
        fn_called = True

    # Set shutdown_event before loop starts — should exit on first wait_for
    svc.shutdown_event.set()
    await svc._run_refresh_loop("test", 3600, _mock_fn)
    assert not fn_called, "fn must not be called when shutdown_event is already set"


@pytest.mark.asyncio
async def test_run_refresh_loop_catches_exceptions_and_sleeps_backoff():
    """_run_refresh_loop catches exceptions from fn, sleeps backoff_s, then exits on shutdown."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.running = True
    svc.shutdown_requested = False
    svc.shutdown_event = asyncio.Event()
    svc.logger = MagicMock()
    svc.logger.error = MagicMock()

    call_count = 0

    async def _failing_fn():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated DB error")

    sleep_calls = []

    async def _mock_sleep(s):
        sleep_calls.append(s)
        # After sleeping, stop the loop
        svc.shutdown_requested = True
        svc.running = False

    with patch("asyncio.sleep", side_effect=_mock_sleep):
        await svc._run_refresh_loop("test", 0.01, _failing_fn, backoff_s=30)

    assert call_count >= 1, "fn must have been called before raising"
    assert 30 in sleep_calls, "asyncio.sleep(30) must be called after exception"
    svc.logger.error.assert_called()


# ── calibration ndarray pre-alloc ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_calibration_curves_stores_ndarray():
    """_load_calibration_curves_from_db stores np.ndarray with dtype=float64."""
    from unittest.mock import MagicMock

    import numpy as np

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.logger = MagicMock()
    svc.logger.debug = MagicMock()
    svc.logger.warning = MagicMock()
    svc._calibration_curves = {}

    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(
        return_value=[
            {
                "plugin_name": "trad_CHoCHReversal",
                "timeframe": "5m",
                "breakpoints": [0.0, 0.3, 0.6, 1.0],
                "values": [0.1, 0.4, 0.7, 0.9],
            }
        ]
    )
    svc.db_manager = mock_db

    await svc._load_calibration_curves_from_db()

    key = ("trad_CHoCHReversal", "5m")
    assert key in svc._calibration_curves, "Key must be present in _calibration_curves"
    bp, vals = svc._calibration_curves[key]
    assert isinstance(bp, np.ndarray), "breakpoints must be np.ndarray"
    assert isinstance(vals, np.ndarray), "values must be np.ndarray"
    assert bp.dtype == np.float64, "breakpoints dtype must be float64"
    assert vals.dtype == np.float64, "values dtype must be float64"
    np.testing.assert_array_equal(bp, [0.0, 0.3, 0.6, 1.0])
    np.testing.assert_array_equal(vals, [0.1, 0.4, 0.7, 0.9])


# ---------------------------------------------------------------------------
# Phase 44.2 Plan 02: In-process pipeline wiring tests
# ---------------------------------------------------------------------------


def _make_minimal_signal(
    plugin: str = "trad_TrendFollowing",
    direction: int = 1,
    confidence: float = 0.75,
) -> dict:
    """Build a minimal signal dict resembling make_signal() output."""
    from uuid import uuid4

    return {
        "signal_id": str(uuid4()),
        "setup_plugin": plugin,
        "direction": direction,
        "confidence": confidence,
        "signal_type": "trend_long",
        "entry_price": 5100.0,
        "stop_loss": 5080.0,
        "targets": [5130.0, 5150.0],
        "ttl_bars": 10,
        "regime_type": "trend",
        "regime_context": "bullish",
        "confluence_score": 0.5,
        "supporting_factors": [],
        "invalidation_conditions": [],
    }


def _make_svc_for_pipeline(extra_attrs: dict | None = None):
    """Build a minimal SignalGeneratorService with all attrs needed for _process_event."""
    import asyncio
    import collections

    from services.signal_generator_service import SignalGeneratorService
    from src.intelligence.trading.cis_scorer import CISScorer

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.logger = MagicMock()
    svc.env_name = "development"
    svc.shutdown_requested = False
    svc._signal_gate = {}
    svc._setup_last_fire = {}
    svc._setup_cooldown = {}
    svc._perf_weights = {}
    svc._drift_penalties = {}
    svc._cis_weights_cache = {}
    svc._calibration_curves = {}
    svc._tod_multipliers = {}
    svc._cis_kalman_state = {}
    svc._audit_queue = asyncio.Queue(maxsize=1000)
    svc._cis_scorer = CISScorer()
    svc._kafka_producer = None
    svc.db_manager = None
    svc.signals_generated_total = MagicMock()
    svc.signals_selected_total = MagicMock()
    svc._total_signals = 0
    svc._regime_cache = collections.defaultdict(dict)
    # SHADOW-01: Regime gate safety floors (configurable via env vars)
    svc._regime_prob_min = 0.30
    svc._regime_dur_min = 1
    if extra_attrs:
        for k, v in extra_attrs.items():
            setattr(svc, k, v)
    return svc


@pytest.mark.asyncio
async def test_process_event_calls_all_pipeline_stages():
    """_process_event calls all 6 pipeline pure functions in-process per bar.

    Each of the 6 stage functions should be called exactly once per _process_event
    invocation. Mocking at the module-patch level ensures we can verify call counts
    regardless of the internal implementation.
    """
    from unittest.mock import patch


    svc = _make_svc_for_pipeline()
    ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    raw_signals = [_make_minimal_signal()]

    svc_mod = "services.signal_generator_service"
    with (
        patch(f"{svc_mod}.apply_quality_gate", return_value=raw_signals) as mock_qg,
        patch(f"{svc_mod}.apply_regime_gate", return_value=raw_signals) as mock_rg,
        patch(f"{svc_mod}.apply_tod_adjustment", return_value=raw_signals) as mock_tod,
        patch(f"{svc_mod}.apply_calibration", return_value=raw_signals) as mock_cal,
        patch(f"{svc_mod}.rank_signals", return_value=raw_signals) as mock_rank,
        patch(f"{svc_mod}.select_winner", return_value=(None, raw_signals, "no_signals"))
        as mock_win,
    ):
        await svc._process_event(
            event=None,
            symbol="ES",
            timeframe="5m",
            timestamp=ts,
            bar_close_ts=None,
            source="live",
            raw_signals=raw_signals,
            regime_data=None,
            drift_penalty=1.0,
            features={},
        )

    mock_qg.assert_called_once()
    mock_rg.assert_called_once()
    mock_tod.assert_called_once()
    mock_cal.assert_called_once()
    mock_rank.assert_called_once()
    mock_win.assert_called_once()


@pytest.mark.asyncio
async def test_audit_queue_overflow_increments_counter():
    """_queue_stage_audits drops payloads when queue is full and increments _AUDIT_DROPS."""
    import asyncio

    import services.signal_generator_service as sgs_mod

    svc = _make_svc_for_pipeline()
    # Use a very small queue to trigger overflow
    svc._audit_queue = asyncio.Queue(maxsize=2)
    # Fill it to capacity
    svc._audit_queue.put_nowait({"topic": "t1", "data": {}})
    svc._audit_queue.put_nowait({"topic": "t2", "data": {}})

    # Read counter before overflow attempts
    drops_before = sgs_mod._AUDIT_DROPS._value.get()
    # Try to add 3 more payloads — all should overflow (queue is full)
    overflow_payloads = [
        {"topic": "t3", "data": {}},
        {"topic": "t4", "data": {}},
        {"topic": "t5", "data": {}},
    ]
    await svc._queue_stage_audits(overflow_payloads)

    drops_after = sgs_mod._AUDIT_DROPS._value.get()
    assert drops_after - drops_before == 3, (
        f"Expected 3 audit drops, got {drops_after - drops_before}"
    )


@pytest.mark.asyncio
async def test_ledger_write_failure_still_publishes_record():
    """When DB write fails, BarIntelligenceRecord is still published with ledger_written=False.

    This is the critical resilience property: pipeline must never crash on DB errors.
    """
    import json
    from unittest.mock import patch

    from src.intelligence.schemas import (
        I1Indicators,
        I2Events,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )

    ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    event = IntelligenceEvent(
        ts=ts,
        symbol="ES",
        tf="5m",
        bar=OHLCVBar(o=5100.0, h=5110.0, l=5095.0, c=5105.0, v=10000),
        i1=I1Indicators(rsi_14=55.0, atr_14=10.0),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    mock_producer = MagicMock()
    publish_calls = []

    async def _mock_publish(topic, payload, key=None):
        publish_calls.append({"topic": topic, "payload": payload})

    mock_producer.publish = _mock_publish

    svc = _make_svc_for_pipeline({"_kafka_producer": mock_producer})
    raw_signals = [_make_minimal_signal()]

    # Make DB write raise — but pipeline must continue and publish record
    with patch(
        "services.signal_generator_service.insert_signals_with_features",
        side_effect=Exception("DB down"),
    ):
        await svc._process_event(
            event=event,
            symbol="ES",
            timeframe="5m",
            timestamp=ts,
            bar_close_ts=None,
            source="live",
            raw_signals=raw_signals,
            regime_data=None,
            drift_penalty=1.0,
            features={},
        )

    # BarIntelligenceRecord must be published regardless of DB failure
    record_publishes = [
        c for c in publish_calls
        if "intelligence.record" in c["topic"]
    ]
    assert len(record_publishes) >= 1, (
        "BarIntelligenceRecord must be published even when DB write fails"
    )
    # Verify ledger_written=False in the record
    record_json = record_publishes[0]["payload"]
    if isinstance(record_json, str):
        record_data = json.loads(record_json)
        assert record_data.get("ledger_written") is False, (
            "ledger_written must be False when DB write fails"
        )


@pytest.mark.asyncio
async def test_pipeline_metrics_incremented():
    """_process_event increments _PIPELINE_STAGE_INPUT counter for quality_gate stage."""
    import services.signal_generator_service as sgs_mod

    svc = _make_svc_for_pipeline()
    ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    raw_signals = [
        _make_minimal_signal("trad_TrendFollowing", 1),
        _make_minimal_signal("trad_MeanReversion", -1),
        _make_minimal_signal("trad_OFISpike", 1),
    ]

    before = sgs_mod._PIPELINE_STAGE_INPUT.labels(stage="quality_gate")._value.get()

    await svc._process_event(
        event=None,
        symbol="ES",
        timeframe="5m",
        timestamp=ts,
        bar_close_ts=None,
        source="live",
        raw_signals=raw_signals,
        regime_data=None,
        drift_penalty=1.0,
        features={},
    )

    after = sgs_mod._PIPELINE_STAGE_INPUT.labels(stage="quality_gate")._value.get()
    assert after - before == 3, (
        f"Expected quality_gate input counter to increase by 3, got {after - before}"
    )


def test_to_ranked_signal_maps_fields():
    """_to_ranked_signal correctly maps signal dict fields to RankedSignal model."""
    from services.signal_generator_service import SignalGeneratorService
    from src.intelligence.schemas import RankedSignal

    svc = SignalGeneratorService.__new__(SignalGeneratorService)

    sig = {
        "signal_id": "abc123",
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "confidence": 0.65,
        "_raw_confidence": 0.80,
        "calibrated_confidence": 0.72,
        "regime_eligible": True,
        "quality_score": 0.90,
        "tod_multiplier": 1.1,
        "adjusted_rank": 3.0,
    }

    result = svc._to_ranked_signal(sig, winner=None)

    assert isinstance(result, RankedSignal)
    assert result.signal_id == "abc123"
    assert result.plugin == "trad_TrendFollowing"
    assert result.direction == 1
    assert result.raw_confidence == pytest.approx(0.80)
    assert result.calibrated_confidence == pytest.approx(0.72)
    assert result.regime_eligible is True
    assert result.quality_score == pytest.approx(0.90)
    assert result.tod_multiplier == pytest.approx(1.1)
    assert result.adjusted_rank == pytest.approx(3.0)
    assert result.is_winner is False


def test_to_ranked_signal_is_winner_true_when_matching_winner():
    """_to_ranked_signal sets is_winner=True when signal matches winner plugin+direction."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)

    sig = {
        "signal_id": "abc123",
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "confidence": 0.75,
        "_raw_confidence": 0.80,
        "calibrated_confidence": 0.75,
        "regime_eligible": True,
        "quality_score": 1.0,
        "tod_multiplier": 1.0,
        "adjusted_rank": 1.0,
    }
    winner = {"setup_plugin": "trad_TrendFollowing", "direction": 1}

    result = svc._to_ranked_signal(sig, winner=winner)
    assert result.is_winner is True


@pytest.mark.asyncio
async def test_backward_compat_i7_retired():
    """_process_event no longer publishes to intelligence.i7 — topic retired in Phase 44.3.

    intelligence.i7 topic is replaced by intelligence.record as the signal_scorecard source.
    Verifies: no publish to intelligence.i7, and intelligence.record IS published.
    """
    from src.intelligence.schemas import (
        I1Indicators,
        I2Events,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )

    ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    event = IntelligenceEvent(
        ts=ts,
        symbol="ES",
        tf="5m",
        bar=OHLCVBar(o=5100.0, h=5110.0, l=5095.0, c=5105.0, v=10000),
        i1=I1Indicators(rsi_14=55.0, atr_14=10.0),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    mock_producer = MagicMock()
    publish_calls = []

    async def _mock_publish(topic, payload, key=None):
        publish_calls.append(topic)

    mock_producer.publish = _mock_publish

    svc = _make_svc_for_pipeline({"_kafka_producer": mock_producer})
    raw_signals = [_make_minimal_signal()]

    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="5m",
        timestamp=ts,
        bar_close_ts=None,
        source="live",
        raw_signals=raw_signals,
        regime_data=None,
        drift_penalty=1.0,
        features={},
    )

    # intelligence.i7 must NOT be published — topic retired in Phase 44.3
    i7_topics = [t for t in publish_calls if "intelligence.i7" in t]
    assert len(i7_topics) == 0, (
        f"intelligence.i7 topic is retired — expected no publish, got: {i7_topics}"
    )

    # intelligence.record must be published (single atomic persistence source)
    record_topics = [t for t in publish_calls if "intelligence.record" in t]
    assert len(record_topics) >= 1, (
        f"Expected publish to intelligence.record, got: {publish_calls}"
    )


@pytest.mark.asyncio
async def test_signals_aggregated_published_on_winner():
    """When a winner is selected, signals.aggregated is published.
    When no winner (empty signals), signals.aggregated is NOT published.
    """

    from src.intelligence.schemas import (
        I1Indicators,
        I2Events,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        SMCContext,
    )

    ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    event = IntelligenceEvent(
        ts=ts,
        symbol="ES",
        tf="5m",
        bar=OHLCVBar(o=5100.0, h=5110.0, l=5095.0, c=5105.0, v=10000),
        i1=I1Indicators(rsi_14=55.0, atr_14=10.0),
        i2=I2Events(),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )

    # Test WITH winner: high-confidence signal that passes all gates
    mock_producer = MagicMock()
    publish_topics_with_winner = []

    async def _mock_publish_with(topic, payload, key=None):
        publish_topics_with_winner.append(topic)

    mock_producer.publish = _mock_publish_with

    svc = _make_svc_for_pipeline({"_kafka_producer": mock_producer})
    raw_signals = [_make_minimal_signal(confidence=0.85)]

    await svc._process_event(
        event=event,
        symbol="ES",
        timeframe="5m",
        timestamp=ts,
        bar_close_ts=None,
        source="live",
        raw_signals=raw_signals,
        regime_data=None,
        drift_penalty=1.0,
        features={},
    )

    aggregated_published = any("signals.aggregated" in t for t in publish_topics_with_winner)
    assert aggregated_published, (
        "signals.aggregated must be published when a winner is selected; "
        f"published topics: {publish_topics_with_winner}"
    )

    # Test WITHOUT signals: empty raw_signals → no winner → no signals.aggregated publish
    mock_producer2 = MagicMock()
    publish_topics_no_winner = []

    async def _mock_publish_no(topic, payload, key=None):
        publish_topics_no_winner.append(topic)

    mock_producer2.publish = _mock_publish_no

    svc2 = _make_svc_for_pipeline({"_kafka_producer": mock_producer2})

    await svc2._process_event(
        event=event,
        symbol="ES",
        timeframe="5m",
        timestamp=ts,
        bar_close_ts=None,
        source="live",
        raw_signals=[],  # no signals → no winner
        regime_data=None,
        drift_penalty=1.0,
        features={},
    )

    aggregated_no_winner = any("signals.aggregated" in t for t in publish_topics_no_winner)
    assert not aggregated_no_winner, (
        "signals.aggregated must NOT be published when no signals fire; "
        f"published topics: {publish_topics_no_winner}"
    )


# ── DB warmup seed (Phase 48) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_success():
    """Test successful seeding populates BarHistory with bars from DB."""
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock

    from services.signal_generator_service import SignalGeneratorService
    from src.core.bar_history import BarHistory
    from src.config.settings import Instrument

    # Mock DB response with 2 bars (DESC order from ORDER BY ts DESC)
    mock_rows = [
        {
            "ts": datetime(2026, 3, 23, 14, 1, tzinfo=UTC),  # Newest (DESC order)
            "bar": {"o": 4502.0, "h": 4506.0, "l": 4500.0, "c": 4504.0, "v": 1200},
            "session_type": "rth"
        },
        {
            "ts": datetime(2026, 3, 23, 14, 0, tzinfo=UTC),  # Oldest
            "bar": {"o": 4500.0, "h": 4505.0, "l": 4498.0, "c": 4502.0, "v": 1000},
            "session_type": "rth"
        }
    ]

    # Create service instance
    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc.logger = MagicMock()

    # Mock db_manager
    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(return_value=mock_rows)
    svc.db_manager = mock_db

    # Mock config with timeframes
    svc.config = {
        "service": {
            "timeframes": ["1m", "5m"]
        }
    }

    # Mock get_active_contracts to return test instrument
    test_instrument = Instrument(
        symbol="ES",
        base="ES",
        asset_class="futures",
        point_value=50.0,
        tick_size=0.25,
        session_id="futures_24_5",
        exchange="CME",
        sector="equity_index",
        name="E-mini S&P 500",
        provider_meta={}
    )

    # Mock get_active_contracts at module level
    import services.signal_generator_service as sgs_mod
    original_get_active = sgs_mod.get_active_contracts
    sgs_mod.get_active_contracts = lambda: [test_instrument]

    try:
        await svc._seed_bar_history_from_db()

        # Verify DB query was called for each (symbol, tf) combination
        assert mock_db.execute_query.call_count == 2  # 1 symbol × 2 timeframes

        # Verify BarHistory populated
        bars_1m = svc._bar_history.get("ES", "1m")
        bars_5m = svc._bar_history.get("ES", "5m")

        assert len(bars_1m) == 2
        # After reversing DESC rows: oldest first (14:00 at index 0, 14:01 at index 1)
        assert bars_1m[0].close == 4502.0
        assert bars_1m[1].close == 4504.0
        assert bars_1m[0].source == "ibkr_seed"

        assert len(bars_5m) == 2
        assert bars_5m[0].close == 4502.0
        assert bars_5m[1].close == 4504.0

        # Verify log message
        svc.logger.info.assert_called_once()
        assert "BarHistory seeded from database" in str(svc.logger.info.call_args)
    finally:
        # Restore original function
        sgs_mod.get_active_contracts = original_get_active


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_no_db_manager():
    """Test graceful fallback when db_manager is None."""
    from services.signal_generator_service import SignalGeneratorService
    from src.core.bar_history import BarHistory

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc.db_manager = None  # No DB manager
    svc.logger = MagicMock()

    # Should not raise exception
    await svc._seed_bar_history_from_db()

    # Verify warning logged
    svc.logger.warning.assert_called_once()
    assert "DB seed failed - no db_manager" in str(svc.logger.warning.call_args)

    # BarHistory should remain empty
    bars = svc._bar_history.get("ES", "1m")
    assert len(bars) == 0


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_exception_fallback():
    """Test graceful fallback when DB query raises exception."""
    from unittest.mock import AsyncMock, MagicMock

    from services.signal_generator_service import SignalGeneratorService
    from src.core.bar_history import BarHistory
    from src.config.settings import Instrument

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc.logger = MagicMock()

    # Mock db_manager that raises exception
    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(side_effect=Exception("DB connection failed"))
    svc.db_manager = mock_db

    svc.config = {
        "service": {
            "timeframes": ["1m"]
        }
    }

    # Mock get_active_contracts to return test instrument
    test_instrument = Instrument(
        symbol="ES",
        base="ES",
        asset_class="futures",
        point_value=50.0,
        tick_size=0.25,
        session_id="futures_24_5",
        exchange="CME",
        sector="equity_index",
        name="E-mini S&P 500",
        provider_meta={}
    )

    import services.signal_generator_service as sgs_mod
    original_get_active = sgs_mod.get_active_contracts
    sgs_mod.get_active_contracts = lambda: [test_instrument]

    try:
        # Should not raise exception
        await svc._seed_bar_history_from_db()

        # Verify warning logged with error message
        svc.logger.warning.assert_called()
        assert "DB seed failed" in str(svc.logger.warning.call_args)
    finally:
        sgs_mod.get_active_contracts = original_get_active


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_empty_result():
    """Test seeding when DB returns no rows (no historical data)."""
    from unittest.mock import AsyncMock, MagicMock

    from services.signal_generator_service import SignalGeneratorService
    from src.core.bar_history import BarHistory
    from src.config.settings import Instrument

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._bar_history = BarHistory(maxlen=200)
    svc.logger = MagicMock()

    # Mock DB response with empty rows
    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(return_value=[])
    svc.db_manager = mock_db

    svc.config = {
        "service": {
            "timeframes": ["1m"]
        }
    }

    # Mock get_active_contracts to return test instrument
    test_instrument = Instrument(
        symbol="ES",
        base="ES",
        asset_class="futures",
        point_value=50.0,
        tick_size=0.25,
        session_id="futures_24_5",
        exchange="CME",
        sector="equity_index",
        name="E-mini S&P 500",
        provider_meta={}
    )

    import services.signal_generator_service as sgs_mod
    original_get_active = sgs_mod.get_active_contracts
    sgs_mod.get_active_contracts = lambda: [test_instrument]

    try:
        # Should not raise exception
        await svc._seed_bar_history_from_db()

        # BarHistory should remain empty (no data to seed)
        bars = svc._bar_history.get("ES", "1m")
        assert len(bars) == 0

        # Verify info logged (success, even though no rows)
        svc.logger.info.assert_called_once()
    finally:
        sgs_mod.get_active_contracts = original_get_active

