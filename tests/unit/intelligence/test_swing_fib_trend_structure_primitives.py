"""Regression: Phase 165 swing/trend/swing-momentum/fibonacci/session-levels FeatureVector
fields are non-constant, ATR-unit, live==batch, and NULL (never a plausible number) on
insufficient data (D-01, the todo-153 failure shape).

Plan 02 (swing detection + trend structure), Plan 03 (swing momentum + fibonacci zones),
and Plan 05 (session levels + the phase-closing 36-column completeness gate) share this
file -- shared helpers (`_make_cfg`, `RNG`, `N`) stay at module level, sub-scopes are
sectioned by comment header. This file now covers all four Phase 165 sub-scopes (swing
detection, trend structure, swing momentum, fibonacci zones, session levels) plus a
phase-wide gate proving all 36 columns produce real values.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.feature_factory_config import FeatureFactoryConfig
from tests.unit.intelligence.production_series import series_columns

N = 250
RNG = np.random.default_rng(7)

# Swing/Trend FeatureVector fields shared between live compute() and batch compute_batch()
_SWING_FIELDS = (
    "swing_high_dist_atr",
    "swing_low_dist_atr",
    "swing_high_type",
    "swing_low_type",
    "swing_pattern",
    "swing_high_age_bars",
    "swing_low_age_bars",
)
_TREND_FIELDS = (
    "trend_direction",
    "trend_strength",
    "trend_leg_count",
    "structure_integrity",
    "price_position",
    "trend_duration_bars",
)

# Swing Momentum / Fibonacci Zones FeatureVector fields (Phase 165 Plan 03)
_SWING_MOMENTUM_FIELDS = (
    "swing_amplitude_ratio",
    "swing_amplitude_expanding",
    "swing_amplitude_intensity",
    "swing_velocity_bars",
    "swing_velocity_bias",
    "struct_energy",
    "struct_accel_bias",
    "swing_volume_confirmation",
)
_FIB_FIELDS = (
    "nearest_fib_ratio",
    "nearest_fib_dist_atr",
    "fib_cluster_strength",
    "in_fib_discount_zone",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so everything warms up well within N bars.

    swing_pivot_window/swing_lookback_bars/trend_structure_* left at dataclass
    defaults (5 / 120 / 5.0 / 20) -- same convention as the Phase 163 S/R test.
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
        rsi_velocity_window=20,
        ofi_velocity_window=20,
        cvd_velocity_window=20,
        volume_velocity_window=20,
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


@pytest.fixture(scope="module")
def bars() -> list[dict]:
    """~250 1m bars, dual-frequency oscillation + random-walk noise so many
    swing highs/lows form with genuinely mixed higher-high/lower-high
    ordering (not a monotonic drift, which would make trend_direction/
    swing_high_type/swing_low_type artificially constant across the whole
    walk-forward batch)."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    t = np.arange(N)
    swing = np.sin(t / 3.0) * 3.5 + np.sin(t / 11.0) * 1.5
    closes = 100.0 + swing + np.cumsum(RNG.normal(0, 0.18, N))
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
# (a) Swing/trend non-constant across bars (batch path) -- direct todo-153 guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (b) ATR-unit conversion -- pins the exact swing-distance formula
# ---------------------------------------------------------------------------


def _build_swing_micro_case_bars() -> list[dict]:
    """Deterministic bars: constant true range so Wilder ATR converges to
    exactly 1.0, and a triangular oscillation with a repeated exact peak so
    the most recent confirmed swing high has an exact, hand-computable price.

    Construction mirrors the Phase 163 S/R micro-case: mid(t) triangular-
    oscillates between 98.0 and 102.0 with a fixed step of 0.25/bar (period
    32 bars); high = mid + 0.5, low = mid - 0.5 (constant true range of 1.0).
    Truncated so the final bar sits exactly 1.0 ATR below the most recent
    confirmed peak (peak high = 102.5, close = 101.5).
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    step = 0.25
    up = np.arange(0, 17) * step
    down = up[1:-1][::-1]
    period = np.concatenate([up, down])
    n_cycles = 5
    wave = np.tile(period, n_cycles)
    mid = 98.0 + wave

    cut = 32 * 2 + 15
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


# ---------------------------------------------------------------------------
# (c) Trend-structure nullability -- THE most important test in this phase
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (d) Swing-detector partial nullability -- exactly one confirmed swing high
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (e) No confirmed pivots -- all 13 fields None (the no-object case)
# ---------------------------------------------------------------------------


def _random_walk_arrays(n=400, seed=5):
    """A swinging close/high/low triple with confirmed pivots, for direct helper calls."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    open_ = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(0.0, 0.004, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    return high, low, float(close[-1])


# ---------------------------------------------------------------------------
# (f) live == batch parity for all 13 swing/trend fields
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (g) APR keys are live -- proves config values actually change output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 165 Plan 03: Swing Momentum + Fibonacci Zones
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# (a) Swing-momentum non-constant across bars (batch path) -- direct
# todo-153-shaped guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (b) Swing-momentum nullability -- D-01, the archived plugin's own
# already-clean {} contract
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (c) ATR-invariance -- THE proof obligation for Task 1(e)'s divisor deletion
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (d) swing_amplitude_expanding uses the LAST three amplitudes, not the
# archived plugin's first three
# ---------------------------------------------------------------------------


def _build_amplitude_progression_bars() -> list[dict]:
    """9 vertices (a padding trough+peak on each end plus 7 real swing
    extremes) whose 6 real amplitudes are [~1.02, ~2.02, ~3.02, ~3.02,
    ~2.02, ~1.02] -- the FIRST three strictly increasing, the LAST three
    NOT. Regression fixture for the archived
    amplitudes[0] < amplitudes[1] < amplitudes[2] bug (migration 267's
    COMMENT and the archived docstring both require testing the LAST three
    instead). The +-0.01 high/low offset is a uniform constant added to
    every amplitude, so it shifts magnitudes without disturbing the
    ordering under test. Padding vertices at both ends fall outside the
    confirm-window's boundary (no bars before the first / after the last)
    and are deliberately dropped, leaving exactly the 7 intended extremes.
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    vertices = [103.0, 100.0, 101.0, 99.0, 102.0, 99.0, 101.0, 100.0, 103.0]
    seg_bars = 6
    closes: list[float] = [vertices[0]]
    for k in range(len(vertices) - 1):
        seg = np.linspace(vertices[k], vertices[k + 1], seg_bars + 1)[1:]
        closes.extend(seg.tolist())
    closes_arr = np.array(closes)
    return [
        {
            "open": float(closes_arr[i]),
            "high": float(closes_arr[i] + 0.01),
            "low": float(closes_arr[i] - 0.01),
            "close": float(closes_arr[i]),
            "volume": 1_000.0 + i,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(len(closes_arr))
    ]


# ---------------------------------------------------------------------------
# (e) swing_velocity_bias numeric encoding (D-03) -- no string anywhere
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (f) swing_volume_confirmation free field (D-15) -- reads volume, not price
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (g) nearest_fib_ratio is always one of the 5 canonical ratios
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (h) fib distance is pinned in ATR units, not merely finite
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (i) fib nullability on a degenerate (flat, zero-ATR) swing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (j) fib discount-zone boundary flip
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (k) live == batch parity for all 12 swing-momentum/fib fields
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (l) APR keys are live -- proves config values actually change output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 165 Plan 05: Session Levels (11 fields) + phase-closing completeness gate
# ---------------------------------------------------------------------------

_SESSION_LEVEL_FIELDS = (
    "prior_session_high_dist_atr",
    "prior_session_low_dist_atr",
    "prior_session_close_dist_atr",
    "opening_gap_pct",
    "weekly_pivot_dist_atr",
    "weekly_r1_dist_atr",
    "weekly_r2_dist_atr",
    "weekly_s1_dist_atr",
    "weekly_s2_dist_atr",
    "nearest_level_dist_atr",
    "gap_filled",
)

# The union of every Phase 165 field, in FeatureVector dataclass declaration order
# (Plan 02's 13 + Plan 03's 12 + Plan 05's 11 = 36).
_PHASE_165_FIELDS = (
    _SWING_FIELDS + _TREND_FIELDS + _SWING_MOMENTUM_FIELDS + _FIB_FIELDS + _SESSION_LEVEL_FIELDS
)


_SESSION_N_DAYS = 8
_SESSION_STEP_MINUTES = 30
_SESSION_RNG = np.random.default_rng(1165)


def _build_session_levels_bars() -> list[dict]:
    """~8 days of 30-min bars (continuous calendar coverage, not RTH-only) with the
    same dual-frequency-oscillation + random-walk shape as the module `bars`
    fixture -- spans multiple ET session-day rollovers and at least one ISO-week
    boundary, so all 11 session-levels fields (plus the swing/trend/fib fields
    the `bars` fixture already exercises at 1-minute granularity) take real,
    varying non-None values. Continuous (not RTH-only) calendar coverage means
    every ET calendar-date change is a session rollover in this synthetic
    fixture -- deliberately denser than real trading-day boundaries, which only
    strengthens (never weakens) the non-constancy/completeness assertions below.
    """
    base_ts = datetime(2026, 7, 6, 0, 0, tzinfo=UTC)  # Monday midnight UTC
    n = _SESSION_N_DAYS * 24 * 60 // _SESSION_STEP_MINUTES
    t = np.arange(n)
    swing = np.sin(t / 3.0) * 3.5 + np.sin(t / 11.0) * 1.5
    closes = 100.0 + swing + np.cumsum(_SESSION_RNG.normal(0, 0.05, n))
    spread = np.abs(_SESSION_RNG.normal(0.10, 0.03, n)) + 0.03
    highs = closes + spread
    lows = closes - spread
    opens = closes + _SESSION_RNG.normal(0, 0.03, n)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = _SESSION_RNG.uniform(1e4, 1e6, n)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=_SESSION_STEP_MINUTES * i),
        }
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def session_bars() -> list[dict]:
    return _build_session_levels_bars()


@pytest.fixture(scope="module")
def session_batch_5m(session_bars, cfg) -> dict:
    """Every column of `session_bars` at 5m through the corpus-rerun path; read-only."""
    return series_columns(session_bars, "SPY", "5m", cfg)


# ---------------------------------------------------------------------------
# (a) Session-levels non-constant across bars (batch path) -- direct
# todo-153-shaped guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (b) Cold nullability -- shorter than one session, no week has ever rolled over
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (c) ATR-unit conversion -- pins the exact prior-session-high formula
# ---------------------------------------------------------------------------


def _build_session_atr_pin_bars() -> list[dict]:
    """Deterministic 2-session bars: constant true range so Wilder ATR
    converges to exactly 1.0, spanning exactly one session rollover so
    prior_session_high_dist_atr is measurable and pinned on the final bar."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 ET
    day1_mid = [100.0, 100.5, 101.0, 100.5, 100.0]
    day2_mid = [100.5, 101.0, 101.5, 102.0, 102.5]
    bars_local: list[dict] = []
    ts = base_ts
    for m in day1_mid:
        bars_local.append(
            {"open": m, "high": m + 0.5, "low": m - 0.5, "close": m, "volume": 1_000.0, "ts": ts}
        )
        ts = ts + timedelta(minutes=5)
    ts = base_ts + timedelta(days=1)
    for m in day2_mid:
        bars_local.append(
            {"open": m, "high": m + 0.5, "low": m - 0.5, "close": m, "volume": 1_000.0, "ts": ts}
        )
        ts = ts + timedelta(minutes=5)
    return bars_local


# ---------------------------------------------------------------------------
# (d) Weekly pivot pin -- exact formula off the PRIOR COMPLETED week only
# ---------------------------------------------------------------------------


def _build_weekly_pivot_bars(mid_step: float = 0.5, range_half_width: float = 0.5) -> list[dict]:
    """10 bars spanning one ISO-week boundary (7 calendar days apart) so the
    prior-completed-week snapshot is populated (and ATR is warmed --
    config.adx_period=7) by the final bar. mid_step drifts each bar's mid price;
    range_half_width sets each bar's high/low offset around its mid (governs ATR
    magnitude). Defaults (0.5/0.5) produce an ordinary ATR; a much smaller
    range_half_width (todo 237's regression test) reproduces a BIL-style
    near-zero-ATR flat period."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday, ISO week 28
    mids = [100.0 + mid_step * i for i in range(10)]
    tss = [base_ts + timedelta(days=i) for i in range(7)] + [
        base_ts + timedelta(days=7),
        base_ts + timedelta(days=8),
        base_ts + timedelta(days=9),
    ]
    return [
        {
            "open": m,
            "high": m + range_half_width,
            "low": m - range_half_width,
            "close": m,
            "volume": 1_000.0,
            "ts": ts,
        }
        for m, ts in zip(mids, tss)
    ]


# ---------------------------------------------------------------------------
# (e) tf=='1d' presence -- the kernel declares no 1d suppression any more
# ---------------------------------------------------------------------------


def _present(value) -> bool:
    """A stored value: not None and not NaN (an undefined value is missing either way)."""
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def test_session_levels_daily_presence(session_bars, session_batch_5m, cfg):
    """The session_levels kernel declares nothing not applicable on 1d (the overnight and Asian
    outputs that were are retired, todo 584 item 6): opening_gap_pct and the weekly five are
    present at both 5m and 1d."""
    columns_5m = session_batch_5m
    columns_1d = series_columns(session_bars, "SPY", "1d", cfg)

    for field in (
        "opening_gap_pct",
        "weekly_pivot_dist_atr",
        "weekly_r1_dist_atr",
        "weekly_r2_dist_atr",
        "weekly_s1_dist_atr",
        "weekly_s2_dist_atr",
    ):
        n_5m = int(np.isfinite(columns_5m[field]).sum())
        n_1d = int(np.isfinite(columns_1d[field]).sum())
        assert n_5m > 0 and n_1d > 0, f"{field} must be meaningful on both 5m and 1d"


# ---------------------------------------------------------------------------
# (f) gap_filled -- D-13 free field, must actually gap and then fill
# ---------------------------------------------------------------------------


def _build_gap_fill_bars() -> list[dict]:
    """Day 1: 8 constant-true-range bars ending at close=103.5 (the prior
    session close). Day 2: gaps up well above 103.5, then descends far enough
    to bracket it -- gap_filled must flip 0.0 -> 1.0 and stay latched."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    day1_mids = [100.0 + 0.5 * i for i in range(8)]
    day1 = [
        {
            "open": m,
            "high": m + 0.5,
            "low": m - 0.5,
            "close": m,
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=5 * i),
        }
        for i, m in enumerate(day1_mids)
    ]
    prior_close = day1_mids[-1]
    day2_base = base_ts + timedelta(days=1)
    day2_phase1 = [prior_close + 3.0 + 0.2 * i for i in range(4)]  # stays above, no fill yet
    day2_phase2 = [day2_phase1[-1] - 1.0 * i for i in range(1, 7)]  # descends, crosses prior_close
    day2_mids = day2_phase1 + day2_phase2
    day2 = [
        {
            "open": m,
            "high": m + 0.5,
            "low": m - 0.5,
            "close": m,
            "volume": 1_000.0,
            "ts": day2_base + timedelta(minutes=5 * i),
        }
        for i, m in enumerate(day2_mids)
    ]
    return day1 + day2


# ---------------------------------------------------------------------------
# (g) live == batch parity for all 11 session-levels fields
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (h) THE phase-closing gate: all 36 Phase 165 columns produce real values
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (i) field-set cross-check: dataclass, domain registry, concept_registry
# ---------------------------------------------------------------------------


def test_every_1d_not_applicable_output_is_missing(session_bars, session_batch_5m, cfg):
    """Every feature column the registry declares not applicable on 1d (design D1) is missing
    in the 1d series on the same bars -- NaN on the kernel grid, never a neutral 0.0/0.5 (the old VP call-site branch) or a _guard
    fallback (the old plain-float calendar reads)."""
    from src.intelligence.features.contract.registry import default_registry

    registry = default_registry()
    declared = registry.applicable_outputs("1d")
    missing = registry.not_applicable_outputs("1d") & set(registry.feature_columns())
    assert missing, "the declaration set must not be empty"
    assert not (missing & declared)

    columns_1d = series_columns(session_bars, "SPY", "1d", cfg)
    leaked = [
        name
        for name in sorted(missing)
        if name in columns_1d and np.isfinite(columns_1d[name]).any()
    ]
    assert not leaked, f"declared-1d outputs with values on the 1d series: {leaked[:5]}"

    # The same columns carry values at 5m where the fixture supplies the inputs (session flags,
    # clock encodings and VP; the ret_div divergences need CTF externals the fixture
    # does not pass, so they stay missing at 5m too and are not asserted here).
    populated_at_5m = (
        "in_ny_session",
        "session_time_pos",
        "hour_of_day_sin",
        "minute_of_hour_sin",
        "poc_dist_atr",
        "va_position",
    )
    for name in populated_at_5m:
        assert np.isfinite(
            session_batch_5m[name]
        ).any(), f"{name} never populated at tf='5m' -- fixture too short"
