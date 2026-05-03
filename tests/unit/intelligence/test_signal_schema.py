"""Tests for signal schema validation."""

import pytest

from src.intelligence.trading.signal_schema import (
    make_signal,
    make_signal_from_frame,
    validate_signal,
)
from src.intelligence.trading.trade_framer import TradeFrame, TradeTarget


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
        symbol="NQ",
        timeframe="15m",
        timestamp="2026-02-16T15:00:00Z",
        signal_type="trend_short",
        setup_plugin="trad_TrendFollowing",
        direction=-1,
        entry_price=18000.0,
        stop_loss=18050.0,
        targets=[17950.0, 17900.0],
        confidence=0.8,
        regime_context="bearish",
        confluence_score=0.7,
        supporting_factors=["trend_regime_bearish"],
        invalidation_conditions=["price_above_18060"],
    )
    assert validate_signal(signal) is True
    assert signal["risk_reward_ratio"] == 1.0  # 50/50


def test_make_signal_clamps_confidence():
    signal = make_signal(
        symbol="ES",
        timeframe="1m",
        timestamp="2026-02-16T15:00:00Z",
        signal_type="trend_long",
        setup_plugin="trad_TrendFollowing",
        direction=1,
        entry_price=5100.0,
        stop_loss=5090.0,
        targets=[5110.0],
        confidence=1.5,
        regime_context="bullish",
        confluence_score=0.5,
        supporting_factors=[],
        invalidation_conditions=[],
    )
    assert signal["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Fixtures for make_signal_from_frame tests
# ---------------------------------------------------------------------------


def _viable_frame() -> TradeFrame:
    return TradeFrame(
        entry=4500.0,
        entry_type="at_close",
        stop=4480.0,
        stop_type="swing_low",
        targets=[
            TradeTarget(price=4530.0, label="S/R 4530", level_type="sr", rr=1.5),
            TradeTarget(price=4560.0, label="BSL 4560", level_type="bsl", rr=3.0),
            TradeTarget(price=4600.0, label="ATR T3", level_type="atr", rr=5.0),
        ],
        rr_t1=1.5,
        rr_t2=3.0,
        rr_t3=5.0,
        method="structural",
        viable=True,
        rejection_reason=None,
        zone_low=4495.0,
        zone_high=4505.0,
    )


def _nonviable_frame() -> TradeFrame:
    return TradeFrame(
        entry=4500.0,
        entry_type="at_close",
        stop=4480.0,
        stop_type="atr",
        viable=False,
        rejection_reason="rr_below_1.5: 0.8",
        zone_low=4490.0,
        zone_high=4510.0,
    )


def _frame_kwargs() -> dict:
    return dict(
        symbol="ES",
        timeframe="5m",
        timestamp="2026-05-03T12:00:00Z",
        signal_type="trend_long",
        setup_plugin="TrendFollowingPlugin",
        direction=1,
        confidence=0.75,
        regime_context="trending",
        confluence_score=0.6,
        supporting_factors=["strong trend"],
        invalidation_conditions=["trend reversal"],
    )


class TestMakeSignalFromFrame:
    def test_make_signal_from_frame_propagates_zones(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert sig["zone_low"] == 4495.0
        assert sig["zone_high"] == 4505.0

    def test_make_signal_from_frame_uses_resolved_entry(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert sig["entry_price"] == tf.entry

    def test_make_signal_from_frame_schema_version(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert sig["signal_schema_version"] == "v1"

    def test_make_signal_from_frame_propagates_stop_type_and_targets(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert sig["stop_type"] == "swing_low"
        assert sig["targets"] == [4530.0, 4560.0, 4600.0]
        assert sig["target_labels"] == ["S/R 4530", "BSL 4560", "ATR T3"]
        assert sig["target_types"] == ["sr", "bsl", "atr"]
        assert sig["rr_t1"] == 1.5
        assert sig["rr_t2"] == 3.0
        assert sig["rr_t3"] == 5.0

    def test_make_signal_from_frame_rejects_nonviable(self):
        tf = _nonviable_frame()
        with pytest.raises(ValueError, match="non-viable"):
            make_signal_from_frame(tf, **_frame_kwargs())

    def test_make_signal_from_frame_validates_as_signal_v1(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert validate_signal(sig) is True

    def test_make_signal_from_frame_features_snapshot(self):
        tf = _viable_frame()
        snap = {"i7_momentum": 0.8, "ctf_trend_alignment": 0.6}
        sig = make_signal_from_frame(tf, features_snapshot=snap, **_frame_kwargs())
        assert sig["features_snapshot"] == snap

    def test_make_signal_from_frame_no_features_snapshot_by_default(self):
        tf = _viable_frame()
        sig = make_signal_from_frame(tf, **_frame_kwargs())
        assert "features_snapshot" not in sig
