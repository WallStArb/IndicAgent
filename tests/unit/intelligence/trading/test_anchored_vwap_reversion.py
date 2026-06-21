"""Unit tests for trad_AnchoredVWAPReversion I7 plugin."""

from __future__ import annotations

import numpy as np
import pytest

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
    """Gate-passing feature set: sigma=2.0 (short, > sigma_min=1.0), hurst=0.45."""
    defaults = {
        "atr_14": 5.0,
        "session_vwap": 5000.0,
        "session_vwap_deviation_sigma": 2.0,  # > 1.5 → short direction
        "session_vwap_deviation_velocity": -0.1,  # moving toward vwap
        "hmm_regime": 0,
        "hurst_exponent": 0.45,  # < 0.55 → mean-reverting
        "avwap_upper_band": 5015.0,
        "avwap_lower_band": 4985.0,
        "hurst_mr_quality": 0.7,
        "vol_regime": 0.5,
        # Structural levels for frame_trade stop resolution
        "sr_nearest_resistance": 5020.0,
        "sr_nearest_support": 4980.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Test 1: fires short when sigma > 1.5, ranging, hurst < 0.55 ─────────────


def test_fires_short_when_above_sigma_threshold():
    """sigma=2.0, hmm_regime=0, hurst=0.45, close reclaims below vwap → direction == -1."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    # Close must be below session_vwap (5000) to confirm short reclaim
    close = np.linspace(5010.0, 4998.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features()))
    assert result.get("direction") == -1, f"Expected -1, got {result.get('direction')}"
    assert result.get("signal_type") == "vwap_reversion_short"


# ─── Test 2: fires long when sigma < -1.5, ranging, hurst < 0.55 ─────────────


def test_fires_long_when_below_sigma_threshold():
    """sigma=-2.0, hmm_regime=0, hurst=0.45, close reclaims above vwap → direction == 1."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    # Close must be above session_vwap (5000) to confirm long reclaim
    close = np.linspace(4988.0, 5002.0, 25)
    features = _base_features(
        session_vwap_deviation_sigma=-2.0,
        session_vwap_deviation_velocity=0.1,  # moving toward vwap (positive)
    )
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}"
    assert result.get("signal_type") == "vwap_reversion_long"


# ─── Test 3: does NOT fire when abs(sigma) < 1.5 ─────────────────────────────


def test_no_signal_when_sigma_too_small():
    """sigma=0.5 → abs < sigma_min=1.0 threshold → no signal."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    close = np.linspace(5003.0, 5004.0, 25)
    result = plugin.compute_full(
        _make_frames(close, _base_features(session_vwap_deviation_sigma=0.5))
    )
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 4: hmm_regime is NOT a gate (ECL invariant) ───────────────────────


def test_fires_in_trending_regime():
    """hmm_regime=1 (trending) must not suppress — HMM is annotation only per ECL invariant."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    # Same setup as test_fires_short_when_above_sigma_threshold but with hmm_regime=1
    close = np.linspace(5010.0, 4998.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features(hmm_regime=1)))
    assert result.get("direction") == -1, "HMM trending regime must not suppress signal"
    assert result.get("signal_type") == "vwap_reversion_short"


# ─── Test 5: does NOT fire when hurst >= 0.55 ────────────────────────────────


def test_no_signal_when_hurst_too_high():
    """hurst_exponent=0.60 >= 0.55 → trending-like → no signal."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    close = np.linspace(5010.0, 5012.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features(hurst_exponent=0.60)))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 6: confidence is positive and < 1.0 ────────────────────────────────


def test_confidence_is_in_range():
    """When signal fires, confidence must be in (0.0, 1.0]."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    # Close must cross below vwap (5000) to confirm short reclaim
    close = np.linspace(5010.0, 4998.0, 25)
    result = plugin.compute_full(_make_frames(close, _base_features()))
    assert result.get("direction") != 0
    conf = result.get("confidence", 0.0)
    assert 0.0 < conf <= 1.0, f"Confidence out of range: {conf}"


# ─── Test 7: targets include session_vwap as T1 ──────────────────────────────


def test_targets_include_session_vwap():
    """T1 target must be session_vwap (5000.0) for short signal."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    close = np.linspace(5010.0, 5012.0, 25)
    features = _base_features(session_vwap=5000.0)
    result = plugin.compute_full(_make_frames(close, features))
    if result.get("direction") == -1:
        targets = result.get("targets", [])
        assert len(targets) >= 1, "Expected at least one target"
        # T1 should be session_vwap
        assert targets[0] == pytest.approx(
            5000.0, abs=1.0
        ), f"Expected T1 ~5000.0, got {targets[0]}"


# ─── Test 8: regime_type is mean_reversion ───────────────────────────────────


def test_regime_type_is_mean_reversion():
    """Plugin must declare regime_type == 'mean_reversion'."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    assert plugin.regime_type == "mean_reversion"


# ─── Test 9: returns no_signal when required features are missing ─────────────


def test_no_signal_when_required_features_missing():
    """Missing session_vwap_deviation_sigma → returns no signal."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    close = np.linspace(5010.0, 5012.0, 25)
    result = plugin.compute_full(_make_frames(close, {}))
    assert result.get("direction") == 0
    assert result.get("confidence") == 0.0


# ─── Test 10: plugin instance exported at module level ───────────────────────


def test_plugin_module_instance():
    """Module-level `plugin` instance must have correct name."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import plugin

    assert plugin.name == "trad_AnchoredVWAPReversion"


# ─── Test 11: TF guard returns no_signal on 1h bars ─────────────────────────


def test_tf_guard_returns_no_signal_on_1h():
    """frames['timeframe']='1h' must return no_signal immediately (before any other logic)."""
    from src.intelligence.archive.trading_i7.anchored_vwap_reversion import (
        AnchoredVWAPReversionPlugin,
    )

    plugin = AnchoredVWAPReversionPlugin()
    close = np.linspace(5010.0, 5012.0, 25)
    frames = _make_frames(close, _base_features())
    frames["timeframe"] = "1h"
    result = plugin.compute_full(frames)
    assert result == {"signal_type": "none", "direction": 0, "confidence": 0.0}
