"""Registered feature kernels against compute_batch and the causality probe (186-12, D-25, D-26).

(a) every registered feature column is a persisted FeatureVector column;
(b) each kernel output equals the compute_batch column on the 500-bar synthetic fixture;
(c) compute_batch no longer calls the moved scalar helpers;
(d) the causality probe and memory check pass every kernel under two configs.
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.causality_probe import (
    CausalityViolation,
    causality_probe,
    memory_check,
    probe_registry,
)
from src.intelligence.features.feature_vector_persistence import _ALL_COLUMN_NAMES
from src.intelligence.features.registry import KernelRegistry, compute_kernels, default_registry
from tests.unit.intelligence import kernel_parity_reference as ref

MANIFEST = ref.load_manifest()
PROBE_ROWS = np.array([700, 1200, 1800, 2400, 2999])
PROBE_BARS = 3000

# Kernels whose output depends on where the series starts (registry path_dependent).
PATH_DEPENDENT = {
    "calendar_above_wk_vwap",
    "ret_autocorr",
    "abs_ret_autocorr",
    "streak_z",
    "variance_ratio",
    "bar_statistics_refresh",
    "vwap_dev_sigma",
}
ACAUSAL_CONTROLS = {"canary_acausal_placebo"}

# compute_batch calls none of these helpers by name any more; it reads registry outputs.
DELEGATED_HELPERS = (
    "_in_ny_session",
    "_in_london_kz",
    "_in_overlap",
    "_power_hour",
    "_opening_range",
    "_session_time_pos",
    "_dow_encoding",
    "_month_position",
    "_quarter_position",
    "_days_to_month_end_fraction",
    "_quarter_cycle_encoding",
    "_tdom_encoding",
    "_minute_of_hour_encoding",
    "_hour_of_day_sin",
    "_hour_of_day_cos",
    "_week_of_month_sin",
    "_week_of_month_cos",
    "_day_of_month_sin",
    "_day_of_month_cos",
    "_week_of_year_sin",
    "_week_of_year_cos",
    "_month_sin",
    "_month_cos",
    "_opex_flag",
    "_quad_witching_flag",
    "_earnings_season_flag",
    "_days_since_quarter_end",
    "_canary_noise_gaussian",
    "_canary_noise_uniform",
    "_canary_near_constant",
    "_canary_acausal_placebo",
    "_bar_close_pos",
    "_range_position",
    "_vol_ratio",
    "_body_ratio",
    "_upper_wick_ratio",
    "_lower_wick_ratio",
    "_range_vs_atr",
    "_close_vs_open_direction",
    "_overnight_gap",
    "_range_efficiency",
    "_ret_lag_1",
    "_ret_lag_2",
    "_ret_lag_3",
    "_ret_lag_fast",
    "_ret_lag_mid",
    "_ret_lag_slow",
    "_open_ret",
    "_intraday_ret",
    "_open_vs_intraday",
    "_cci",
    "_aroon_osc",
    "_ret_vol_ratio",
    "_informed_flow",
    "_cmf",
    "_product",
    "_up_vol_body_diff",
)


# Numeric persisted columns no kernel owns after this plan: SMC, structural VP/SR/swing/fib/
# session-level/AMD, CTF, the three ret_div columns, the cross-sectional rank columns, the HMM
# regime columns, and the macro columns until they move (this plan's macro commits). A column
# that is dropped or left unowned changes this set and fails the test below.
REMAINING_COLUMNS = frozenset(
    {
        "active_demand_zones",
        "active_supply_zones",
        "amd_distribution_direction",
        "amd_manipulation_detected",
        "amd_phase",
        "asian_session_high_dist_atr",
        "asian_session_low_dist_atr",
        "bars_since_last_shift",
        "bars_since_last_sweep",
        "bos_direction",
        "bos_strength",
        "breaker_block_active",
        "breaker_dist_atr",
        "bsl_dist_atr",
        "bsl_touches",
        "choch_direction",
        "choch_strength",
        "ctf_momentum",
        "ctf_regime_align",
        "ctf_vwap_align",
        "demand_dist_atr",
        "demand_freshness",
        "distance_to_vah_atr",
        "distance_to_val_atr",
        "equity_beta_z",
        "fib_cluster_strength",
        "flight_quality",
        "fvg_dist_atr",
        "fvg_open_count",
        "fvg_size_atr",
        "gap_filled",
        "hmm_duration",
        "hmm_entropy",
        "hmm_regime_prob",
        "hyg_lqd_ret_z",
        "in_fib_discount_zone",
        "in_lvn",
        "manip_strength",
        "momentum_rank_z",
        "nearest_fib_dist_atr",
        "nearest_fib_ratio",
        "nearest_hvn_above_dist_atr",
        "nearest_hvn_below_dist_atr",
        "nearest_hvn_dist_atr",
        "nearest_level_dist_atr",
        "nearest_lvn_above_dist_atr",
        "nearest_lvn_below_dist_atr",
        "ob_bear_dist_atr",
        "ob_bull_dist_atr",
        "ob_mitigated_flag",
        "ob_mitigation_pct",
        "ob_strength",
        "opening_gap_pct",
        "overnight_high_dist_atr",
        "overnight_low_dist_atr",
        "overnight_range_pct",
        "poc_dist_atr",
        "poc_rolling_dist_atr",
        "poc_session_rolling_divergence_atr",
        "pool_count",
        "price_in_value_area",
        "price_position",
        "prior_session_close_dist_atr",
        "prior_session_high_dist_atr",
        "prior_session_low_dist_atr",
        "rate_beta_z",
        "reclaim_velocity",
        "resistance_age_bars",
        "resistance_strength",
        "ret_div_1h_1d",
        "ret_div_1m_5m",
        "ret_div_5m_1h",
        "sb_corr_fast",
        "sb_corr_slow",
        "sb_corr_z",
        "smc_trend_direction",
        "sr_level_count",
        "sr_resist_dist",
        "sr_support_dist",
        "ssl_dist_atr",
        "ssl_touches",
        "struct_accel_bias",
        "struct_energy",
        "structure_integrity",
        "supply_dist_atr",
        "supply_freshness",
        "support_age_bars",
        "support_strength",
        "sweep_detected",
        "sweep_strength",
        "swing_amplitude_expanding",
        "swing_amplitude_intensity",
        "swing_amplitude_ratio",
        "swing_high_age_bars",
        "swing_high_dist_atr",
        "swing_high_type",
        "swing_low_age_bars",
        "swing_low_dist_atr",
        "swing_low_type",
        "swing_pattern",
        "swing_velocity_bars",
        "swing_velocity_bias",
        "swing_volume_confirmation",
        "tip_tlt_ret_z",
        "trend_direction",
        "trend_duration_bars",
        "trend_leg_count",
        "trend_strength",
        "va_position",
        "va_width_atr",
        "vix_reversion_product",
        "vix_z",
        "volatility_rank_z",
        "volume_rank_z",
        "weekly_pivot_dist_atr",
        "weekly_r1_dist_atr",
        "weekly_r2_dist_atr",
        "weekly_s1_dist_atr",
        "weekly_s2_dist_atr",
        "yield_slope_momentum_product",
        "yield_slope_z",
        "zone_friction_score",
    }
)


def test_every_numeric_column_is_owned_by_a_kernel_or_listed_as_remaining():
    numeric = set(MANIFEST["numeric_columns"])
    owned = set(default_registry().feature_columns())
    assert owned | REMAINING_COLUMNS == numeric
    assert not owned & REMAINING_COLUMNS


def synthetic_bars(n: int, seed: int = 42) -> dict[str, np.ndarray]:
    """Same generator order as the parity fixture's synthetic case, for any length."""
    rng = np.random.default_rng(seed)
    closes = np.cumprod(1.0 + rng.normal(0, 0.005, n)) * 100.0
    spread = closes * rng.uniform(0.001, 0.008, n)
    highs = closes + spread
    lows = closes - spread
    opens = closes + rng.normal(0, 0.003, n) * closes
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(1e5, 1e7, n)
    base = ref.dt_to_ns(datetime(2023, 1, 3, 14, 30, tzinfo=UTC))
    ts = base + np.arange(n, dtype=np.int64) * 5 * 60 * 1_000_000_000
    return {
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "symbol": np.array(["SPY"] * n, dtype=object),
    }


@lru_cache(maxsize=1)
def _synthetic_case():
    inputs, config = ref.synthetic_inputs()
    inputs = {**inputs, "symbol": np.array(["SPY"] * len(inputs["ts"]), dtype=object)}
    bars = ref._bars_from_arrays(
        *(inputs[f] for f in ("ts", "open", "high", "low", "close", "volume"))
    )
    results = FeatureFactory.compute_batch(
        bars, "SPY", "5m", FeatureCache(), config, warm_up_bars=0
    )
    batch = {
        name: np.array([getattr(fv, name) for _, fv in results], dtype=np.float64)
        for name in _ALL_COLUMN_NAMES
        if hasattr(results[0][1], name)
    }
    kernels = compute_kernels(default_registry(), inputs, config)
    return kernels, batch, len(inputs["ts"])


def test_feature_columns_are_persisted_columns():
    columns = default_registry().feature_columns()
    assert columns
    assert set(columns) <= set(_ALL_COLUMN_NAMES)


def test_kernel_outputs_equal_compute_batch_rows_1_onward():
    kernels, batch, n = _synthetic_case()
    columns = default_registry().feature_columns()
    for name in columns:
        assert name in batch, f"{name} is not a FeatureVector field"
        got = kernels[name][1:].astype(np.float32)
        want = batch[name].astype(np.float32)
        assert len(got) == len(want) == n - 1
        bad = ~((got == want) | (np.isnan(got) & np.isnan(want)))
        assert (
            not bad.any()
        ), f"{name}: row {int(np.argmax(bad)) + 1} got {got[bad][0]!r} want {want[bad][0]!r}"


def _code_lines(func) -> str:
    return "\n".join(
        line for line in inspect.getsource(func).splitlines() if not line.lstrip().startswith("#")
    )


def test_compute_batch_calls_no_delegated_helper():
    body = _code_lines(FeatureFactory.compute_batch)
    called = [name for name in DELEGATED_HELPERS if re.search(rf"(?<![A-Za-z0-9_]){name}\(", body)]
    assert called == []


# Kernels the probe proves acausal on today's code, moved unchanged by the code-only commits and
# fixed in their own behavior commits. Each entry is asserted to still FAIL the probe, so the
# fix commit must delete its entry (the probe is the regression test for the fix).
KNOWN_ACAUSAL: dict[str, str] = {
    "gap_z": "_gap_z_series_full assigns the z-score of bar i+1's gap to row i (off by one)",
}


@lru_cache(maxsize=2)
def _probe_case(config_key: str):
    config = ref.build_config(MANIFEST[config_key])
    available = synthetic_bars(PROBE_BARS)
    available.update(compute_kernels(default_registry(), available, config))
    return available, config


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
@pytest.mark.parametrize("kernel", default_registry().kernels, ids=lambda k: k.name)
def test_probe_and_memory_check_per_kernel(kernel, config_key):
    available, config = _probe_case(config_key)
    if kernel.acausal_control or kernel.name in KNOWN_ACAUSAL:
        with pytest.raises(CausalityViolation):
            causality_probe(kernel, available, config, PROBE_ROWS)
        return
    causality_probe(kernel, available, config, PROBE_ROWS)
    if kernel.path_dependent:
        assert kernel.name in PATH_DEPENDENT
        return
    assert kernel.name not in PATH_DEPENDENT
    memory_check(kernel, available, config, PROBE_ROWS)


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_probe_registry_statuses(config_key):
    """probe_registry over the whole registry, minus kernels listed as known acausal."""
    config = ref.build_config(MANIFEST[config_key])
    known = [name for name in KNOWN_ACAUSAL]
    registry = default_registry()
    kept = (
        KernelRegistry.from_kernels(
            [k for k in registry.kernels if k.name not in known], registry.external_inputs
        )
        if not known
        else None
    )
    if kept is None:
        pytest.skip("known acausal kernels are covered per kernel above")
    statuses = probe_registry(kept, synthetic_bars(PROBE_BARS), config, PROBE_ROWS)
    assert set(statuses.values()) <= {
        "ok",
        "path_dependent_skipped_memory",
        "acausal_control_detected",
    }
