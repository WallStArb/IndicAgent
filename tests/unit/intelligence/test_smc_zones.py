"""Regression: SMC Supply/Demand Zones (Phase 164 Plan 04).

Wires FeatureFactory._compute_supply_demand_zones() (stateless, ported from
archive/smc_context/supply_demand_zones.py) into FeatureFactory.compute()/compute_batch(),
replacing 7 of the final 18 None placeholders Plan 01 threaded for demand_dist_atr/
supply_dist_atr/demand_freshness/supply_freshness/active_demand_zones/active_supply_zones/
zone_friction_score. Exercises the soft dependency on Plan 03's fvg_midpoint/price_in_premium
in-pass locals -- 164-RESEARCH.md Pitfall 1's vacuous-pass guard.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _compute_supply_demand_zones,
)

_ZONE_FIELDS = (
    "demand_dist_atr",
    "supply_dist_atr",
    "demand_freshness",
    "supply_freshness",
    "active_demand_zones",
    "active_supply_zones",
    "zone_friction_score",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_zones_* left at their dataclass defaults (lookback=150, impulse_atr_mult=1.5,
    max_base_bars=5, etc.) -- same convention as Phase 164 Plans 02/03's own tests.
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
        momentum_velocity_window=20,
        vwap_velocity_window=20,
        extreme_move_sigma_threshold=2.0,
        vol_spike_threshold=2.0,
        session_vp_rolling_window=15,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


# ---------------------------------------------------------------------------
# Fixture builders — small, deterministic, hand-computed OHLCV sequences.
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


def _extend(bars: list[dict], open_: float, high: float, low: float, close: float) -> None:
    bars.append(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1e5,
            "ts": bars[-1]["ts"] + timedelta(minutes=1),
        }
    )


def _warmup_bars(n: int, base_price: float) -> list[dict]:
    """n bars of tiny alternating-direction consolidation -- keeps ATR small
    and stable without ever forming a genuine impulse of its own (same
    convention as Phase 164 Plan 02's order-blocks warmup).
    """
    price = base_price
    bars = [
        {
            "open": base_price,
            "high": base_price + 0.05,
            "low": base_price - 0.05,
            "close": base_price,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for i in range(n - 1):
        delta = 0.05 if i % 2 == 0 else -0.04
        open_ = price
        close = price + delta
        high, low = max(open_, close) + 0.05, min(open_, close) - 0.05
        _extend(bars, open_, high, low, close)
        price = close
    return bars


def _zone_bars(direction: float) -> list[dict]:
    """direction=+1.0 -> Drop-Base-Rally (demand); direction=-1.0 -> Rally-Base-Drop (supply).

    Warmup -> 3 tiny-body/tiny-range "base" bars -> one gapped impulse bar (so
    overlap-vs-prior-bar is exactly 0, regardless of the warmup's real ATR) ->
    hold well away from the zone (never revisited -- max freshness).
    """
    bars = _warmup_bars(30, base_price=100.0)
    price = bars[-1]["close"]

    base_high = price + 0.02
    base_low = price - 0.02
    for _ in range(3):
        open_ = price
        close = price + (0.005 if direction > 0 else -0.005)
        high = max(open_, close) + 0.015
        low = min(open_, close) - 0.015
        base_high = max(base_high, high)
        base_low = min(base_low, low)
        _extend(bars, open_, high, low, close)
        price = close

    if direction > 0:
        imp_open = base_high + 0.5
        imp_close = imp_open + 4.0
    else:
        imp_open = base_low - 0.5
        imp_close = imp_open - 4.0
    high = max(imp_open, imp_close) + 0.05
    low = min(imp_open, imp_close) - 0.05
    _extend(bars, imp_open, high, low, imp_close)
    price = imp_close

    for _ in range(5):
        step = 0.15 if direction > 0 else -0.15
        close = price + step
        high = max(price, close) + 0.02
        low = min(price, close) - 0.02
        _extend(bars, price, high, low, close)
        price = close

    return bars


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) Demand zone fires (Drop-Base-Rally)
# ---------------------------------------------------------------------------


def test_demand_zone_fires(cfg):
    bars = _zone_bars(1.0)
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.demand_dist_atr is not None
    assert math.isfinite(fv.demand_dist_atr)
    assert fv.demand_dist_atr != 0.0, "demand_dist_atr frozen at 0.0 -- no demand zone detected"

    assert fv.demand_freshness is not None
    assert 0.0 <= fv.demand_freshness <= 1.0

    assert fv.active_demand_zones is not None and fv.active_demand_zones >= 1.0

    assert fv.zone_friction_score is not None
    assert 0.0 <= fv.zone_friction_score <= 1.0


# ---------------------------------------------------------------------------
# (b) Supply zone fires (Rally-Base-Drop, mirror of a)
# ---------------------------------------------------------------------------


def test_supply_zone_fires(cfg):
    bars = _zone_bars(-1.0)
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.supply_dist_atr is not None
    assert math.isfinite(fv.supply_dist_atr)
    assert fv.supply_dist_atr != 0.0, "supply_dist_atr frozen at 0.0 -- no supply zone detected"

    assert fv.supply_freshness is not None
    assert 0.0 <= fv.supply_freshness <= 1.0

    assert fv.active_supply_zones is not None and fv.active_supply_zones >= 1.0

    assert fv.zone_friction_score is not None
    assert 0.0 <= fv.zone_friction_score <= 1.0


# ---------------------------------------------------------------------------
# (c) zone_friction_score bounded + soft-dependency non-vacuous (T-164-01)
# ---------------------------------------------------------------------------


def _demand_array_fixture() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Same geometry as _zone_bars(1.0), as raw numpy arrays with a fixed
    atr_val (called directly against the helper, not through compute() --
    lets the soft-dependency toggle test hold atr_val/geometry perfectly
    constant across the two fvg_midpoint/price_in_premium variants).
    """
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    price = 100.0

    for _ in range(8):
        opens.append(price)
        highs.append(price + 0.02)
        lows.append(price - 0.02)
        closes.append(price)

    base_high = price + 0.02
    base_low = price - 0.02
    for _ in range(3):
        open_ = price
        close = price + 0.005
        high = close + 0.015
        low = open_ - 0.015
        base_high = max(base_high, high)
        base_low = min(base_low, low)
        opens.append(open_)
        highs.append(high)
        lows.append(low)
        closes.append(close)
        price = close

    imp_open = base_high + 0.5
    imp_close = imp_open + 4.0
    opens.append(imp_open)
    highs.append(imp_close + 0.05)
    lows.append(imp_open - 0.05)
    closes.append(imp_close)
    price = imp_close

    # One partial retest: a wick dips back into [base_low, base_high] (a
    # genuine touch, test_count=1 -> freshness < 1.0) without closing beyond
    # base_low (never mitigated) -- otherwise freshness stays pinned at its
    # 1.0 ceiling and the premium/fvg strength boosts below get clamped away
    # identically in both toggle variants, making the soft-dependency
    # comparison vacuous (164-RESEARCH.md Pitfall 1).
    retest_open = price
    retest_close = price - 0.1
    retest_low = base_low - 0.01
    retest_high = retest_open + 0.05
    opens.append(retest_open)
    highs.append(retest_high)
    lows.append(retest_low)
    closes.append(retest_close)
    price = retest_close

    for _ in range(5):
        close = price + 0.15
        opens.append(price)
        highs.append(close + 0.02)
        lows.append(price - 0.02)
        closes.append(close)
        price = close

    return (
        np.array(opens),
        np.array(highs),
        np.array(lows),
        np.array(closes),
        float(closes[-1]),
    )


def test_zone_friction_score_bounded_and_soft_dependency_non_vacuous(cfg):
    opens, highs, lows, closes, close_ = _demand_array_fixture()
    atr_val = 0.1

    result_no_boost = _compute_supply_demand_zones(
        opens, highs, lows, closes, close_, atr_val, cfg, 0.0, 1.0
    )
    result_boosted = _compute_supply_demand_zones(
        opens, highs, lows, closes, close_, atr_val, cfg, 0.0, 0.0
    )

    assert 0.0 <= result_no_boost["zone_friction_score"] <= 1.0
    assert 0.0 <= result_boosted["zone_friction_score"] <= 1.0
    assert result_boosted["zone_friction_score"] != result_no_boost["zone_friction_score"], (
        "zone_friction_score identical with/without price_in_premium alignment -- "
        "soft dependency not actually exercised (164-RESEARCH.md Pitfall 1)"
    )
    assert result_boosted["zone_friction_score"] > result_no_boost["zone_friction_score"]

    # Same toggle test, this time via fvg_midpoint landing inside the zone.
    demand_low = min(lows[8:11])
    demand_high = max(highs[8:11])
    zone_mid = (demand_low + demand_high) / 2.0
    result_fvg_aligned = _compute_supply_demand_zones(
        opens, highs, lows, closes, close_, atr_val, cfg, zone_mid, 1.0
    )
    assert result_fvg_aligned["zone_friction_score"] != result_no_boost["zone_friction_score"]


# ---------------------------------------------------------------------------
# (d) Raw-price / redundant-strength fields must never exist on FeatureVector
# ---------------------------------------------------------------------------


def test_zones_no_raw_price_fields_on_feature_vector(cfg):
    cache = FeatureCache()
    fv = FeatureFactory.compute(_zone_bars(1.0), "SPY", "5m", cache, cfg)

    for raw_field in (
        "nearest_demand_high",
        "nearest_demand_low",
        "nearest_supply_high",
        "nearest_supply_low",
        "demand_strength",
        "supply_strength",
        "in_demand_zone",
        "in_supply_zone",
    ):
        assert not hasattr(
            fv, raw_field
        ), f"raw/redundant field {raw_field} leaked onto FeatureVector"


# ---------------------------------------------------------------------------
# (e) Fallback contract -- never raises on atr<=0 or too-short window (T-164-05)
# ---------------------------------------------------------------------------


def test_zones_fallback_on_invalid_atr(cfg):
    opens, highs, lows, closes, close_ = _demand_array_fixture()
    result = _compute_supply_demand_zones(opens, highs, lows, closes, close_, 0.0, cfg, 0.0, 0.0)
    assert result["active_demand_zones"] == 0.0
    assert result["active_supply_zones"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


def test_zones_fallback_on_short_window(cfg):
    opens = np.array([100.0, 100.5, 100.2])
    highs = np.array([100.1, 100.6, 100.3])
    lows = np.array([99.9, 100.4, 100.1])
    closes = np.array([100.0, 100.5, 100.2])
    result = _compute_supply_demand_zones(opens, highs, lows, closes, 100.2, 1.0, cfg, 0.0, 0.0)
    assert result["active_demand_zones"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


# ---------------------------------------------------------------------------
# (f) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_zones_determinism_identical_inputs_identical_outputs(cfg):
    bars = _zone_bars(1.0)

    fv1 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)
    fv2 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)

    for field in _ZONE_FIELDS:
        v1 = getattr(fv1, field)
        v2 = getattr(fv2, field)
        assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"


# ---------------------------------------------------------------------------
# (g) compute_batch() produces non-constant zone fields
# ---------------------------------------------------------------------------


def test_compute_batch_produces_non_constant_zone_fields(cfg):
    bars = _zone_bars(1.0)
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    for field in ("demand_dist_atr", "demand_freshness"):
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant across compute_batch()"


def test_zones_compute_live_batch_parity(cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    bars = _zone_bars(1.0)
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    cache_live = FeatureCache()
    fv_live_last = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        cache_live.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _ZONE_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"
