"""Tests for indicator_service — standalone I1 computation service."""

from datetime import datetime


def test_build_i1_message_includes_ohlcv_and_features():
    """Combined message must contain OHLCV fields AND I1 feature outputs."""
    from services.indicator_service import build_i1_message

    bar = {"open": 5300.0, "high": 5305.0, "low": 5299.0, "close": 5303.0, "volume": 1000}
    features = {"rsi_14": 58.3, "macd": 2.1, "atr_14": 4.5}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert msg["open"] == "5300.0"
    assert msg["high"] == "5305.0"
    assert msg["close"] == "5303.0"
    assert msg["volume"] == "1000"
    assert msg["rsi_14"] == "58.3"
    assert msg["macd"] == "2.1"
    assert msg["timestamp"] == ts.isoformat()
    assert msg["symbol"] == "ES"
    assert msg["timeframe"] == "1m"


def test_build_i1_message_skips_non_scalar_features():
    """Non-scalar values (lists, dicts) must be excluded from message."""
    from services.indicator_service import build_i1_message

    bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}
    features = {"rsi_14": 55.0, "targets": [101.0, 102.0], "meta": {"x": 1}}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert "rsi_14" in msg
    assert "targets" not in msg
    assert "meta" not in msg


def test_parse_indicators_message_splits_ohlcv_and_features():
    """parse_indicators_message must split OHLCV from feature fields."""
    from services.indicator_service import parse_indicators_message

    raw = {
        b"timestamp": b"2026-02-20T10:00:00",
        b"symbol": b"ES",
        b"timeframe": b"1m",
        b"open": b"5300.0",
        b"high": b"5305.0",
        b"low": b"5299.0",
        b"close": b"5303.0",
        b"volume": b"1000",
        b"rsi_14": b"58.3",
        b"macd": b"2.1",
    }

    bar, features = parse_indicators_message(raw)

    assert bar["open"] == 5300.0
    assert bar["close"] == 5303.0
    assert bar["volume"] == 1000
    assert features["rsi_14"] == 58.3
    assert features["macd"] == 2.1
    assert "open" not in features
    assert "timestamp" not in features
