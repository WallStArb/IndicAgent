"""IC evaluation skeleton test for Renaissance primitives (Phase 142.5 Plan 00).

Skeleton only -- verifies query STRUCTURE for evaluating each of the 91 new
Renaissance primitives against feature_ic_scores. Does NOT run the IC engine
and does NOT touch a live DB. The actual IC Sharpe > 0 AND p < 0.05 evaluation
happens via a corpus run + the `feature_edge_by_regime`/`feature_edge_by_symbol`
views (migration 297) once Plans 01-05.5 implement the primitives and Plan 06
seeds feature_registry + runs migration 206. (The originally-planned Task 4
report generator, `scripts/analysis/ops_primitive_discovery_report.py`, was
deleted 2026-08-21, todo 251 -- migration 297's views supersede it, never
implemented beyond a skeleton.)

Note: this lives at tests/unit/services/test_ic_engine.py -- a new location
distinct from the existing split-out `tests/unit/test_ic_engine_*.py` files
(clustering/idempotency/parallelism/stride/vectorized/compute_split), which
cover services/ic_engine.py's existing runtime behavior. This file is scoped
specifically to the Renaissance primitive inventory added by this phase.

Also carries new `_assert_prerequisites` coverage (Phase 172 plan 06, Task 1)
-- this function had no prior test coverage in this file or any of the
split-out `test_ic_engine_*.py` files. And new `_compute_symbol_tf`
feature-matrix SQL + `_build_regime_passes` coverage (Phase 172 plan 06,
Task 2).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from services.ic_engine import (  # noqa: E402
    _assert_prerequisites,
    _build_regime_passes,
    _compute_symbol_tf,
)

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
    (ic_sharpe, p_value, passes_ci_gate, passes_fdr) that the
    `feature_edge_by_regime`/`feature_edge_by_symbol` views (migration 297)
    rank and gate on.
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


def _mock_conn_for_prerequisites(counts: list[int]) -> MagicMock:
    """Build a mock connection whose cursor().fetchone() yields `counts` in order.

    `_assert_prerequisites` opens a fresh `with conn.cursor() as cur:` block per
    gate query, so the mock cursor's context-manager protocol must return itself
    on __enter__, and fetchone() must advance through `counts` one call at a time
    (feature_vectors count, then the regime/regime_volatility count, then
    forward_returns count -- in that fixed order).
    """
    cur = MagicMock()
    cur.fetchone.side_effect = [(c,) for c in counts]
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_assert_prerequisites_fails_on_volatility_all_null() -> None:
    """Gate raises RuntimeError naming regime_volatility when that column is all-NULL.

    feature_vectors count is non-zero (gate 1 passes); the second gate's count
    (now regime_volatility, not legacy regime) is zero -- must raise, and the
    message must name feature_vectors.regime_volatility and the
    --regime-column regime_volatility remedy, not the legacy column.
    """
    conn = _mock_conn_for_prerequisites([100, 0])
    with pytest.raises(RuntimeError) as exc_info:
        _assert_prerequisites(conn, tfs=None, equity_model_enabled=True, group_configs=None)
    message = str(exc_info.value)
    assert "regime_volatility" in message
    assert "regime_writer.py --regime-column regime_volatility" in message


def test_assert_prerequisites_passes_when_volatility_populated() -> None:
    """Gate passes (no raise before the forward_returns check) when the second
    gate's count (regime_volatility, post-cutover) is non-zero."""
    conn = _mock_conn_for_prerequisites([100, 50, 200])
    _assert_prerequisites(conn, tfs=None, equity_model_enabled=True, group_configs=None)


def test_compute_symbol_tf_feature_matrix_sql_selects_regime_volatility() -> None:
    """The per-symbol feature-matrix fv_sql select list must read
    regime_volatility, not the legacy feature_vectors.regime column.

    Source-inspection test (mirrors Task 1's _assert_prerequisites gate check)
    rather than standing up the full compute path -- fv_sql is built inline
    inside _compute_symbol_tf from a live DB connection, and the plan
    explicitly prefers testing the SQL string over a live-DB integration test
    here.
    """
    source = inspect.getsource(_compute_symbol_tf)
    assert "SELECT bar_ts, regime_volatility," in source
    assert "SELECT bar_ts, regime," not in source


def test_build_regime_passes_symbol_hmm_pass_carries_volatility_labels() -> None:
    """_build_regime_passes' symbol_hmm pass type is unchanged (Task 2 leaves
    _resolve_regime_scope's return values alone) but the label array it wraps
    is regime_aligned -- which Task 2 repoints to carry
    calm/elevated/turbulent volatility labels once _compute_symbol_tf's fetch
    is repointed. This test drives the pure helper directly with a
    volatility-label array and asserts the pass type and distinct labels.
    """
    regime_aligned_market = np.array(["breadth_vol_high", "breadth_vol_low", "breadth_vol_high"])
    distinct_regimes = ["breadth_vol_high", "breadth_vol_low"]
    regime_aligned = np.array(["calm", "elevated", "turbulent"])

    passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=False,
        primary_resolved_scope="cross_sectional",
    )

    assert len(passes) == 2
    primary_label_array, primary_labels, primary_scope = passes[0]
    assert primary_scope == "cross_sectional"
    assert set(primary_labels) == set(distinct_regimes)

    symbol_hmm_label_array, symbol_hmm_labels, symbol_hmm_scope = passes[1]
    assert symbol_hmm_scope == "symbol_hmm"
    assert set(symbol_hmm_labels) == {"calm", "elevated", "turbulent"}
    assert list(symbol_hmm_label_array) == list(regime_aligned)
