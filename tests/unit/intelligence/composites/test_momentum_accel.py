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
    from src.intelligence.register_plugins import TIER_I2
    from src.intelligence.composites.momentum_accel import plugin
    assert plugin.name in TIER_I2
