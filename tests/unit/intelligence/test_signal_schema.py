"""Tests for signal schema validation."""

from src.intelligence.trading.signal_schema import validate_signal, make_signal


def _make_valid_signal() -> dict:
    return {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-02-16T14:30:00Z",
        "signal_type": "trend_long",
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5090.0,
        "targets": [5110.0],
        "confidence": 0.75,
        "risk_reward_ratio": 2.0,
        "regime_context": "bullish",
        "confluence_score": 0.82,
        "supporting_factors": [],
        "invalidation_conditions": [],
        "ttl_bars": 10,
    }


def test_valid_signal_passes():
    assert validate_signal(_make_valid_signal()) is True


def test_missing_field_fails():
    signal = {"type": "signal.v1", "symbol": "ES"}
    assert validate_signal(signal) is False


def test_confidence_out_of_range_fails():
    signal = _make_valid_signal()
    signal["confidence"] = 1.5
    assert validate_signal(signal) is False


def test_direction_must_be_plus_minus_one():
    signal = _make_valid_signal()
    signal["direction"] = 0
    assert validate_signal(signal) is False


def test_make_signal_produces_valid_output():
    signal = make_signal(
        symbol="NQ", timeframe="15m", timestamp="2026-02-16T15:00:00Z",
        signal_type="trend_short", setup_plugin="trad_TrendFollowing",
        direction=-1, entry_price=18000.0, stop_loss=18050.0,
        targets=[17950.0, 17900.0], confidence=0.8,
        regime_context="bearish", confluence_score=0.7,
        supporting_factors=["trend_regime_bearish"],
        invalidation_conditions=["price_above_18060"],
    )
    assert validate_signal(signal) is True
    assert signal["risk_reward_ratio"] == 1.0  # 50/50


def test_make_signal_clamps_confidence():
    signal = make_signal(
        symbol="ES", timeframe="1m", timestamp="2026-02-16T15:00:00Z",
        signal_type="trend_long", setup_plugin="trad_TrendFollowing",
        direction=1, entry_price=5100.0, stop_loss=5090.0,
        targets=[5110.0], confidence=1.5,
        regime_context="bullish", confluence_score=0.5,
        supporting_factors=[], invalidation_conditions=[],
    )
    assert signal["confidence"] == 1.0
