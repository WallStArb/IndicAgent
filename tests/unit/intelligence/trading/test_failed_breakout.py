"""Unit tests for trad_FailedBreakout I7 plugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(close_arr, features=None, symbol="ES", tf="1m"):
    df = make_ohlcv(np.array(close_arr, dtype=float))
    return {
        "main": df,
        "features": features or {},
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


def _base_features(**kwargs):
    defaults = {
        "bos_detected": 0.0,
        "bos_direction": 0,
        "bos_level": 0.0,
        "hmm_regime": 0.0,
        "hmm_regime_prob": 0.8,
        "hmm_prob_ranging": 0.8,
        "hmm_prob_trending_up": 0.1,
        "hmm_prob_trending_down": 0.1,
        "atr_14": 5.0,
        "garch_vol_regime": 0.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Basic gate tests ─────────────────────────────────────────────────────────


def test_no_signal_when_bos_not_detected():
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close = np.linspace(5000.0, 5010.0, 25)
    frames = _make_frames(close, _base_features(bos_detected=0.0))
    result = plugin.compute_full(frames)
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


def test_no_signal_when_bos_detected_but_no_reversal_yet():
    """BOS just detected — bars_since_bos not past 3 but no close-back-through yet."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close = np.linspace(5000.0, 4990.0, 25)  # price falling (bearish BOS)
    # Bar 1: BOS detected at 5000.0
    feat1 = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    frames1 = _make_frames(close, feat1)
    result1 = plugin.compute_full(frames1)
    # On the bar that detects BOS: close is below bos_level (no reversal)
    assert result1.get("direction") == 0


def test_no_signal_when_reversal_window_exceeds_3_bars():
    """BOS detected but bars_since_bos exceeds 3 with no reversal — state cleared, no signal."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close = np.linspace(5000.0, 4985.0, 25)

    # Bar 0: detect BOS (bearish BOS at 5000), close below bos_level
    feat = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close, feat))

    # Bars 1-4: bos_detected=0, close remains below 5000 (no reversal)
    feat_no_bos = _base_features(bos_detected=0.0, bos_level=0.0)
    for _ in range(4):
        plugin.compute_full(_make_frames(close, feat_no_bos))

    # By bar 4, bars_since_bos > 3 so state should be cleared and no signal
    result = plugin.compute_full(_make_frames(close, feat_no_bos))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


def test_fires_on_bos_reversal_long():
    """Bearish BOS (bos_direction=-1), then close > bos_level within 3 bars -> long signal."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    # Bar 0: bearish BOS detected, price below bos_level (no reversal yet)
    feat_bos = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close_below, feat_bos))

    # Bar 1: no new BOS, but close jumps above bos_level (5001 > 5000)
    close_above = np.linspace(5000.0, 5001.0, 25)
    feat_rev = _base_features(bos_detected=0.0, bos_level=0.0)
    result = plugin.compute_full(_make_frames(close_above, feat_rev))

    assert result.get("direction") == 1
    assert result.get("signal_type") == "failed_breakout_long"
    assert result.get("confidence", 0.0) > 0.0
    assert "entry_price" in result
    assert "stop_loss" in result
    assert "targets" in result


def test_fires_on_bos_reversal_short():
    """Bullish BOS (bos_direction=1), then close < bos_level within 3 bars -> short signal."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_above = np.linspace(5000.0, 5010.0, 25)

    # Bar 0: bullish BOS detected at 5005.0, price above bos_level
    feat_bos = _base_features(bos_detected=1.0, bos_direction=1, bos_level=5005.0)
    plugin.compute_full(_make_frames(close_above, feat_bos))

    # Bar 1: close drops below bos_level (5003 < 5005) -> failed bullish BOS -> short
    close_below = np.linspace(5005.0, 5003.0, 25)
    feat_rev = _base_features(bos_detected=0.0, bos_level=0.0)
    result = plugin.compute_full(_make_frames(close_below, feat_rev))

    assert result.get("direction") == -1
    assert result.get("signal_type") == "failed_breakout_short"
    assert result.get("confidence", 0.0) > 0.0


def test_mean_reversion_regime_boosts_confidence():
    """hmm_regime=0.0 (ranging/mean-reversion aligned) boosts confidence."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin_mr = FailedBreakoutPlugin()
    plugin_trend = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    feat_bos = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)

    # Setup bearish BOS on both
    plugin_mr.compute_full(_make_frames(close_below, feat_bos))
    plugin_trend.compute_full(_make_frames(close_below, feat_bos))

    close_above = np.linspace(5000.0, 5001.0, 25)

    # Ranging regime (hmm=0) -> higher confidence
    feat_mr = _base_features(bos_detected=0.0, hmm_regime=0.0)
    result_mr = plugin_mr.compute_full(_make_frames(close_above, feat_mr))

    # Trend regime (hmm=1) -> lower confidence
    feat_trend = _base_features(
        bos_detected=0.0,
        hmm_regime=1.0,
        hmm_prob_ranging=0.1,
        hmm_prob_trending_up=0.8,
        hmm_prob_trending_down=0.1,
    )
    result_trend = plugin_trend.compute_full(_make_frames(close_above, feat_trend))

    assert result_mr.get("direction") == 1
    assert result_trend.get("direction") == 1
    assert result_mr.get("confidence", 0.0) > result_trend.get("confidence", 0.0)


def test_trend_regime_reduces_confidence():
    """hmm_regime=1.0 (trend) reduces confidence compared to base."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    feat_bos = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close_below, feat_bos))

    close_above = np.linspace(5000.0, 5001.0, 25)
    feat_trend = _base_features(
        bos_detected=0.0,
        hmm_regime=1.0,
        hmm_prob_ranging=0.1,
        hmm_prob_trending_up=0.8,
        hmm_prob_trending_down=0.1,
    )
    result = plugin.compute_full(_make_frames(close_above, feat_trend))

    # Trend regime should reduce confidence below base 0.55
    assert result.get("direction") == 1
    # With trend penalty -0.10 * trending_w, confidence should be below base
    assert result.get("confidence", 1.0) < 0.60


def test_bos_level_persists_in_state():
    """State persists bos_level so second call with bos_detected=0 still uses it."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    # Call 1: bos_detected=1.0, store bos_level=5000.0
    feat1 = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close_below, feat1))

    # Verify state was stored
    state = plugin._state.get(("ES", "1m"), {})
    assert state.get("bos_level") == 5000.0
    assert state.get("bos_direction") == -1

    # Call 2: bos_detected=0.0 (no new BOS), close rises above old bos_level
    close_above = np.linspace(5000.0, 5002.0, 25)
    feat2 = _base_features(bos_detected=0.0)  # no bos_level provided
    result = plugin.compute_full(_make_frames(close_above, feat2))

    # Should still fire because state retained the bos_level
    assert result.get("direction") == 1


def test_no_signal_when_frame_not_viable():
    """When frame_trade returns viable=False, plugin returns no_signal."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    # Setup BOS
    feat_bos = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close_below, feat_bos))

    close_above = np.linspace(5000.0, 5001.0, 25)
    feat_rev = _base_features(bos_detected=0.0)

    mock_frame = MagicMock()
    mock_frame.viable = False

    with patch(
        "src.intelligence.trading.failed_breakout.frame_trade",
        return_value=mock_frame,
    ):
        result = plugin.compute_full(_make_frames(close_above, feat_rev))

    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


def test_feature_logging_fields():
    """Fired signal includes bos_level, bars_since_bos, delta in supporting_factors."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close_below = np.linspace(5000.0, 4990.0, 25)

    feat_bos = _base_features(bos_detected=1.0, bos_direction=-1, bos_level=5000.0)
    plugin.compute_full(_make_frames(close_below, feat_bos))

    close_above = np.linspace(5000.0, 5001.0, 25)
    feat_rev = _base_features(bos_detected=0.0, hmm_regime=0.0)
    result = plugin.compute_full(_make_frames(close_above, feat_rev))

    assert result.get("direction") == 1
    supporting = result.get("supporting_factors", [])
    # Check that at least one supporting factor contains logging info about bos_level or bars_since
    assert any(
        "bos" in str(f).lower() or "bars" in str(f).lower() or "delta" in str(f).lower()
        for f in supporting
    ), f"Expected bos/bars/delta info in supporting_factors, got: {supporting}"

    # Also verify the key metrics are present as output fields or in supporting
    assert result.get("confidence", 0.0) > 0.0


def test_min_lookback_guard():
    """Returns empty dict when df has fewer rows than min_lookback."""
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    plugin = FailedBreakoutPlugin()
    close = np.array([5000.0] * 5)  # only 5 bars, min_lookback=20
    frames = _make_frames(close, _base_features())
    result = plugin.compute_full(frames)
    assert result == {}


def test_module_level_plugin_instance():
    """Module exports a plugin instance."""
    import src.intelligence.trading.failed_breakout as mod

    assert hasattr(mod, "plugin")
    from src.intelligence.trading.failed_breakout import FailedBreakoutPlugin

    assert isinstance(mod.plugin, FailedBreakoutPlugin)
