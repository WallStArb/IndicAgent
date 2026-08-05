"""Regression: SMC AMD Cycle + FeatureCache.update_overnight_range() wiring (Phase 164 Plan 04).

Wires FeatureFactory._derive_amd_cycle() (reads FeatureCache's overnight-range/manipulation
state, set by the update_overnight_range() mutator Plan 01 built but never invoked) into
FeatureFactory.compute()/compute_batch(), replacing the final 4 None placeholders Plan 01
threaded for amd_phase/amd_manipulation_detected/amd_distribution_direction/manip_strength.
Also verifies update_overnight_range()'s call sites (compute_batch loop, live per-bar handler,
warm-up replay block) so the overnight-range state's lifecycle no longer cold-starts
inconsistently vs update_wk_vwap()/update_session_vp() (T-164-07).
"""

from __future__ import annotations

import inspect
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from services import feature_vector_pipeline
from src.intelligence import feature_factory
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _derive_amd_cycle,
)

_AMD_FIELDS = (
    "amd_phase",
    "amd_manipulation_detected",
    "amd_distribution_direction",
    "manip_strength",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_amd_* left at their dataclass defaults (accum_start=20 UTC, manip_end=10 UTC,
    dist_end=21 UTC) -- same convention as Phase 164 Plans 02/03's own tests.
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
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


_DAY0 = date(2023, 1, 3)
_DAY1 = date(2023, 1, 4)


def _ts(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# (a) Full cycle: accumulation -> manipulation (overshoot, clamp) -> distribution
# ---------------------------------------------------------------------------


def test_amd_full_cycle_transitions_and_manip_strength_clamp(cfg):
    cache = FeatureCache()

    accum_high, accum_low = 100.0, 99.0  # on_range = 1.0
    for hour in range(20, 24):
        ts = _ts(_DAY0, hour)
        cache.update_overnight_range(ts, accum_high, accum_low, cfg)
        fields = _derive_amd_cycle(cache, ts, cfg)
        assert fields["amd_phase"] == 1.0
        assert fields["amd_manipulation_detected"] == 0.0
        assert fields["amd_distribution_direction"] == 0.0

    # Manipulation: upside sweep overshooting the overnight range by 150% --
    # the exact >100%-overshoot case 164-RESEARCH.md Pitfall 3 requires.
    manip_ts = _ts(_DAY1, 2)
    on_range = accum_high - accum_low
    overshoot_high = accum_high + on_range * 1.5
    cache.update_overnight_range(manip_ts, overshoot_high, accum_high - 0.01, cfg)
    fields = _derive_amd_cycle(cache, manip_ts, cfg)
    assert fields["amd_phase"] == 2.0
    assert fields["amd_manipulation_detected"] == 1.0
    assert 0.0 <= fields["manip_strength"] <= 1.0
    assert fields["manip_strength"] == 1.0, "raw ratio 1.5 must clamp down to exactly 1.0"
    # Not yet in distribution -- direction must not leak early.
    assert fields["amd_distribution_direction"] == 0.0

    # Distribution: overnight state must still be readable many bars later.
    dist_ts = _ts(_DAY1, 12)
    cache.update_overnight_range(dist_ts, accum_high - 0.02, accum_low + 0.5, cfg)
    fields = _derive_amd_cycle(cache, dist_ts, cfg)
    assert fields["amd_phase"] == 3.0
    assert fields["amd_manipulation_detected"] == 1.0
    assert fields["amd_distribution_direction"] == -1.0, "upside sweep -> bearish distribution"
    assert fields["manip_strength"] == 1.0


# ---------------------------------------------------------------------------
# (b) Extreme overshoot (3x the overnight range) still clamps to exactly 1.0
# ---------------------------------------------------------------------------


def test_manip_strength_extreme_overshoot_still_clamped(cfg):
    cache = FeatureCache()
    accum_high, accum_low = 50.0, 49.5  # on_range = 0.5
    ts0 = _ts(_DAY0, 21)
    cache.update_overnight_range(ts0, accum_high, accum_low, cfg)

    manip_ts = _ts(_DAY1, 3)
    on_range = accum_high - accum_low
    overshoot_high = accum_high + on_range * 3.0  # 300% overshoot
    cache.update_overnight_range(manip_ts, overshoot_high, accum_high - 0.01, cfg)

    fields = _derive_amd_cycle(cache, manip_ts, cfg)
    assert fields["amd_manipulation_detected"] == 1.0
    assert fields["manip_strength"] == 1.0
    assert 0.0 <= fields["manip_strength"] <= 1.0


# ---------------------------------------------------------------------------
# (c) UTC-20:00 boundary reset
# ---------------------------------------------------------------------------


def test_boundary_reset_at_next_accumulation_cycle(cfg):
    cache = FeatureCache()
    accum_high, accum_low = 100.0, 99.0
    cache.update_overnight_range(_ts(_DAY0, 20), accum_high, accum_low, cfg)

    manip_ts = _ts(_DAY1, 2)
    cache.update_overnight_range(manip_ts, accum_high + 1.5, accum_high - 0.01, cfg)
    assert cache.amd_manipulation_detected == 1.0

    next_accum_ts = _ts(_DAY1, 20)
    cache.update_overnight_range(next_accum_ts, 105.0, 104.5, cfg)
    fields = _derive_amd_cycle(cache, next_accum_ts, cfg)
    assert fields["amd_phase"] == 1.0
    assert fields["amd_manipulation_detected"] == 0.0, "manipulation flag must reset at boundary"
    assert fields["amd_distribution_direction"] == 0.0


# ---------------------------------------------------------------------------
# (d) amd_phase ordinal sweep -- {0, 1, 2, 3} only
# ---------------------------------------------------------------------------


def test_amd_phase_ordinal_values(cfg):
    cache = FeatureCache()

    assert _derive_amd_cycle(cache, None, cfg)["amd_phase"] == 0.0
    assert _derive_amd_cycle(cache, _ts(_DAY0, 20), cfg)["amd_phase"] == 1.0
    assert _derive_amd_cycle(cache, _ts(_DAY0, 2), cfg)["amd_phase"] == 2.0
    assert _derive_amd_cycle(cache, _ts(_DAY0, 12), cfg)["amd_phase"] == 3.0

    for hour in range(24):
        phase = _derive_amd_cycle(cache, _ts(_DAY0, hour), cfg)["amd_phase"]
        assert phase in (0.0, 1.0, 2.0, 3.0)


# ---------------------------------------------------------------------------
# (e) Warm-up replay leaves overnight state non-cold (matches update_session_vp)
# ---------------------------------------------------------------------------


def test_warm_up_replay_leaves_overnight_state_non_cold(cfg):
    cache_cold = FeatureCache()
    assert cache_cold._overnight_high is None
    assert cache_cold._overnight_low is None

    cache_replayed = FeatureCache()
    buffered = [
        {"ts": _ts(_DAY0, hour), "high": 100.0 + 0.1 * i, "low": 99.5 + 0.1 * i}
        for i, hour in enumerate(range(20, 24))
    ]
    for bar in buffered:
        cache_replayed.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)

    assert cache_replayed._overnight_high is not None
    assert cache_replayed._overnight_low is not None

    fields = _derive_amd_cycle(cache_replayed, _ts(_DAY0, 23), cfg)
    assert fields["amd_phase"] == 1.0


# ---------------------------------------------------------------------------
# (f) Never raises on a cold cache / insufficient state (T-164-05)
# ---------------------------------------------------------------------------


def test_amd_never_raises_on_cold_cache(cfg):
    cache = FeatureCache()
    for hour in (2, 12, 20):
        fields = _derive_amd_cycle(cache, _ts(_DAY0, hour), cfg)
        for v in fields.values():
            assert math.isfinite(v)
        assert fields["amd_manipulation_detected"] == 0.0
        assert fields["amd_distribution_direction"] == 0.0
        assert fields["manip_strength"] == 0.0


# ---------------------------------------------------------------------------
# (g) update_overnight_range() wired into compute_batch()'s per-bar loop
# ---------------------------------------------------------------------------


def _bars_spanning_amd_cycle() -> list[dict]:
    """5m bars from 19:55 UTC through the next day's 12:xx UTC -- crosses the
    accumulation -> manipulation -> distribution boundaries within one series,
    with a manipulation-phase wick that breaches and reverses.
    """
    bars: list[dict] = []
    ts = datetime(2023, 1, 3, 19, 55, tzinfo=UTC)
    price = 100.0

    def _flat(n: int) -> None:
        nonlocal ts, price
        for _ in range(n):
            bars.append(
                {
                    "open": price,
                    "high": price + 0.05,
                    "low": price - 0.05,
                    "close": price,
                    "volume": 1e5,
                    "ts": ts,
                }
            )
            ts = ts + timedelta(minutes=5)

    _flat(1)  # 19:55 -- still accumulation-adjacent padding
    _flat(48)  # 20:00 through ~23:55 -- accumulation window (12 bars/hour * 4h)

    # Manipulation bar: wick above the accumulated overnight high, close back
    # inside -- 00:xx UTC.
    bars.append(
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.02,
            "close": price + 0.01,
            "volume": 1e5,
            "ts": ts,
        }
    )
    ts = ts + timedelta(minutes=5)
    price = bars[-1]["close"]

    _flat(150)  # carry through manipulation + into distribution (~12.5h)

    return bars


def test_compute_batch_amd_fields_non_constant_and_grep_wired(cfg):
    bars = _bars_spanning_amd_cycle()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    phases = {round(fv.amd_phase, 4) for _, fv in results if fv.amd_phase is not None}
    assert len(phases) > 1, "amd_phase never transitions across compute_batch()'s bars"

    manip_flags = {fv.amd_manipulation_detected for _, fv in results}
    assert 1.0 in manip_flags, "amd_manipulation_detected never fires across the manipulation wick"


def test_update_overnight_range_wired_into_call_sites():
    """Structural check that the mutator's 3 required call sites exist:
    compute_batch()'s per-bar loop, the live per-bar handler, and the
    warm-up replay block (T-164-07) -- complements the plan's own grep gate.
    """
    batch_src = inspect.getsource(feature_factory.FeatureFactory.compute_batch)
    assert "update_overnight_range" in batch_src

    pipeline_src = inspect.getsource(feature_vector_pipeline)
    assert pipeline_src.count("update_overnight_range") >= 2, (
        "expected at least 2 call sites in feature_vector_pipeline.py "
        "(live per-bar handler + warm-up replay block)"
    )


# ---------------------------------------------------------------------------
# (h) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_amd_determinism_identical_inputs_identical_outputs(cfg):
    bars = _bars_spanning_amd_cycle()

    cache1 = FeatureCache()
    cache2 = FeatureCache()
    results1 = FeatureFactory.compute_batch(bars, "SPY", "5m", cache1, cfg)
    results2 = FeatureFactory.compute_batch(bars, "SPY", "5m", cache2, cfg)

    for (_, fv1), (_, fv2) in zip(results1, results2, strict=True):
        for field in _AMD_FIELDS:
            v1 = getattr(fv1, field)
            v2 = getattr(fv2, field)
            assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"
