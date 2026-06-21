"""Unit tests for trad_HVNRejection I7 plugin."""

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


def _base_features(**kwargs):
    defaults = {
        "atr_14": 10.0,
        "nearest_hvn_above": 5010.0,
        "nearest_hvn_below": 4990.0,
        "nearest_hvn_dist_atr": 1.0,
        "rsi_div_bullish": 0.0,
        "rsi_div_bearish": 0.0,
        "stoch_k_14_3": 50.0,
        "sr_nearest_support": 4970.0,
        "sr_nearest_resistance": 5030.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Test 1: fires long near nearest_hvn_below with bullish reversal ─────────


def test_fires_long_near_hvn_below():
    """close within 0.3*ATR of nearest_hvn_below + rsi_div_bullish > 0.3 → long signal."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    # hvn_below=4990, ATR=10, 0.3*ATR=3 → close near 4991 (above hvn_below, approaching)
    close = np.linspace(4991.0, 4991.5, 25)
    features = _base_features(rsi_div_bullish=0.5)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}"
    assert result.get("signal_type") == "hvn_rejection_long"


# ─── Test 2: fires short near nearest_hvn_above with bearish reversal ────────


def test_fires_short_near_hvn_above():
    """close within 0.3*ATR of nearest_hvn_above + rsi_div_bearish > 0.3 → short signal."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    # hvn_above=5010, ATR=10, 0.3*ATR=3 → close near 5009 (below hvn_above, approaching)
    close = np.linspace(5009.0, 5009.5, 25)
    features = _base_features(rsi_div_bearish=0.5)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == -1, f"Expected -1, got {result.get('direction')}"
    assert result.get("signal_type") == "hvn_rejection_short"


# ─── Test 3: does NOT fire when not near any HVN ─────────────────────────────


def test_no_signal_when_not_near_hvn():
    """close = 5000 (10 pts from both hvn_above and hvn_below → 1× ATR > 0.3)."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    close = np.linspace(5000.0, 5000.5, 25)
    features = _base_features(rsi_div_bullish=0.5, rsi_div_bearish=0.5)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 4: does NOT fire when near HVN but no momentum reversal ─────────────


def test_no_signal_when_no_reversal_at_hvn():
    """Near hvn_below but no reversal confirmation (rsi_div=0, stoch_k=50)."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    close = np.linspace(4991.0, 4991.5, 25)
    features = _base_features(rsi_div_bullish=0.0, stoch_k_14_3=50.0)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 5: stoch_k < 30 triggers long at hvn_below ────────────────────────


def test_fires_long_with_stoch_oversold_at_hvn():
    """stoch_k=15 < 30 → oversold at HVN below → long fires."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    close = np.linspace(4991.0, 4991.5, 25)
    features = _base_features(stoch_k_14_3=15.0)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 1


# ─── Test 6: regime_type is mean_reversion ───────────────────────────────────


def test_regime_type_is_mean_reversion():
    """Plugin must declare regime_type == 'mean_reversion'."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    assert plugin.regime_type == "mean_reversion"


# ─── Test 7: no signal when hvn fields are missing ───────────────────────────


def test_no_signal_when_hvn_fields_missing():
    """No nearest_hvn_above or nearest_hvn_below → no signal."""
    from src.intelligence.archive.trading_i7.hvn_rejection import HVNRejectionPlugin

    plugin = HVNRejectionPlugin()
    close = np.linspace(4991.0, 4991.5, 25)
    result = plugin.compute_full(_make_frames(close, {"atr_14": 10.0}))
    assert result.get("direction") == 0


# ─── Test 8: module-level plugin instance ────────────────────────────────────


def test_plugin_module_instance():
    """Module-level `plugin` instance must have correct name."""
    from src.intelligence.archive.trading_i7.hvn_rejection import plugin

    assert plugin.name == "trad_HVNRejection"
