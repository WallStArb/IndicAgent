"""Unit tests for trad_LVNBreakout I7 plugin."""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(close_arr, features=None, symbol="ES", tf="1m", open_arr=None):
    df = make_ohlcv(np.array(close_arr, dtype=float))
    if open_arr is not None:
        df["open"] = np.array(open_arr, dtype=float)
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
    """Gate-passing features for a long LVN breakout: in_lvn=1.0, trending up, high volume."""
    defaults = {
        "atr_14": 5.0,
        "in_lvn": 1.0,
        "hmm_regime": 1,  # trending up (for legacy code still reading it)
        "hmm_prob_trending_up": 0.75,  # continuous regime gate (>= 0.30)
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
        "rel_volume": 2.0,  # > 1.5 threshold
        "nearest_hvn_above": 5015.0,  # T1 target
        "nearest_hvn_below": 4985.0,
        "nearest_lvn_above": 5005.0,
        "nearest_lvn_below": 4995.0,
        "sr_nearest_resistance": 5020.0,
        "sr_nearest_support": 4980.0,
    }
    defaults.update(kwargs)
    return defaults


def _base_features_short(**kwargs):
    """Gate-passing features for a short LVN breakout: in_lvn=1.0, trending down, high volume."""
    defaults = {
        "atr_14": 5.0,
        "in_lvn": 1.0,
        "hmm_regime": 2,  # trending down (for legacy code still reading it)
        "hmm_prob_trending_up": 0.10,
        "hmm_prob_trending_down": 0.75,  # continuous regime gate (>= 0.30)
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
        "rel_volume": 2.0,  # > 1.5 threshold
        "nearest_hvn_above": 5015.0,
        "nearest_hvn_below": 4985.0,  # T1 target for short
        "nearest_lvn_above": 5005.0,
        "nearest_lvn_below": 4995.0,
        "sr_nearest_resistance": 5020.0,
        "sr_nearest_support": 4980.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Test 1: fires long when in_lvn=1.0, vol>=1.5, trending up, up bar ───────


def test_fires_long_in_lvn_trending_up():
    """in_lvn=1.0, hmm_regime=1, rel_volume=2.0, close > open → long breakout."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    # Upward bar: close > open
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_long(), open_arr=open_arr))
    assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}"
    assert result.get("signal_type") == "lvn_breakout_long"


# ─── Test 2: fires short when in_lvn=1.0, vol>=1.5, trending down, down bar ─


def test_fires_short_in_lvn_trending_down():
    """in_lvn=1.0, hmm_regime=2, rel_volume=2.0, close < open → short breakout."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    # Downward bar: close < open
    open_arr = np.full(25, 5001.0)
    close = np.linspace(5000.5, 4999.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_short(), open_arr=open_arr))
    assert result.get("direction") == -1, f"Expected -1, got {result.get('direction')}"
    assert result.get("signal_type") == "lvn_breakout_short"


# ─── Test 3: does NOT fire when in_lvn != 1.0 ────────────────────────────────


def test_no_signal_when_not_in_lvn():
    """in_lvn=0.0 → not in LVN → no signal."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    features = _base_features_long(in_lvn=0.0)
    result = plugin.compute_full(_make_frames(close, features, open_arr=open_arr))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 4: does NOT fire when rel_volume < 1.5 ─────────────────────────────


def test_no_signal_when_volume_insufficient():
    """rel_volume=1.0 < 1.5 → insufficient volume expansion → no signal."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    features = _base_features_long(rel_volume=1.0)
    result = plugin.compute_full(_make_frames(close, features, open_arr=open_arr))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 5: does NOT fire when hmm_regime == 0 (ranging) ───────────────────


@pytest.mark.skip(reason="HMM regime gate removed (ECL boundary violation fix)")
def test_no_signal_when_ranging_regime():
    """hmm_prob_trending_up and _down both low → not trending → no signal."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    features = _base_features_long(
        hmm_regime=0,
        hmm_prob_trending_up=0.10,
        hmm_prob_trending_down=0.10,
    )
    result = plugin.compute_full(_make_frames(close, features, open_arr=open_arr))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 6: T1 target is nearest_hvn_above for long ────────────────────────


def test_first_target_is_nearest_hvn_above_for_long():
    """For long LVN breakout, first target should be nearest_hvn_above (5015.0)."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features_long(), open_arr=open_arr))
    if result.get("direction") == 1:
        targets = result.get("targets", [])
        assert len(targets) >= 1, "Expected at least one target"
        # T1 should be near nearest_hvn_above (5015.0)
        assert targets[0] == pytest.approx(5015.0, abs=2.0), f"Expected T1 ~5015, got {targets[0]}"


# ─── Test 7: regime_type is "trend" ──────────────────────────────────────────


def test_regime_type_is_trend():
    """Plugin must declare regime_type == 'trend'."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    assert plugin.regime_type == "trend"


# ─── Test 8: no signal when in_lvn field missing ─────────────────────────────


def test_no_signal_when_in_lvn_missing():
    """Missing in_lvn field → returns no signal."""
    from src.intelligence.archive.trading_i7.lvn_breakout import LVNBreakoutPlugin

    plugin = LVNBreakoutPlugin()
    open_arr = np.full(25, 5000.0)
    close = np.linspace(5000.5, 5002.0, 25)
    result = plugin.compute_full(_make_frames(close, {"atr_14": 5.0}, open_arr=open_arr))
    assert result.get("direction") == 0


# ─── Test 9: module-level plugin instance ────────────────────────────────────


def test_plugin_module_instance():
    """Module-level `plugin` instance must have correct name."""
    from src.intelligence.archive.trading_i7.lvn_breakout import plugin

    assert plugin.name == "trad_LVNBreakout"
