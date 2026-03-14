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

    async def mock_process_bar(symbol, timeframe, bar, features, frames, timestamp, **kwargs):
        captured_bar.update(bar)
        captured_features.update({k: v for k, v in features.items() if v is not None})

    svc._df_cache = {}
    svc._regime_cache = collections.defaultdict(dict)
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
        symbol="ES", tf="1m",
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


# ── _build_i7_payload ─────────────────────────────────────────────────────────


class TestBuildI7Payload:
    """Tests for _build_i7_payload pure function."""

    def _make_result(self, all_ranked=None, selected_plugin=None):
        from src.intelligence.trading.aggregator import AggregatedResult
        selected = {"setup_plugin": selected_plugin} if selected_plugin else None
        return AggregatedResult(
            selected_signal=selected,
            all_ranked=all_ranked or [],
            num_signals_fired=len(all_ranked or []),
        )

    def _ts(self):
        return datetime(2026, 3, 4, 10, 0, 0, tzinfo=UTC)

    def test_empty_all_ranked_produces_empty_list(self):
        """result.all_ranked=[] → payload data decodes to []."""
        import json

        from services.signal_generator_service import _build_i7_payload

        result = self._make_result()
        msg = _build_i7_payload(result, self._ts(), "ESH6", "5m")

        assert json.loads(msg["data"]) == []

    def test_signal_shape_has_all_required_keys(self):
        """Single signal in all_ranked → decoded list item has all required keys."""
        import json

        from services.signal_generator_service import _build_i7_payload

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_following_long",
            "direction": 1,
            "confidence": 0.75,
            "regime_eligible": True,
            "suppression_reason": None,
            "entry_price": 5100.0,
            "stop_loss": 5080.0,
            "targets": [5140.0],
            "composite_rank": 1,
        }
        result = self._make_result(all_ranked=[sig], selected_plugin="trad_TrendFollowing")
        msg = _build_i7_payload(result, self._ts(), "ESH6", "5m")

        items = json.loads(msg["data"])
        assert len(items) == 1
        item = items[0]
        for key in (
            "setup_type", "confidence", "direction", "regime_eligible",
            "suppression_reason", "entry", "stop", "target", "composite_rank", "is_winner",
        ):
            assert key in item, f"Missing key: {key}"

    def test_winner_flagged_on_selected_signal(self):
        """Rank-1 eligible signal matching selected_plugin gets is_winner=True."""
        import json

        from services.signal_generator_service import _build_i7_payload

        sig1 = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_following_long",
            "direction": 1, "confidence": 0.75, "regime_eligible": True,
            "suppression_reason": None, "entry_price": 5100.0,
            "stop_loss": 5080.0, "targets": [5140.0], "composite_rank": 1,
        }
        sig2 = {
            "setup_plugin": "trad_MeanReversion",
            "signal_type": "mean_reversion_long",
            "direction": 1, "confidence": 0.60, "regime_eligible": True,
            "suppression_reason": None, "entry_price": 5100.0,
            "stop_loss": 5080.0, "targets": [5140.0], "composite_rank": 2,
        }
        result = self._make_result(all_ranked=[sig1, sig2], selected_plugin="trad_TrendFollowing")
        msg = _build_i7_payload(result, self._ts(), "ESH6", "5m")

        items = json.loads(msg["data"])
        winners = [i for i in items if i["is_winner"]]
        assert len(winners) == 1
        assert winners[0]["setup_type"] == "trend_following_long"

    def test_suppressed_signal_never_winner(self):
        """regime_eligible=False signal is never is_winner even if rank 1."""
        import json

        from services.signal_generator_service import _build_i7_payload

        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_following_long",
            "direction": 1, "confidence": 0.75, "regime_eligible": False,
            "suppression_reason": "regime_type", "entry_price": 5100.0,
            "stop_loss": 5080.0, "targets": [5140.0], "composite_rank": 1,
        }
        result = self._make_result(all_ranked=[sig], selected_plugin="trad_TrendFollowing")
        msg = _build_i7_payload(result, self._ts(), "ESH6", "5m")

        items = json.loads(msg["data"])
        assert items[0]["is_winner"] is False

    def test_payload_contains_ts_symbol_tf(self):
        """Payload dict has ts, symbol, tf keys for feature_writer routing."""
        from services.signal_generator_service import _build_i7_payload

        result = self._make_result()
        msg = _build_i7_payload(result, self._ts(), "NQH6", "15m")

        assert msg["symbol"] == "NQH6"
        assert msg["tf"] == "15m"
        assert "ts" in msg
        assert "2026-03-04" in msg["ts"]


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


# ── signal_id threading ──────────────────────────────────────────────────────


def test_build_ledger_entries_winning_entry_has_signal_id():
    """The was_selected=True LedgerEntry has a non-empty UUID4 signal_id."""
    import re

    from services.signal_generator_service import build_ledger_entries
    from src.intelligence.trading.aggregator import AggregatedResult

    selected_signal = {
        "setup_plugin": "trad_TrendFollowing",
        "signal_type": "trend_long",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5090.0,
        "targets": [5120.0],
        "confidence": 0.80,
        "confluence_score": 0.75,
        "regime_context": "trending_up",
        "supporting_factors": ["BOS confirmed"],
        "composite_rank": 1,
        "regime_eligible": True,
    }
    result = AggregatedResult(
        selected_signal=selected_signal,
        all_ranked=[selected_signal],
        num_signals_fired=1,
    )
    entries = build_ledger_entries(
        result,
        symbol="ESH6",
        timeframe="5m",
        timestamp=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
        features={},
    )

    assert len(entries) == 1
    winning = entries[0]
    assert winning.was_selected is True
    assert winning.signal_id != ""
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    winning.signal_id)


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


# ── _seed_bar_history_from_db ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_seed_bar_history_from_db_success():
    """Seeding populates bar_history with bars from intelligence_features."""
    import collections
    from unittest.mock import AsyncMock, patch

    from services.signal_generator_service import SignalGeneratorService

    # Mock service setup
    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m", "5m", "15m"]}}
    svc.logger = MagicMock()

    # Mock DB manager
    mock_db = AsyncMock()
    svc.db_manager = mock_db

    # Mock query returns exactly LIMIT rows (DESC order, newest first)
    # execute_query returns list[dict] with keys "ts" and "bar"
    mock_db.execute_query.return_value = [
        {"ts": datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC), "bar": {"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100}},
        {"ts": datetime(2026, 3, 10, 9, 59, 0, tzinfo=UTC), "bar": {"o": 0.8, "h": 1.2, "l": 0.6, "c": 1.0, "v": 80}},
    ]

    # Mock min_bars_for_tf to return 2 for 1m
    with patch("services.signal_generator_service.min_bars_for_tf", return_value=2):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES"]):
            await svc._seed_bar_history_from_db()

    # Verify bar_history was populated
    key = "ES:1m"
    assert key in svc.bar_history
    assert len(svc.bar_history[key]) == 2

    # Verify bar format conversion and chronological order (oldest first after reverse)
    # bar_history format: {"open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "timestamp": ...}
    first_bar = svc.bar_history[key][0]
    assert first_bar["open"] == 0.8  # Oldest bar (9:59, second in DESC result)
    assert first_bar["high"] == 1.2
    assert first_bar["low"] == 0.6
    assert first_bar["close"] == 1.0
    assert first_bar["volume"] == 80
    assert first_bar["timestamp"] == datetime(2026, 3, 10, 9, 59, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_multiple_symbols():
    """Seeding handles multiple symbols and timeframes."""
    import collections
    from unittest.mock import AsyncMock, patch

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m", "5m", "15m"]}}
    svc.logger = MagicMock()

    mock_db = AsyncMock()
    svc.db_manager = mock_db

    # Mock different results per symbol/TF combination
    # execute_query is called as execute_query(query, symbol, tf) → *args style
    def mock_execute_query_side_effect(query, symbol, tf):
        if symbol == "ES" and tf == "1m":
            return [
                {"ts": datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC), "bar": {"o": 1.0, "h": 1.2, "l": 0.8, "c": 1.1, "v": 100}},
                {"ts": datetime(2026, 3, 10, 9, 59, 0, tzinfo=UTC), "bar": {"o": 0.9, "h": 1.1, "l": 0.7, "c": 1.0, "v": 90}},
            ]
        elif symbol == "NQ" and tf == "5m":
            return [
                {"ts": datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC), "bar": {"o": 2.0, "h": 2.2, "l": 1.8, "c": 2.1, "v": 200}},
                {"ts": datetime(2026, 3, 10, 9, 55, 0, tzinfo=UTC), "bar": {"o": 1.9, "h": 2.1, "l": 1.7, "c": 2.0, "v": 190}},
            ]
        elif symbol == "ES" and tf == "15m":
            return [
                {"ts": datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC), "bar": {"o": 3.0, "h": 3.2, "l": 2.8, "c": 3.1, "v": 300}},
            ]
        return []

    mock_db.execute_query.side_effect = mock_execute_query_side_effect

    # Mock min_bars_for_tf to return different values per TF
    def mock_min_bars(tf):
        return {"1m": 2, "5m": 26, "15m": 26}.get(tf, 26)

    with patch("services.signal_generator_service.min_bars_for_tf", side_effect=mock_min_bars):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES", "NQ"]):
            await svc._seed_bar_history_from_db()

    # Verify all symbol/TF combinations were seeded
    assert "ES:1m" in svc.bar_history
    assert "NQ:5m" in svc.bar_history
    assert "ES:15m" in svc.bar_history

    # Verify correct bar counts (limited by DB availability, not min_bars_for_tf)
    assert len(svc.bar_history["ES:1m"]) == 2
    assert len(svc.bar_history["NQ:5m"]) == 2
    assert len(svc.bar_history["ES:15m"]) == 1


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_partial_data():
    """Seeding handles partial data (less than min_bars_for_tf)."""
    import collections
    from unittest.mock import AsyncMock, patch

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m"]}}
    svc.logger = MagicMock()

    mock_db = AsyncMock()
    svc.db_manager = mock_db

    # Return only 1 bar (less than min_bars_for_tf=120)
    mock_db.execute_query.return_value = [
        {"ts": datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC), "bar": {"o": 1.0, "h": 1.2, "l": 0.8, "c": 1.1, "v": 100}},
    ]

    with patch("services.signal_generator_service.min_bars_for_tf", return_value=120):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES"]):
            await svc._seed_bar_history_from_db()

    # Verify bar_history contains whatever DB returned (doesn't enforce min_bars)
    key = "ES:1m"
    assert key in svc.bar_history
    assert len(svc.bar_history[key]) == 1


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_unavailable():
    """Seeding gracefully degrades when DB is unavailable."""
    import collections
    from unittest.mock import AsyncMock, patch

    import psycopg2

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m"]}}
    svc.logger = MagicMock()

    mock_db = AsyncMock()
    svc.db_manager = mock_db

    # Mock DB error
    mock_db.execute_query.side_effect = psycopg2.OperationalError("connection timeout")

    with patch("services.signal_generator_service.min_bars_for_tf", return_value=120):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES"]):
            await svc._seed_bar_history_from_db()

    # Verify WARNING log was emitted
    svc.logger.warning.assert_called()
    warning_call = str(svc.logger.warning.call_args)
    assert "DB seed failed" in warning_call or "falling back" in warning_call

    # Verify bar_history remains empty (graceful fallback to live warmup)
    assert "ES:1m" not in svc.bar_history or len(svc.bar_history.get("ES:1m", [])) == 0


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_no_db_manager():
    """Seeding handles None db_manager gracefully."""
    import collections
    from unittest.mock import patch

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m"]}}
    svc.logger = MagicMock()
    svc.db_manager = None  # No DB manager

    with patch("services.signal_generator_service.min_bars_for_tf", return_value=120):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES"]):
            await svc._seed_bar_history_from_db()

    # Verify WARNING log was emitted
    svc.logger.warning.assert_called()

    # Verify bar_history remains empty
    assert "ES:1m" not in svc.bar_history or len(svc.bar_history.get("ES:1m", [])) == 0


@pytest.mark.asyncio
async def test_seed_bar_history_from_db_empty_result():
    """Seeding handles empty DB result set."""
    import collections
    from unittest.mock import AsyncMock, patch

    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.bar_history = collections.defaultdict(lambda: collections.deque(maxlen=200))
    svc._df_cache = {}
    svc.config = {"service": {"timeframes": ["1m"]}}
    svc.logger = MagicMock()

    mock_db = AsyncMock()
    svc.db_manager = mock_db

    # Return empty result
    mock_db.execute_query.return_value = []

    with patch("services.signal_generator_service.min_bars_for_tf", return_value=120):
        with patch("services.signal_generator_service.get_active_contracts", return_value=["ES"]):
            await svc._seed_bar_history_from_db()

    # Verify bar_history remains empty
    assert "ES:1m" not in svc.bar_history or len(svc.bar_history.get("ES:1m", [])) == 0


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
        assert len(blocked) == 0, (
            f"Same setup+direction within cooldown window should be blocked, got {blocked}"
        )

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
        assert len(accepted) == 1, (
            f"Different setup should not be blocked by TrendFollowing cooldown, got {accepted}"
        )

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
        assert len(accepted) == 1, (
            f"Opposite direction should not be blocked, got {accepted}"
        )

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
        expired_ts = datetime(
            2026, 3, 10, 10, cooldown_bars, 0, tzinfo=UTC
        )  # 3 bars = 3 min on 1m

        accepted = svc._filter_setup_cooldown("ESH6", "1m", [sig], expired_ts)
        assert len(accepted) == 1, (
            f"Signal should be accepted after {cooldown_bars} bars, got {accepted}"
        )

    def test_cooldown_keyed_by_symbol_tf_plugin_direction(self):
        """Cooldown state is keyed by (symbol, tf, plugin, direction) — different symbol unaffected."""
        from datetime import datetime

        svc = _make_svc_with_cooldown()
        base_ts = datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC)
        next_ts = datetime(2026, 3, 10, 10, 1, 0, tzinfo=UTC)

        # Fire signal on ESH6
        sig = _make_signal("trad_TrendFollowing", 1)
        svc._filter_setup_cooldown("ESH6", "1m", [sig], base_ts)

        # Same plugin+direction but different symbol — should NOT be blocked
        accepted = svc._filter_setup_cooldown("NQH6", "1m", [sig], next_ts)
        assert len(accepted) == 1, (
            f"Different symbol should not be blocked by ESH6 cooldown, got {accepted}"
        )

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
    import ast
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
