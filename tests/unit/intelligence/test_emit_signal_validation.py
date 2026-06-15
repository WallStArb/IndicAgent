"""Tests for emit_signal() in plugin_utils.py (Phase 100.5 Task 6)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_trade_frame(viable=True, entry=5000.0, stop=4980.0, targets=None):
    """Build a minimal TradeFrame-like mock."""
    tf = MagicMock()
    tf.viable = viable
    tf.entry = entry
    tf.stop = stop
    tf.stop_type = "atr"
    tf.entry_type = "at_close"
    tf.zone_low = 4975.0
    tf.zone_high = 5005.0
    tf.rr_t1 = 2.0
    tf.rr_t2 = None
    tf.rr_t3 = None
    tf.method = "atr"
    tf.rejection_reason = None
    # Targets as a list of mock objects with .price, .label, .level_type
    if targets is None:
        t1 = MagicMock()
        t1.price = 5040.0
        t1.label = "T1"
        t1.level_type = "atr"
        tf.targets = [t1]
    else:
        tf.targets = targets
    return tf


def test_emit_signal_importable():
    """emit_signal is importable from plugin_utils."""
    from src.intelligence.trading.plugin_utils import emit_signal

    assert emit_signal is not None


def test_emit_signal_returns_valid_signal():
    """emit_signal returns a validated signal dict."""
    from src.intelligence.trading.plugin_utils import emit_signal
    from src.intelligence.trading.signal_schema import validate_signal

    tf = _make_trade_frame()
    signal = emit_signal(
        tf,
        confidence=0.75,
        entry_type="at_close",
        stop_loss=4980.0,
        target_1=5040.0,
        symbol="ES",
        timeframe="1m",
        timestamp="2026-05-22T10:00:00Z",
        signal_type="trend_long",
        setup_plugin="TrendPlugin",
        direction=1,
        regime_context="trending",
        confluence_score=0.8,
        supporting_factors=["ema_slope"],
        invalidation_conditions=["close_below_stop"],
    )
    assert signal is not None
    assert validate_signal(signal), f"Signal failed validation: {signal}"


def test_emit_signal_raises_on_invalid_signal():
    """emit_signal raises ValueError when signal validation fails."""
    from src.intelligence.trading.plugin_utils import emit_signal

    tf = _make_trade_frame()
    with pytest.raises(ValueError):
        # Missing required fields — direction 0 is invalid
        emit_signal(
            tf,
            confidence=0.75,
            entry_type="at_close",
            stop_loss=4980.0,
            target_1=5040.0,
            symbol="ES",
            timeframe="1m",
            timestamp="2026-05-22T10:00:00Z",
            signal_type="none",
            setup_plugin="TrendPlugin",
            direction=0,  # invalid direction
            regime_context="trending",
            confluence_score=0.8,
            supporting_factors=[],
            invalidation_conditions=[],
        )


def test_emit_signal_no_features_snapshot_field():
    """Phase 126-06: features_snapshot is no longer a signal field (stamped by pipeline annotation layer)."""
    from src.intelligence.trading.plugin_utils import emit_signal

    tf = _make_trade_frame()
    tf.features = {"ctf_trend_score": 0.85, "regime": "trending"}  # non-empty features

    signal = emit_signal(
        tf,
        confidence=0.75,
        entry_type="at_close",
        stop_loss=4980.0,
        target_1=5040.0,
        symbol="ES",
        timeframe="1m",
        timestamp="2026-05-22T10:00:00Z",
        signal_type="trend_long",
        setup_plugin="TrendPlugin",
        direction=1,
        regime_context="trending",
        confluence_score=0.8,
        supporting_factors=["ema_slope"],
        invalidation_conditions=["close_below_stop"],
    )
    assert "features_snapshot" not in signal


def test_emit_signal_no_features_snapshot_when_empty():
    """emit_signal does not write features_snapshot when trade_frame.features is empty."""
    from src.intelligence.trading.plugin_utils import emit_signal

    tf = _make_trade_frame()
    tf.features = {}  # empty features — no snapshot

    signal = emit_signal(
        tf,
        confidence=0.75,
        entry_type="at_close",
        stop_loss=4980.0,
        target_1=5040.0,
        symbol="ES",
        timeframe="1m",
        timestamp="2026-05-22T10:00:00Z",
        signal_type="trend_long",
        setup_plugin="TrendPlugin",
        direction=1,
        regime_context="trending",
        confluence_score=0.8,
        supporting_factors=["ema_slope"],
        invalidation_conditions=["close_below_stop"],
    )
    assert signal.get("features_snapshot") is None or "features_snapshot" not in signal


def test_emit_signal_accepts_target_2():
    """emit_signal accepts optional target_2 parameter."""
    from src.intelligence.trading.plugin_utils import emit_signal

    tf = _make_trade_frame()
    t2 = MagicMock()
    t2.price = 5080.0
    t2.label = "T2"
    t2.level_type = "atr"
    tf.targets = [tf.targets[0], t2]

    signal = emit_signal(
        tf,
        confidence=0.75,
        entry_type="at_close",
        stop_loss=4980.0,
        target_1=5040.0,
        target_2=5080.0,
        symbol="ES",
        timeframe="1m",
        timestamp="2026-05-22T10:00:00Z",
        signal_type="trend_long",
        setup_plugin="TrendPlugin",
        direction=1,
        regime_context="trending",
        confluence_score=0.8,
        supporting_factors=["ema_slope"],
        invalidation_conditions=["close_below_stop"],
    )
    assert signal is not None
    assert len(signal["targets"]) >= 1
