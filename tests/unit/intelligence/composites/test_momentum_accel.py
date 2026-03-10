# tests/unit/intelligence/composites/test_momentum_accel.py
from __future__ import annotations

import pytest

from src.intelligence.composites.momentum_accel import MomentumAccelPlugin


def make_frames(
    rsi=None, macd=None, roc=None,
    prev_rsi=None, prev_macd=None, prev_roc=None,
) -> dict:
    features = {}
    prev = {}
    if rsi is not None:
        features["rsi_14"] = rsi
    if macd is not None:
        features["macd_12_26_9"] = macd
    if roc is not None:
        features["roc_14"] = roc
    if prev_rsi is not None:
        prev["rsi_14"] = prev_rsi
    if prev_macd is not None:
        prev["macd_12_26_9"] = prev_macd
    if prev_roc is not None:
        prev["roc_14"] = prev_roc
    return {"features": features, "prev_features": prev}


def test_missing_prev_returns_zeros():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next({
        "features": {"rsi_14": 50.0, "macd_12_26_9": 0.5, "roc_14": 1.0},
        "prev_features": {},
    })
    assert result["rsi_accel"] == 0.0
    assert result["macd_accel"] == 0.0
    assert result["roc_accel"] == 0.0
    assert result["inflection_flag"] == 0


def test_rsi_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["rsi_accel"] == pytest.approx(5.0)


def test_macd_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.8, roc=0.0,
        prev_rsi=50.0, prev_macd=0.5, prev_roc=0.0,
    ))
    assert result["macd_accel"] == pytest.approx(0.3)


def test_roc_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=2.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=3.0,
    ))
    assert result["roc_accel"] == pytest.approx(-1.0)


def test_inflection_flag_zero_on_first_bar():
    """First bar: deltas exist but no prior delta in state yet — flag must be 0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.5, roc=1.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=0.5,
    ))
    assert result["inflection_flag"] == 0


def test_inflection_flag_fires_on_rsi_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: rsi_accel = +5.0 → stored in state
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    # Bar 2: rsi_accel = -2.0 → sign change
    result = plugin.compute_next(make_frames(
        rsi=53.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_fires_on_macd_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: macd_accel = +0.2
    plugin.compute_next(make_frames(
        rsi=50.0, macd=0.5, roc=0.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=0.0,
    ))
    # Bar 2: macd_accel = -0.1 → sign change
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.4, roc=0.0,
        prev_rsi=50.0, prev_macd=0.5, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_fires_on_roc_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: roc_accel = +1.0
    plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=2.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=1.0,
    ))
    # Bar 2: roc_accel = -0.5 → sign change
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=1.5,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=2.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_zero_when_no_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: all positive accels
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.5, roc=2.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=1.0,
    ))
    # Bar 2: all still positive
    result = plugin.compute_next(make_frames(
        rsi=58.0, macd=0.7, roc=3.5,
        prev_rsi=55.0, prev_macd=0.5, prev_roc=2.0,
    ))
    assert result["inflection_flag"] == 0


def test_inflection_flag_zero_when_delta_reaches_zero():
    """prev_accel * 0 = 0, which is not < 0 → no inflection."""
    plugin = MomentumAccelPlugin()
    # Bar 1: rsi_accel = +5.0
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    # Bar 2: rsi_accel = 0.0 (flat)
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 0


def test_state_persists_across_multiple_calls():
    """Three bars: up, up, down → inflection only on the third bar."""
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames(
        rsi=52.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = +2
    r2 = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=52.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = +3, same sign → no inflection
    assert r2["inflection_flag"] == 0
    r3 = plugin.compute_next(make_frames(
        rsi=53.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = -2, sign change → inflection
    assert r3["inflection_flag"] == 1


def test_plugin_registered_in_tier_i2():
    from src.intelligence.composites.momentum_accel import plugin
    from src.intelligence.register_plugins import TIER_I2
    assert plugin.name in TIER_I2


# ─── Phase 24 RED stubs: new outputs (rsi_curvature, macd_hist_slope,
#     price_accel, hma_slope, hma_accel) ─────────────────────────────────────
#
# These tests MUST FAIL until Plan 02 implements the new outputs.


def make_frames_extended(
    rsi=None, macd_hist=None, atr=None, hma_20_val=None,
    prev_rsi_accel=None, prev_macd_hist=None, prev_hma_20_val=None,
    close_prices=None,
) -> dict:
    """Build frames dict for extended MomentumAccelPlugin tests.

    State-based outputs (macd_hist_slope, hma_slope, hma_accel) are driven
    by the plugin's internal _state, not by prev_features.  We inject state
    values directly on the plugin instance in tests that need prior-bar state.
    """
    features: dict = {}
    prev: dict = {}
    if rsi is not None:
        features["rsi_14"] = rsi
    if macd_hist is not None:
        features["macd_histogram_12_26_9"] = macd_hist
    if atr is not None:
        features["atr_14"] = atr
    if hma_20_val is not None:
        features["hma_20"] = hma_20_val
    if prev_rsi_accel is not None:
        prev["rsi_accel"] = prev_rsi_accel
    if prev_macd_hist is not None:
        prev["macd_histogram_12_26_9"] = prev_macd_hist
    if prev_hma_20_val is not None:
        prev["hma_20"] = prev_hma_20_val

    main_df = None
    if close_prices is not None:
        import numpy as np
        import pandas as pd
        c = np.array(close_prices, dtype=float)
        spread = np.abs(c) * 0.002
        main_df = pd.DataFrame({
            "open": c, "high": c + spread, "low": c - spread, "close": c,
            "volume": np.ones(len(c)) * 1000.0,
        })

    return {"features": features, "prev_features": prev, "main": main_df}


# ── new outputs in frozenset ──────────────────────────────────────────────────


def test_new_output_keys_in_plugin_outputs():
    """All new output keys must appear in plugin.outputs frozenset."""
    plugin = MomentumAccelPlugin()
    for key in ("rsi_curvature", "macd_hist_slope", "price_accel", "hma_slope", "hma_accel"):
        assert key in plugin.outputs, f"Missing output key: {key}"


# ── rsi_curvature ─────────────────────────────────────────────────────────────


def test_rsi_curvature_zero_on_first_bar():
    """No prev_rsi_accel in state → rsi_curvature must be 0.0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_extended(rsi=55.0))
    assert result["rsi_curvature"] == 0.0


def test_rsi_curvature_computed_on_second_bar():
    """rsi_curvature = accel[bar2] - accel[bar1].

    Bar1: rsi goes 50→55, accel=+5.
    Bar2: rsi goes 55→57, accel=+2. curvature = 2 - 5 = -3.
    """
    plugin = MomentumAccelPlugin()
    # bar 1 — sets prev_rsi_accel = +5 in state (via rsi_accel path)
    plugin.compute_next(make_frames(rsi=55.0, macd=0.0, roc=0.0,
                                    prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0))
    # bar 2 — rsi_accel = 57-55 = +2; curvature = 2 - 5 = -3
    result = plugin.compute_next(make_frames(rsi=57.0, macd=0.0, roc=0.0,
                                             prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0))
    assert result["rsi_curvature"] == pytest.approx(-3.0)


# ── macd_hist_slope ───────────────────────────────────────────────────────────


def test_macd_hist_slope_zero_on_first_bar():
    """No prior macd_histogram value in state → macd_hist_slope = 0.0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_extended(macd_hist=0.5))
    assert result["macd_hist_slope"] == 0.0


def test_macd_hist_slope_reads_state_not_prev_features():
    """macd_hist_slope = current_histogram - state['prev_macd_hist'].

    Inject state directly: prev=0.3, current=0.2 → slope = -0.1.
    """
    plugin = MomentumAccelPlugin()
    plugin._state["prev_macd_hist"] = 0.3
    result = plugin.compute_next(make_frames_extended(macd_hist=0.2))
    assert result["macd_hist_slope"] == pytest.approx(-0.1)


# ── price_accel ───────────────────────────────────────────────────────────────


def test_price_accel_zero_when_atr_missing():
    """price_accel must be 0.0 when atr_14 is absent from features."""
    plugin = MomentumAccelPlugin()
    closes = [5000.0, 5001.0, 5003.0, 5006.0, 5010.0]
    result = plugin.compute_next(make_frames_extended(close_prices=closes))
    assert result["price_accel"] == 0.0


def test_price_accel_computed_correctly():
    """price_accel = (velocity_now - velocity_prev) / atr.

    closes=[5000,5001,5003,5006,5010], atr=8.
    velocity_prev = 5003-5001=2, velocity_now = 5010-5006=4.
    price_accel = (4-2)/8 = 0.25.
    """
    plugin = MomentumAccelPlugin()
    closes = [5000.0, 5001.0, 5003.0, 5006.0, 5010.0]
    result = plugin.compute_next(make_frames_extended(atr=8.0, close_prices=closes))
    assert result["price_accel"] == pytest.approx(0.25)


# ── hma_slope ────────────────────────────────────────────────────────────────


def test_hma_slope_zero_on_first_bar():
    """No hma_20 in features → hma_slope = 0.0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_extended())
    assert result["hma_slope"] == 0.0


def test_hma_slope_state_tracked():
    """hma_slope = hma_20[t] - hma_20[t-1] (state-based, not from prev_features).

    Bar 1: hma_20=100 → slope stored = 0 (no prior).
    Bar 2: hma_20=103 → slope = 103 - 100 = 3.
    """
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames_extended(hma_20_val=100.0))
    result = plugin.compute_next(make_frames_extended(hma_20_val=103.0))
    assert result["hma_slope"] == pytest.approx(3.0)


# ── hma_accel ────────────────────────────────────────────────────────────────


def test_hma_accel_zero_on_first_bar():
    """No prior hma_slope in state → hma_accel = 0.0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_extended(hma_20_val=100.0))
    assert result["hma_accel"] == 0.0


def test_hma_accel_computed_on_second_slope_bar():
    """hma_accel = hma_slope[t] - hma_slope[t-1].

    Bar 1: hma_20=100 → slope=0 (first bar, no accel).
    Bar 2: hma_20=103 → slope=3, accel=3-0=3.
    Bar 3: hma_20=104 → slope=1, accel=1-3=-2.
    """
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames_extended(hma_20_val=100.0))
    plugin.compute_next(make_frames_extended(hma_20_val=103.0))
    result = plugin.compute_next(make_frames_extended(hma_20_val=104.0))
    assert result["hma_accel"] == pytest.approx(-2.0)
