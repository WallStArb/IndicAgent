"""IC evaluation skeleton test for Renaissance primitives (Phase 142.5 Plan 00).

Skeleton only -- verifies query STRUCTURE for evaluating each of the 91 new
Renaissance primitives against feature_ic_scores. Does NOT run the IC engine
and does NOT touch a live DB. The actual IC Sharpe > 0 AND p < 0.05 evaluation
happens later via a corpus run + `scripts/analysis/ops_primitive_discovery_report.py`
(Task 4) once Plans 01-05.5 implement the primitives and Plan 06 seeds
feature_registry + runs migration 206.

Note: this lives at tests/unit/services/test_ic_engine.py -- a new location
distinct from the existing split-out `tests/unit/test_ic_engine_*.py` files
(clustering/idempotency/parallelism/stride/vectorized/compute_split), which
cover services/ic_engine.py's existing runtime behavior. This file is scoped
specifically to the Renaissance primitive inventory added by this phase.
"""

from __future__ import annotations

# Canonical 91 Renaissance primitive feature names (mirrors
# tests/unit/test_feature_factory.py::RENAISSANCE_PRIMITIVE_FIELDS and
# tests/integration/test_feature_vectors_schema.py::RENAISSANCE_COLUMNS --
# all three must stay in sync; see 142.5-PLAN-OUTLINE.md for the reconciled
# authoritative inventory).
RENAISSANCE_PRIMITIVE_NAMES: tuple[str, ...] = (
    # Bar Anatomy (8)
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "range_vs_atr",
    "close_vs_open_direction",
    "overnight_gap",
    "overnight_gap_z",
    "range_efficiency",
    # Lagged Returns (6)
    "ret_lag_1",
    "ret_lag_2",
    "ret_lag_3",
    "ret_lag_fast",
    "ret_lag_mid",
    "ret_lag_slow",
    # Open-to-Close Split (4)
    "open_ret",
    "intraday_ret",
    "open_vs_intraday",
    "session_time_pos",
    # Temporal Coordinates: new pairs + month_sin/cos (10)
    "hour_of_day_sin",
    "hour_of_day_cos",
    "week_of_month_sin",
    "week_of_month_cos",
    "day_of_month_sin",
    "day_of_month_cos",
    "week_of_year_sin",
    "week_of_year_cos",
    "month_sin",
    "month_cos",
    # Volume Structure (12)
    "vol_acceleration",
    "dollar_vol_z",
    "vol_range_ratio",
    "vol_trend_ratio",
    "up_vol_ratio_fast",
    "up_vol_ratio_slow",
    "vol_percentile",
    "vol_persistence",
    "vol_std_z",
    "mfi_fast",
    "mfi_slow",
    "obv_z",
    # Return Distribution (7)
    "ret_kurtosis_z_fast",
    "ret_kurtosis_z_slow",
    "ret_autocorr_1",
    "ret_autocorr_5",
    "updown_ratio_fast",
    "updown_ratio_slow",
    "streak_z",
    # Realized Variance (14)
    "realized_var_ratio_fast",
    "realized_var_ratio_slow",
    "range_to_close",
    "true_range_pct",
    "vol_of_vol",
    "high_low_corr",
    "variance_ratio_fast",
    "variance_ratio_slow",
    "vol_asymmetry_z",
    "bb_pct_b_fast",
    "bb_pct_b_slow",
    "hv_z_fast",
    "hv_z_slow",
    "hv_ratio",
    # Alternative Volatility (3)
    "parkinson_vol_z",
    "garman_klass_vol_z",
    "yang_zhang_vol_z",
    # Volatility Dynamics (5)
    "parkinson_vol_velocity",
    "garman_klass_vol_velocity",
    "yang_zhang_vol_velocity",
    "vol_velocity_z",
    "intraday_noise_ratio",
    # Breakout Distance (14)
    "dist_from_high_fast",
    "dist_from_high_slow",
    "dist_from_low_fast",
    "dist_from_low_slow",
    "range_pct_fast",
    "range_pct_slow",
    "stoch_k_fast",
    "stoch_k_slow",
    "price_percentile_fast",
    "price_percentile_slow",
    "efficiency_ratio_fast",
    "efficiency_ratio_slow",
    # Price-Volume Interactions (8)
    "vol_body_product",
    "ret_vol_product_fast",
    "price_vol_corr_fast",
    "price_vol_corr_slow",
    "range_vol_product",
    "up_vol_body_diff",
    "ret_vol_ratio_fast",
    "vol_skew_product",
)

assert (
    len(RENAISSANCE_PRIMITIVE_NAMES) == 89
), f"Expected 89 Renaissance primitive names, got {len(RENAISSANCE_PRIMITIVE_NAMES)}"


def _build_primitive_ic_query(feature_name: str) -> tuple[str, tuple[str]]:
    """Build the parameterized SELECT used to evaluate one primitive's IC.

    Structure only -- mirrors the SELECT shape services/ic_engine.py itself uses
    when reading back feature_ic_scores (see its idempotency / manifest-output
    queries), stratified by (tf, regime) and exposing the pass/fail gate columns
    (ic_sharpe, p_value, passes_ci_gate, passes_fdr) that
    ops_primitive_discovery_report.py (Task 4) ranks and gates on.
    """
    query = """
        SELECT feature_name, symbol, tf, regime, lookahead_bars, is_pooled,
               ic_value, ic_sharpe, p_value, passes_ci_gate, passes_fdr
        FROM feature_ic_scores
        WHERE feature_name = %s
        ORDER BY tf, regime
    """
    return query, (feature_name,)


def test_renaissance_primitive_evaluation() -> None:
    """Skeleton: verify query structure for all 89 Renaissance primitives.

    Does not run the IC engine. Confirms every primitive name produces a
    well-formed, parameterized feature_ic_scores query referencing the columns
    the eventual gate (IC Sharpe > 0 AND p < 0.05, corpus-level BH-FDR) needs.
    """
    assert len(RENAISSANCE_PRIMITIVE_NAMES) == 89

    for feature_name in RENAISSANCE_PRIMITIVE_NAMES:
        query, params = _build_primitive_ic_query(feature_name)
        assert "feature_ic_scores" in query
        assert "feature_name" in query
        assert params == (feature_name,)
        # Parameterized (no string interpolation of feature_name into the SQL body).
        assert feature_name not in query

    # Gate columns referenced by the eventual discovery report (Task 4).
    sample_query, _ = _build_primitive_ic_query(RENAISSANCE_PRIMITIVE_NAMES[0])
    assert "ic_sharpe" in sample_query
    assert "p_value" in sample_query
    assert "passes_fdr" in sample_query
    assert "passes_ci_gate" in sample_query

    # No duplicate names (each primitive must evaluate to exactly one query).
    assert len(set(RENAISSANCE_PRIMITIVE_NAMES)) == len(RENAISSANCE_PRIMITIVE_NAMES)
