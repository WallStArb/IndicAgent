"""The block-vectorized bounded-window and bar-statistics kernels equal the per-row loops they
replaced, bit for bit, across NaN, untraded slots, ties and periods longer than the window."""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.features.kernels import price
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels.price import (
    _aroon_osc,
    _cci,
    _compute_bar_statistics_refresh,
    _compute_bounded_window_scalars,
    _range_position,
    _vol_ratio,
)
from tests.unit.intelligence import kernel_parity_reference as ref


def _reference_bounded(x, config):
    h, lo, c = x["high"], x["low"], x["close"]
    window = max(
        config.cci_slow_period, config.aroon_slow_period, config.vol_long_bars, config.cmf_period
    )
    out = {
        k: np.empty(len(c))
        for k in (
            "range_position",
            "vol_ratio",
            "cci_fast",
            "cci_mid",
            "cci_slow",
            "aroon_fast",
            "aroon_slow",
        )
    }
    for i in range(len(c)):
        start = max(0, i - window)
        w_h, w_l, w_c = h[start : i + 1], lo[start : i + 1], c[start : i + 1]
        rb = min(config.momentum_window_mid, i + 1 - start)
        out["range_position"][i] = _range_position(float(c[i]), w_h[-rb:], w_l[-rb:])
        out["vol_ratio"][i] = _vol_ratio(w_c, config.vol_short_bars, config.vol_long_bars)
        out["cci_fast"][i] = _cci(w_h, w_l, w_c, config.cci_fast_period)
        out["cci_mid"][i] = _cci(w_h, w_l, w_c, config.cci_mid_period)
        out["cci_slow"][i] = _cci(w_h, w_l, w_c, config.cci_slow_period)
        out["aroon_fast"][i] = _aroon_osc(w_h, w_l, config.aroon_fast_period)
        out["aroon_slow"][i] = _aroon_osc(w_h, w_l, config.aroon_slow_period)
    return out


def _bars(seed: int, n: int, kind: str):
    rng = np.random.default_rng(seed)
    c = np.cumprod(1.0 + rng.normal(0, 0.01, n)) * 50.0
    h, lo = c * 1.004, c * 0.996
    o = c
    if kind == "ties":
        c, h, lo = np.round(c, 0), np.round(h, 0), np.round(lo, 0)
    if kind == "flat":
        c = h = lo = np.full(n, 12.5)
    if kind == "nan":
        for arr in (c, h, lo):
            arr[rng.choice(n, max(n // 25, 1), replace=False)] = np.nan
    del o
    return {"high": h, "low": lo, "close": c}


CONFIGS = {
    "default": SimpleNamespace(
        momentum_window_mid=20,
        vol_short_bars=5,
        vol_long_bars=20,
        cci_fast_period=7,
        cci_mid_period=14,
        cci_slow_period=30,
        aroon_fast_period=10,
        aroon_slow_period=25,
        cmf_period=20,
    ),
    "long_periods": SimpleNamespace(  # cci_mid and aroon_fast exceed the bounded window
        momentum_window_mid=200,
        vol_short_bars=40,
        vol_long_bars=8,
        cci_fast_period=3,
        cci_mid_period=300,
        cci_slow_period=9,
        aroon_fast_period=64,
        aroon_slow_period=12,
        cmf_period=6,
    ),
    "wide": SimpleNamespace(  # windows of 130+ rows exercise numpy's blocked pairwise sum
        momentum_window_mid=50,
        vol_short_bars=30,
        vol_long_bars=140,
        cci_fast_period=20,
        cci_mid_period=64,
        cci_slow_period=150,
        aroon_fast_period=50,
        aroon_slow_period=100,
        cmf_period=40,
    ),
}


@pytest.mark.parametrize("block", [None, 7, 1])
@pytest.mark.parametrize("kind", ["normal", "ties", "flat", "nan"])
@pytest.mark.parametrize("config_name", list(CONFIGS))
def test_bounded_window_scalars_equality(config_name, kind, block, monkeypatch):
    if block is not None:
        monkeypatch.setattr(price, "_block_rows", lambda n_windows: block)
    config = CONFIGS[config_name]
    for seed, n in ((1, 400), (2, 37), (3, 2)):
        x = _bars(seed, n, kind)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            want = _reference_bounded(x, config)
            got = _compute_bounded_window_scalars(x, config)
        for name, w in want.items():
            assert got[name].dtype == w.dtype and got[name].tobytes() == w.tobytes(), (
                config_name,
                kind,
                seed,
                name,
            )


def test_bounded_window_scalars_empty():
    x = {k: np.zeros(0) for k in ("high", "low", "close")}
    got = _compute_bounded_window_scalars(x, CONFIGS["default"])
    assert all(len(v) == 0 for v in got.values())


def _reference_bar_statistics(x, config):
    o, h, lo, c, v = (x[f].tolist() for f in ("open", "high", "low", "close", "volume"))
    bars = [
        {"open": o[i], "high": h[i], "low": lo[i], "close": c[i], "volume": v[i]}
        for i in range(len(c))
    ]
    cache = FeatureCache()
    out = {name: np.empty(len(bars)) for name in price._BAR_STATISTICS}
    for i in range(len(bars)):
        if i >= 1 and i % config.regime_cache_refresh_bars == 0:
            cache.refresh_regime(bars[max(0, i - config.hurst_window) : i + 1], config)
        for name in price._BAR_STATISTICS:
            out[name][i] = getattr(cache, name)
    return out


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
@pytest.mark.parametrize("n", [1, 25, 31, 400])
def test_bar_statistics_refresh_equality(config_key, n):
    from tests.unit.intelligence.test_feature_kernels import MANIFEST, synthetic_bars

    config = ref.build_config(MANIFEST[config_key])
    x = synthetic_bars(n, 5)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        want = _reference_bar_statistics(x, config)
        got = _compute_bar_statistics_refresh(x, config)
    for name, w in want.items():
        assert got[name].tobytes() == w.tobytes(), (config_key, n, name)
