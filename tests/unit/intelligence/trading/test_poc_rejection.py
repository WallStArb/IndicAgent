"""Unit tests for trad_POCRejection I7 plugin."""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(close_arr, features=None, symbol="ES", tf="1m"):
    df = make_ohlcv(np.array(close_arr, dtype=float))
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features or {},
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


def _base_features_long(**kwargs):
    """Gate-passing features: close below poc_price within 0.3 ATR, rsi_div_bullish > 0.3."""
    defaults = {
        "atr_14": 10.0,
        "poc_price": 5000.0,
        # close will be ~4997 (below poc, within 0.3*10=3 pts)
        "rsi_div_bullish": 0.5,
        "rsi_div_bearish": 0.0,
        "stoch_k_14_3": 50.0,
        # Structural levels
        "sr_nearest_support": 4980.0,
        "sr_nearest_resistance": 5020.0,
    }
    defaults.update(kwargs)
    return defaults


def _base_features_short(**kwargs):
    """Gate-passing features: close above poc_price within 0.3 ATR, rsi_div_bearish > 0.3."""
    defaults = {
        "atr_14": 10.0,
        "poc_price": 5000.0,
        # close will be ~5003 (above poc, within 0.3*10=3 pts)
        "rsi_div_bullish": 0.0,
        "rsi_div_bearish": 0.5,
        "stoch_k_14_3": 50.0,
        "sr_nearest_support": 4980.0,
        "sr_nearest_resistance": 5020.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Test 1: fires long when below poc and rsi_div_bullish > 0.3 ─────────────


def test_fires_long_near_poc_from_below():
    """close within 0.3*ATR below poc_price + rsi_div_bullish=0.5 → direction == 1."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    # poc_price=5000, ATR=10, 0.3*ATR=3 → close must be in [4997, 5003]
    close = np.linspace(4997.5, 4998.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_long()))
    assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}"
    assert result.get("signal_type") == "poc_rejection_long"


# ─── Test 2: fires short when above poc and rsi_div_bearish > 0.3 ────────────


def test_fires_short_near_poc_from_above():
    """close within 0.3*ATR above poc_price + rsi_div_bearish=0.5 → direction == -1."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(5002.0, 5002.5, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_short()))
    assert result.get("direction") == -1, f"Expected -1, got {result.get('direction')}"
    assert result.get("signal_type") == "poc_rejection_short"


# ─── Test 3: does NOT fire when too far from POC ─────────────────────────────


def test_no_signal_when_far_from_poc():
    """close = 4990 (10 pts below poc, ATR=10 → 1.0× ATR > 0.3 threshold) → no signal."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(4990.0, 4990.5, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_long()))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 4: does NOT fire when no momentum reversal signal ──────────────────


def test_no_signal_when_no_momentum_reversal():
    """Near poc but rsi_div_bullish=0.0 and stoch_k=50 → no reversal confirmation."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(4997.5, 4998.0, 25)
    features = _base_features_long(rsi_div_bullish=0.0, stoch_k_14_3=50.0)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 5: fires with stoch_k < 30 as reversal signal ─────────────────────


def test_fires_with_stoch_oversold():
    """stoch_k=20 < 30 → oversold reversal signal → long fires near poc."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(4997.5, 4998.0, 25)
    features = _base_features_long(rsi_div_bullish=0.0, stoch_k_14_3=20.0)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 1


# ─── Test 6: regime_type is mean_reversion ───────────────────────────────────


def test_regime_type_is_mean_reversion():
    """Plugin must declare regime_type == 'mean_reversion'."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    assert plugin.regime_type == "mean_reversion"


# ─── Test 7: no signal when required fields missing ──────────────────────────


def test_no_signal_when_poc_missing():
    """Missing poc_price → returns no signal."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(4997.5, 4998.0, 25)
    result = plugin.compute_full(_make_frames(close, {}))
    assert result.get("direction") == 0


# ─── Test 8: module-level plugin instance ────────────────────────────────────


def test_plugin_module_instance():
    """Module-level `plugin` instance must have correct name."""
    from src.intelligence.archive.trading_i7.poc_rejection import plugin

    assert plugin.name == "trad_POCRejection"


# ─── Test 9: TF guard returns no_signal on 1h bars ───────────────────────────


def test_tf_guard_returns_no_signal_on_1h():
    """frames['timeframe']='1h' must return no_signal immediately (before any other logic)."""
    from src.intelligence.archive.trading_i7.poc_rejection import POCRejectionPlugin

    plugin = POCRejectionPlugin()
    close = np.linspace(4997.0, 4999.0, 25)
    frames = _make_frames(close, {"poc_price": 5000.0, "atr_14": 10.0})
    frames["timeframe"] = "1h"
    result = plugin.compute_full(frames)
    assert result == {"signal_type": "none", "direction": 0, "confidence": 0.0}
