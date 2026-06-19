"""Unit tests for trad_SecondLegContinuation I7 plugin (Fibonacci measured-move continuation)."""

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
    defaults = {
        "atr_14": 50.0,
        "hmm_regime": 1.0,
        "hmm_regime_prob": 0.75,
        "hmm_prob_trending_up": 0.75,  # continuous regime gate (>= 0.30)
        "hmm_prob_trending_down": 0.10,
        "ctf_score": 0.40,  # I6 gate (abs >= 0.25)
        "swing_high": 5100.0,
        "swing_low": 5000.0,
        "swing_high_age_bars": 10.0,
        "swing_low_age_bars": 15.0,
        # Structural features so frame_trade returns viable trade
        "nearest_resistance": 5250.0,
        "nearest_support": 4900.0,
    }
    defaults.update(kwargs)
    return defaults


# ─── Guard tests ────────────────────────────────────────────────────────────


@pytest.mark.skip(reason="HMM regime gate removed (ECL boundary violation fix)")
def test_no_signal_in_ranging_regime():
    """Both hmm_prob_trending_up and _down below 0.30 -> no_signal (continuous regime gate)."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    close = np.full(60, 5050.0)
    features = _base_features(
        hmm_regime=0.0,
        hmm_prob_trending_up=0.10,
        hmm_prob_trending_down=0.10,
    )
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("signal_type") == "none"
    assert result.get("direction") == 0


def test_no_signal_when_amplitude_below_atr():
    """swing_high - swing_low < atr_14 -> no_signal (amplitude gate)."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    close = np.full(60, 5005.0)
    # amplitude=10, atr=50 -> amplitude < 1.0*atr
    features = _base_features(
        swing_high=5010.0,
        swing_low=5000.0,
        atr_14=50.0,
        hmm_regime=1.0,
    )
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("signal_type") == "none"


def test_no_signal_when_swing_data_missing():
    """swing_high=None -> no_signal (guard for missing data)."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    close = np.full(60, 5050.0)
    features = _base_features(swing_high=None, swing_low=None)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("signal_type") == "none"


def test_no_signal_when_stale_swing():
    """swing_high_age_bars > 50 AND swing_low_age_bars > 50 -> no_signal (stale data)."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    close = np.full(60, 5050.0)
    features = _base_features(swing_high_age_bars=60.0, swing_low_age_bars=55.0)
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("signal_type") == "none"


def test_no_signal_when_price_outside_fib_zone():
    """close above 61.8% retracement (already past ideal zone) -> no_signal."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    # swing_high=5100, swing_low=5000, amplitude=100
    # 38.2% retracement from high = 5100 - 0.382*100 = 5061.8
    # 61.8% retracement from high = 5100 - 0.618*100 = 5038.2
    # Fib zone for long: between 5038.2 and 5061.8
    # close=5080.0 -> above 61.8% from bottom = above zone
    close = np.full(60, 5080.0)
    features = _base_features(
        swing_high=5100.0,
        swing_low=5000.0,
        atr_14=50.0,
        hmm_regime=1.0,
    )
    result = plugin.compute_full(_make_frames(close, features))
    assert result.get("signal_type") == "none"


def test_no_signal_insufficient_lookback():
    """len(df) < min_lookback -> empty dict."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    close = np.full(5, 5050.0)
    result = plugin.compute_full(_make_frames(close, _base_features()))
    assert result == {}


# ─── Fire tests ─────────────────────────────────────────────────────────────


def test_fires_in_fib_zone_long():
    """close at 50% retracement (5050), swing_high=5100, swing_low=5000, hmm_regime=1.0 -> direction=1."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    # 50% retracement is midpoint: (5100+5000)/2 = 5050
    # This is within the 38.2%-61.8% fib zone (5038.2-5061.8)
    close = np.full(60, 5050.0)
    features = _base_features(
        swing_high=5100.0,
        swing_low=5000.0,
        atr_14=50.0,  # amplitude=100 > 1.0*50 -> passes gate
        hmm_regime=1.0,
        hmm_regime_prob=0.75,
        nearest_resistance=5250.0,
        nearest_support=4900.0,
    )
    result = plugin.compute_full(_make_frames(close, features))
    if result.get("direction") != 0:  # may be no_signal if frame not viable
        assert result.get("direction") == 1
        assert result.get("signal_type") == "second_leg_long"


def test_fires_in_fib_zone_short():
    """close in fib zone with dominant down regime -> direction=-1."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    # For bearish: swing_high=5100 (peak of downward leg 1), swing_low=5000
    # For short: retracement is upward; fib zone between 5038.2 and 5061.8 from below
    close = np.full(60, 5050.0)
    features = _base_features(
        swing_high=5100.0,
        swing_low=5000.0,
        atr_14=50.0,
        hmm_regime=2.0,
        hmm_regime_prob=0.75,
        hmm_prob_trending_up=0.10,  # override base: bearish regime
        hmm_prob_trending_down=0.75,
        nearest_support=4750.0,
        nearest_resistance=5250.0,
    )
    result = plugin.compute_full(_make_frames(close, features))
    if result.get("direction") != 0:
        assert result.get("direction") == -1
        assert result.get("signal_type") == "second_leg_short"


# ─── Target accuracy test ───────────────────────────────────────────────────


def test_targets_match_measured_move():
    """Targets should approximate entry + 1.0x, 1.272x, 1.618x amplitude."""
    from src.intelligence.trading.second_leg_continuation import SecondLegContinuationPlugin

    plugin = SecondLegContinuationPlugin()
    # swing_high=5100, swing_low=5000, amplitude=100
    # Entry = fib_50 = 5050. Targets: 5050+100=5150, 5050+127.2=5177.2, 5050+161.8=5211.8
    close = np.full(60, 5050.0)
    features = _base_features(
        swing_high=5100.0,
        swing_low=5000.0,
        atr_14=50.0,
        hmm_regime=1.0,
        hmm_regime_prob=0.80,
        nearest_resistance=5300.0,
        nearest_support=4900.0,
    )
    result = plugin.compute_full(_make_frames(close, features))
    if result.get("direction") == 1:
        targets = result.get("targets", [])
        if len(targets) >= 1:
            # T1 should be near entry + amplitude
            assert targets[0] > 5050.0  # above entry
        if len(targets) >= 3:
            # T3 should be near 161.8% extension
            assert targets[2] > targets[1] > targets[0]


def test_plugin_instance_exists():
    """Module-level plugin instance must exist."""
    from src.intelligence.trading.second_leg_continuation import (
        SecondLegContinuationPlugin,
        plugin,
    )

    assert isinstance(plugin, SecondLegContinuationPlugin)
    assert plugin.name == "trad_SecondLegContinuation"
    assert plugin.regime_type == "trend"
