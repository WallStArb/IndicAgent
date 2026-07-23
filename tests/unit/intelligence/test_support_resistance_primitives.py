"""Regression: inline S/R FeatureVector fields are non-constant, ATR-unit, live==batch (todo 153).

Phase 163 Plan 03 wires FeatureFactory._compute_sr_dist_atr() (stateless pivot-clustering,
ported from i3_structure/support_resistance.py) into both FeatureFactory.compute() (live)
and compute_batch() (backfill), replacing the permanently-frozen 0.0 cache-stub reads for
sr_support_dist/sr_resist_dist -- the second half of the original todo-153 bug -- and adding
5 new D-19 fields (resistance_strength, support_strength, resistance_age_bars, support_age_bars,
sr_level_count) from the same clustering pass. These tests would have caught both the original
frozen-0.0 regression and a silent D-19 omission (the 5 strength/age/count fields left null).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# Shared fixtures — single NY session, ~140 1m bars with a clear cyclical
# swing (repeated local highs/lows so pivots and clusters actually form) and
# varying volume (needed to exercise D-19's volume-weighted strength scoring).
# ---------------------------------------------------------------------------

N = 140
RNG = np.random.default_rng(16303)

# S/R FeatureVector fields shared between live compute() and batch compute_batch()
_SR_FIELDS = (
    "sr_support_dist",
    "sr_resist_dist",
    "resistance_strength",
    "support_strength",
    "resistance_age_bars",
    "support_age_bars",
    "sr_level_count",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within N bars.

    sr_window/sr_cluster_atr_mult/sr_lookback_by_tf left at dataclass defaults
    (10 / 0.5 / {"5m": 60, ...}) -- same convention as Plan 02's VP test.
    """
    defaults = dict(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=30,
        volume_zscore_window=20,
        ofi_zscore_window=20,
        cvd_slope_bars=5,
        cmf_period=20,
        vol_short_bars=5,
        vol_long_bars=20,
        hma_period=10,
        adx_period=7,
        hurst_window=30,
        garch_window=30,
        vix_zscore_window=20,
        yield_curve_zscore_window=20,
        regime_cache_refresh_bars=30,
        min_bars_warmup=5,
        cross_asset_rv_window=20,
        ny_session_start_utc_hour=13,
        ny_session_start_utc_minute=30,
        ny_session_end_utc_hour=20,
        overlap_start_utc_hour=12,
        overlap_end_utc_hour=15,
        london_kz_start_utc_hour=7,
        london_kz_end_utc_hour=10,
        power_hour_start_utc_hour=19,
        power_hour_end_utc_hour=21,
        opening_range_start_minute=810,
        opening_range_end_minute=900,
        rsi_fast_period=7,
        rsi_mid_period=14,
        rsi_slow_period=28,
        cci_fast_period=10,
        cci_mid_period=20,
        cci_slow_period=40,
        aroon_fast_period=14,
        aroon_slow_period=25,
        amihud_zscore_window=20,
        ret_skew_window=10,
        ret_skew_zscore_window=20,
        ret_acf_window=5,
        ret_acf_zscore_window=20,
        high_52w_window=20,
        ret_lag_fast=5,
        ret_lag_mid=20,
        ret_lag_slow=60,
        overnight_gap_window=20,
        dollar_vol_window=20,
        vol_range_ratio_window=20,
        vol_trend_fast=5,
        vol_trend_slow=20,
        up_vol_ratio_fast=5,
        up_vol_ratio_slow=20,
        vol_percentile_window=20,
        vol_persistence_window=20,
        vol_std_window=20,
        mfi_fast=7,
        mfi_slow=14,
        obv_window=20,
        dist_window_fast=20,
        dist_window_slow=50,
        range_window_fast=20,
        range_window_slow=50,
        stoch_window_fast=14,
        stoch_window_slow=50,
        percentile_window_fast=50,
        percentile_window_slow=200,
        efficiency_window_fast=10,
        efficiency_window_slow=50,
        ret_kurtosis_fast=10,
        ret_kurtosis_slow=40,
        ret_kurtosis_zscore_window=20,
        updown_ratio_fast=5,
        updown_ratio_slow=20,
        streak_window=20,
        realized_var_fast=5,
        realized_var_slow=20,
        vol_of_vol_window=20,
        high_low_corr_window=20,
        variance_ratio_fast=5,
        variance_ratio_slow=20,
        vol_asymmetry_window=20,
        bb_pct_b_fast=20,
        bb_pct_b_slow=50,
        hv_fast=10,
        hv_slow=30,
        hv_ratio_window=20,
        parkinson_vol_window=10,
        parkinson_vol_zscore_window=20,
        garman_klass_vol_window=10,
        garman_klass_vol_zscore_window=20,
        yang_zhang_vol_window=20,
        yang_zhang_vol_zscore_window=20,
        vol_velocity_window=20,
        intraday_noise_window=20,
        price_vol_corr_fast=10,
        price_vol_corr_slow=30,
        session_vp_rolling_window=15,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


@pytest.fixture(scope="module")
def bars() -> list[dict]:
    """~140 1m bars, single NY session, cyclical swing with repeated pivots.

    base_ts is well inside the 13:30-20:00 UTC session window (390 minutes
    available; N=140 minutes used). A sine-wave + small noise price path
    (smaller cumulative drift than the VP fixture) gives repeated local highs
    and lows so real pivot clusters form, while still varying enough across
    the sequence to exercise the non-constant regression guards. Volume
    varies per bar to exercise D-19's volume-weighted strength scoring.
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    t = np.arange(N)
    swing = np.sin(t / 10.0) * 3.0
    closes = 100.0 + swing + np.cumsum(RNG.normal(0, 0.02, N))
    spread = np.abs(RNG.normal(0.10, 0.03, N)) + 0.03
    highs = closes + spread
    lows = closes - spread
    opens = closes + RNG.normal(0, 0.03, N)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = RNG.uniform(1e4, 1e6, N)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(N)
    ]


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) S/R non-constant across bars (batch path) — direct todo-153 regression
# ---------------------------------------------------------------------------


def test_sr_non_constant_batch(bars, cfg):
    """sr_support_dist/sr_resist_dist must vary across bars, not freeze at 0.0.

    Pre-Phase-163-Plan-03, both were permanently 0.0 in both live and batch
    (read straight from an unpopulated FeatureCache stub attribute).
    """
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == N - 1  # compute_batch loop is range(1, len(bars))

    support_vals = _finite([fv.sr_support_dist for _, fv in results])
    assert len(support_vals) > 1
    assert len({round(v, 8) for v in support_vals}) > 1, "sr_support_dist is constant"
    assert any(v != 0.0 for v in support_vals), "sr_support_dist frozen at 0.0"

    resist_vals = _finite([fv.sr_resist_dist for _, fv in results])
    assert len(resist_vals) > 1
    assert len({round(v, 8) for v in resist_vals}) > 1, "sr_resist_dist is constant"
    assert any(v != 0.0 for v in resist_vals), "sr_resist_dist frozen at 0.0"


# ---------------------------------------------------------------------------
# (b) ATR-unit conversion — pins the D-02 percent -> ATR unit fix
# ---------------------------------------------------------------------------


def _build_sr_micro_case_bars() -> list[dict]:
    """Deterministic bars: constant true range so Wilder ATR converges to
    exactly 1.0, and a triangular oscillation whose peak repeats at an exact
    price so the nearest resistance cluster has an exact, hand-computable
    level. The final bar's close sits exactly 1.0 ATR (== 1.0 price unit)
    below that resistance level.

    Construction: mid(t) triangular-oscillates between 98.0 and 102.0 with a
    fixed step of 0.25/bar (period 32 bars). high = mid + 0.5, low = mid - 0.5
    (constant true range of 1.0, since consecutive mid steps of 0.25 keep the
    gap-based true-range components under the 1.0 range component). The
    sequence is truncated 14 steps into the 3rd "up" arm, where mid == 101.5
    -- exactly 1.0 below the 102.0 peak already completed earlier in the
    window (peak's high = 102.5, so (102.5 - 101.5) / 1.0 ATR == 1.0).
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    step = 0.25
    up = np.arange(0, 17) * step  # 0.0 .. 4.0 (17 points)
    down = up[1:-1][::-1]  # 3.75 .. 0.25 (15 points, no endpoint duplication)
    period = np.concatenate([up, down])  # 32 points, one full triangular cycle
    n_cycles = 5
    wave = np.tile(period, n_cycles)
    mid = 98.0 + wave  # oscillates 98.0 .. 102.0

    cut = 32 * 2 + 15  # 2 complete cycles + 14 steps into the 3rd up-arm (0-indexed)
    mid = mid[:cut]
    assert abs(mid[-1] - 101.5) < 1e-9, f"micro-case construction bug: mid[-1]={mid[-1]}"

    highs = mid + 0.5
    lows = mid - 0.5
    closes = mid.copy()
    opens = mid.copy()
    volumes = np.full(len(mid), 1_000.0)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(len(mid))
    ]


def test_sr_in_atr_units(cfg):
    """A resistance level exactly 1 ATR above close must yield sr_resist_dist == 1.0.

    Pins the D-02 fix: the archived plugin reports PERCENT distance
    ((level - close) / close * 100); this test fails if that conversion is
    ever reverted, since a percent value here would be far from 1.0
    ((102.5 - 101.5) / 101.5 * 100 ~= 0.99%, not 1.0 -- close by coincidence
    of scale here, so the ATR-unit assertion below pins the exact ATR
    formula, not just "close to 1").
    """
    micro_bars = _build_sr_micro_case_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(micro_bars, "SPY", "5m", cache, cfg)

    assert math.isfinite(fv.sr_resist_dist)
    close_ = micro_bars[-1]["close"]
    resistance_level = 102.5
    atr_val = 1.0
    expected = (resistance_level - close_) / atr_val
    assert math.isclose(fv.sr_resist_dist, expected, abs_tol=1e-6)
    assert math.isclose(fv.sr_resist_dist, 1.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# (c) live == batch parity for all 7 S/R fields
# ---------------------------------------------------------------------------


def test_sr_live_batch_parity(bars, cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    cache_live = FeatureCache()
    fv_live_last: FeatureVector | None = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _SR_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"


# ---------------------------------------------------------------------------
# (d) D-19 fields non-constant — catches the original silent-omission bug
# ---------------------------------------------------------------------------


def test_sr_d19_fields_non_constant(bars, cfg):
    """resistance_strength/support_strength/*_age_bars/sr_level_count must vary
    across bars and never be left null/constant -- the D-19 regression guard.
    """
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)

    d19_fields = (
        "resistance_strength",
        "support_strength",
        "resistance_age_bars",
        "support_age_bars",
        "sr_level_count",
    )
    for field in d19_fields:
        vals = [getattr(fv, field) for _, fv in results]
        assert all(v is not None for v in vals), f"{field} left null (D-19 omission)"
        finite_vals = _finite(vals)
        assert len(finite_vals) > 1
        assert all(v >= 0.0 for v in finite_vals), f"{field} has a negative value"
        assert len({round(v, 8) for v in finite_vals}) > 1, f"{field} is constant"
