"""Regression: SMC Order Blocks + stateless Breaker/Mitigation (Phase 164 Plan 02).

Wires FeatureFactory._compute_order_blocks() (stateless full-window scan, ported from
archive/smc_context/order_blocks.py + breaker_blocks.py + mitigation_blocks.py) into
FeatureFactory.compute()/compute_batch(), replacing the 7 None placeholders Plan 01 threaded
for ob_bull_dist_atr/ob_bear_dist_atr/ob_strength/ob_mitigated_flag/breaker_dist_atr/
breaker_block_active/ob_mitigation_pct. Covers the hard order_blocks -> breaker/mitigation
dependency chain 164-RESEARCH.md flagged as this phase's hardest sequencing case, ported
statelessly (no self._state, no FeatureCache) per its explicit correction.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.schemas import FeatureVector

_OB_FIELDS = (
    "ob_bull_dist_atr",
    "ob_bear_dist_atr",
    "ob_strength",
    "ob_mitigated_flag",
    "breaker_dist_atr",
    "breaker_block_active",
    "ob_mitigation_pct",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_order_blocks_* left at dataclass defaults (100/3/0.003/10) -- same convention
    as Phase 163's own tests (leave the feature-under-test's own config at its
    APR-seeded defaults).
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
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
        session_vp_rolling_window=15,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


# ---------------------------------------------------------------------------
# Fixture builders — small, deterministic, hand-computed OHLCV sequences that
# reliably trigger order_blocks.py's impulse+opposing-candle detection
# geometry (no randomness -- every candle is placed on purpose).
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


def _candle(open_: float, close: float, wick: float = 0.1) -> tuple[float, float, float, float]:
    """(open, high, low, close) with a small symmetric wick around the body."""
    high = max(open_, close) + wick
    low = min(open_, close) - wick
    return open_, high, low, close


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


def _warmup_bars(n: int, base_price: float, seed: int) -> list[dict]:
    """n bars of tiny alternating-direction consolidation.

    Magnitude (+0.05/-0.04 per bar) is well under the default 0.3%
    significant-move threshold, so no impulse/OB candidate ever forms from
    warmup alone -- it exists purely to give ATR (adx_period=7) and the
    overall bar-count guards enough history to warm up. `seed` is accepted
    for call-site symmetry with other fixture builders in this module but
    unused -- warmup is fully deterministic (no randomness needed).
    """
    del seed
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


def _bullish_ob_bars() -> list[dict]:
    """Bearish OB candle -> 3-bar bullish impulse -> hold well above the zone.

    Forms one clean, unmitigated bullish order block: the OB stays untouched
    (price never dips back toward it), giving a finite, non-zero
    ob_bull_dist_atr and ob_mitigated_flag == 0.0 for it.
    """
    bars = _warmup_bars(30, base_price=100.0, seed=1)
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close + 0.3, last_close - 0.9))  # bearish OB candle
    price = bars[-1]["close"]
    for _ in range(3):  # impulse_bars default = 3
        open_ = price
        close = price + 2.0
        _extend(bars, *_candle(open_, close))
        price = close
    for _ in range(5):  # hold well above the OB zone
        open_ = price
        close = price + 0.1
        _extend(bars, *_candle(open_, close))
        price = close
    return bars


def _bearish_ob_bars() -> list[dict]:
    """Mirror of _bullish_ob_bars(): bullish OB candle -> 3-bar bearish impulse -> hold below."""
    bars = _warmup_bars(30, base_price=100.0, seed=2)
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close - 0.3, last_close + 0.9))  # bullish OB candle
    price = bars[-1]["close"]
    for _ in range(3):
        open_ = price
        close = price - 2.0
        _extend(bars, *_candle(open_, close))
        price = close
    for _ in range(5):
        open_ = price
        close = price - 0.1
        _extend(bars, *_candle(open_, close))
        price = close
    return bars


def _ob_breaker_retest_bars() -> list[dict]:
    """Bullish OB forms, is fully mitigated by a 2-bar decline through its own
    zone, then price reclaims immediately back inside the zone (now a bearish
    breaker, per breaker_blocks.py's flip-polarity rule) on the very last bar.

    Exercises breaker_block_active == 1.0 and ob_mitigation_pct in (0, 1]
    TOGETHER, on a fixture that genuinely forms and then breaks/mitigates an
    order block -- not a no-OB-present fixture that would pass the "no
    breaker" branch vacuously (164-RESEARCH.md Pitfall 1).
    """
    bars = _warmup_bars(30, base_price=100.0, seed=3)
    last_close = bars[-1]["close"]
    _extend(bars, *_candle(last_close + 0.3, last_close - 0.9))  # bearish OB candle
    price = bars[-1]["close"]
    for _ in range(3):  # bullish impulse
        open_ = price
        close = price + 2.0
        _extend(bars, *_candle(open_, close))
        price = close
    # 2-bar decline back through the OB zone -- a wick low fully mitigates it
    # (order_blocks.py's _check_mitigated reads the low series, not close).
    _extend(bars, *_candle(price, price - 3.5))
    price = bars[-1]["close"]
    _extend(bars, *_candle(price, price - 3.5))
    price = bars[-1]["close"]
    # Reclaim: back up into the (now-flipped bearish) breaker zone, on the
    # final bar -- a retest from below.
    _extend(bars, *_candle(price, price + 3.8))
    return bars


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) Bullish order block fires
# ---------------------------------------------------------------------------


def test_ob_bull_dist_atr_fires(cfg):
    bars = _bullish_ob_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.ob_bull_dist_atr is not None
    assert math.isfinite(fv.ob_bull_dist_atr)
    assert fv.ob_bull_dist_atr != 0.0, "ob_bull_dist_atr frozen at 0.0 -- no OB detected"

    assert fv.ob_strength is not None
    assert 0.0 <= fv.ob_strength <= 1.0


# ---------------------------------------------------------------------------
# (b) Bearish order block fires (mirror of a)
# ---------------------------------------------------------------------------


def test_ob_bear_dist_atr_fires(cfg):
    bars = _bearish_ob_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.ob_bear_dist_atr is not None
    assert math.isfinite(fv.ob_bear_dist_atr)
    assert fv.ob_bear_dist_atr != 0.0, "ob_bear_dist_atr frozen at 0.0 -- no OB detected"

    assert fv.ob_strength is not None
    assert 0.0 <= fv.ob_strength <= 1.0


# ---------------------------------------------------------------------------
# (c) Breaker + mitigation exercised together (RESEARCH Pitfall 1 guard)
# ---------------------------------------------------------------------------


def test_breaker_and_mitigation_exercised(cfg):
    """A sequenced OB-then-break/mitigate fixture must produce a genuinely
    active breaker and a non-trivial mitigation percentage -- not the
    vacuous "no breaker present" pass a no-OB fixture would give.
    """
    bars = _ob_breaker_retest_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.breaker_block_active == 1.0, "breaker never activated on a retested mitigated OB"
    assert fv.breaker_dist_atr is not None
    assert math.isfinite(fv.breaker_dist_atr)

    assert fv.ob_mitigation_pct is not None
    assert 0.0 < fv.ob_mitigation_pct <= 1.0, "ob_mitigation_pct not exercised in (0, 1]"

    assert fv.ob_mitigated_flag == 1.0


def test_breaker_and_mitigation_non_constant_vs_unmitigated_fixture(cfg):
    """Cross-fixture non-constant guard: an untouched OB (a) must NOT report
    the same breaker/mitigation state as a genuinely broken-and-retested one
    (c) -- pins that these fields are real detections, not hardcoded.
    """
    cache_a = FeatureCache()
    fv_untouched = FeatureFactory.compute(_bullish_ob_bars(), "SPY", "5m", cache_a, cfg)

    cache_c = FeatureCache()
    fv_broken = FeatureFactory.compute(_ob_breaker_retest_bars(), "SPY", "5m", cache_c, cfg)

    assert fv_untouched.breaker_block_active == 0.0
    assert fv_untouched.ob_mitigation_pct == 0.0
    assert fv_untouched.ob_mitigated_flag == 0.0

    assert fv_broken.breaker_block_active == 1.0
    assert fv_broken.ob_mitigation_pct is not None and fv_broken.ob_mitigation_pct > 0.0
    assert fv_broken.ob_mitigated_flag == 1.0


# ---------------------------------------------------------------------------
# (d) Raw-price fields must never exist on FeatureVector (T-164-02)
# ---------------------------------------------------------------------------


def test_no_raw_price_fields_on_feature_vector(cfg):
    cache = FeatureCache()
    fv = FeatureFactory.compute(_bullish_ob_bars(), "SPY", "5m", cache, cfg)

    for raw_field in ("ob_top", "ob_bottom", "breaker_block_top", "breaker_block_bottom"):
        assert not hasattr(fv, raw_field), f"raw-price field {raw_field} leaked onto FeatureVector"


# ---------------------------------------------------------------------------
# (e) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_determinism_identical_inputs_identical_outputs(cfg):
    bars = _ob_breaker_retest_bars()

    fv1 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)
    fv2 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)

    for field in _OB_FIELDS:
        v1 = getattr(fv1, field)
        v2 = getattr(fv2, field)
        assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"


# ---------------------------------------------------------------------------
# (f) compute_batch() produces the same non-constant/exercised behavior
# ---------------------------------------------------------------------------


def test_compute_batch_produces_non_constant_ob_fields(cfg):
    bars = _ob_breaker_retest_bars()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    for field in ("ob_bull_dist_atr", "ob_strength"):
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant across compute_batch()"

    # The final bar (the retest) must show an active breaker, matching compute().
    _, fv_last = results[-1]
    assert fv_last.breaker_block_active == 1.0
    assert fv_last.ob_mitigation_pct is not None and fv_last.ob_mitigation_pct > 0.0


def test_compute_live_batch_parity(cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    bars = _ob_breaker_retest_bars()
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
    for field in _OB_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"
