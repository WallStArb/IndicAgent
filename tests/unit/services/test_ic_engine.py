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
    _earnings_season_labels,
    _lifecycle_guard_cells,
    _plan_season_subcells,
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


# ---------------------------------------------------------------------------
# Phase 176 plan 04 -- earnings_season stratification pass + label derivation
# ---------------------------------------------------------------------------


def _earnings_flag_column(values: list[float | None]) -> np.ndarray:
    """Build a float32 flag column the way the per-symbol fetch produces it:
    persisted 1.0/0.0 values, with NULL (pre-backfill) rows as NaN."""
    return np.array([np.nan if v is None else v for v in values], dtype=np.float32)


def test_earnings_season_labels_maps_flag_values_explicitly() -> None:
    """1.0 -> "in_season", 0.0 -> "off_season", NaN -> None. The mapping must
    never be reversed and must be a three-way mapping, not a two-way fill."""
    labels = _earnings_season_labels(_earnings_flag_column([1.0, 0.0, 1.0, 0.0]))
    assert list(labels) == ["in_season", "off_season", "in_season", "off_season"]


def test_earnings_season_labels_nan_maps_to_none_not_off_season() -> None:
    """NaN (pre-backfill NULL) must map to None -- excluded downstream -- never
    silently coerced into a valid season label the data does not support
    (T-176-04-01)."""
    labels = _earnings_season_labels(_earnings_flag_column([np.nan, 1.0, np.nan, 0.0]))
    assert labels[0] is None
    assert labels[1] == "in_season"
    assert labels[2] is None
    assert labels[3] == "off_season"


def test_earnings_season_labels_unexpected_value_maps_to_none() -> None:
    """Any value outside {0.0, 1.0} maps to None rather than silently landing on
    whichever label a two-way fill would have picked."""
    labels = _earnings_season_labels(_earnings_flag_column([2.0, -1.0]))
    assert labels[0] is None
    assert labels[1] is None


def test_earnings_season_labels_all_nan_column_is_all_none() -> None:
    """A fully-NULL flag column (pre-backfill corpus) maps to an all-None label
    array -- the pass construction must then skip the pass entirely."""
    labels = _earnings_season_labels(_earnings_flag_column([None, None, None]))
    assert all(entry is None for entry in labels)


def test_build_regime_passes_earnings_disabled_is_unchanged() -> None:
    """With earnings_season_conditioned=False the helper returns exactly the same
    passes it returned before Phase 176 -- byte-identical behavior, pinned by
    comparing scope strings, label sets and label arrays against the pre-176
    call shape."""
    regime_aligned_market = np.array(["breadth_vol_high", "breadth_vol_low", "breadth_vol_high"])
    distinct_regimes = ["breadth_vol_high", "breadth_vol_low"]
    regime_aligned = np.array(["calm", "elevated", "turbulent"])

    base = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
    )
    disabled = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
        earnings_season_aligned=np.array(["in_season", "off_season", "in_season"], dtype=object),
        earnings_season_conditioned=False,
    )

    assert len(base) == 2
    assert len(disabled) == len(base)
    for (base_arr, base_labels, base_scope), (dis_arr, dis_labels, dis_scope) in zip(
        base, disabled, strict=True
    ):
        assert base_scope == dis_scope
        assert set(base_labels) == set(dis_labels)
        assert list(base_arr) == list(dis_arr)


def test_build_regime_passes_appends_earnings_pass_once_with_labels() -> None:
    """With the switch on and a populated flag column, a third pass is appended
    with resolved_scope == "earnings_season" and exactly the {"in_season",
    "off_season"} distinct-label set -- exactly once, never duplicated by the
    cluster_regime_conditioned gate also being on."""
    regime_aligned_market = np.array(["breadth_vol_high", "breadth_vol_low", "breadth_vol_high"])
    distinct_regimes = ["breadth_vol_high", "breadth_vol_low"]
    regime_aligned = np.array(["calm", "elevated", "calm"])
    earnings_aligned = np.array(["in_season", "off_season", "in_season"], dtype=object)

    passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
        earnings_season_aligned=earnings_aligned,
        earnings_season_conditioned=True,
    )

    assert len(passes) == 3
    earnings_scopes = [scope for _, _, scope in passes if scope == "earnings_season"]
    assert earnings_scopes == ["earnings_season"]
    label_array, labels_this_pass, resolved_scope = passes[2]
    assert resolved_scope == "earnings_season"
    assert set(labels_this_pass) == {"in_season", "off_season"}
    assert list(label_array) == list(earnings_aligned)


def test_build_regime_passes_earnings_pass_not_gated_on_cross_sectional() -> None:
    """Unlike the symbol_hmm pass, the earnings pass is deliberately NOT gated on
    cross_sectional -- earnings season is a calendar axis orthogonal to
    regime-group routing -- so it appends on the non-cross-sectional per-symbol
    HMM path too."""
    regime_aligned_market = np.array(["calm", "elevated"])
    distinct_regimes = ["calm", "elevated"]
    regime_aligned = np.array(["calm", "elevated"])
    earnings_aligned = np.array(["in_season", "off_season"], dtype=object)

    passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=False,
        dual_write_symbol_hmm=False,
        cluster_regime_conditioned=False,
        primary_resolved_scope="symbol_hmm",
        earnings_season_aligned=earnings_aligned,
        earnings_season_conditioned=True,
    )

    assert [scope for _, _, scope in passes] == ["symbol_hmm", "earnings_season"]


def test_build_regime_passes_skips_earnings_pass_when_all_labels_none() -> None:
    """An all-None label array (flag column entirely NaN) appends no earnings pass
    at all -- a partially/never-backfilled corpus degrades to fewer passes, never
    to a pass with an empty label list."""
    regime_aligned_market = np.array(["calm", "elevated"])
    distinct_regimes = ["calm", "elevated"]
    regime_aligned = np.array(["calm", "elevated"])
    earnings_aligned = np.array([None, None], dtype=object)

    passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=True,
        primary_resolved_scope="cross_sectional",
        earnings_season_aligned=earnings_aligned,
        earnings_season_conditioned=True,
    )

    assert len(passes) == 2
    assert "earnings_season" not in {scope for _, _, scope in passes}


def test_build_regime_passes_earnings_labels_exclude_none_entries() -> None:
    """A partially-backfilled corpus (mixed 1.0/0.0/None) produces a distinct-label
    list containing only the real labels -- None entries are excluded exactly the
    way distinct_regimes excludes them."""
    earnings_aligned = np.array(["in_season", None, "off_season", None], dtype=object)

    passes = _build_regime_passes(
        np.array(["calm", "calm", "calm", "calm"]),
        ["calm"],
        np.array(["calm", "calm", "calm", "calm"]),
        cross_sectional=False,
        dual_write_symbol_hmm=False,
        cluster_regime_conditioned=False,
        primary_resolved_scope="symbol_hmm",
        earnings_season_aligned=earnings_aligned,
        earnings_season_conditioned=True,
    )

    assert len(passes) == 2
    _, labels_this_pass, _ = passes[1]
    assert set(labels_this_pass) == {"in_season", "off_season"}


def test_compute_symbol_tf_emits_earnings_season_skip_log_once() -> None:
    """A fully-NULL flag column skips the earnings pass with a single per-(symbol,
    tf) info log -- never per-row logging (CLAUDE.md hot-path rule)."""
    source = inspect.getsource(_compute_symbol_tf)
    assert "ic_engine.earnings_season_pass_skipped" in source


# ---------------------------------------------------------------------------
# Phase 176 plan 04 -- IC lifecycle guard exclusion (Task 2)
# ---------------------------------------------------------------------------


def _guard_row(regime: str, scope: str, status: str = "active") -> dict:
    """One synthetic feature_ic_scores cell row shaped like the lifecycle hook's
    cell_rows dicts (only the keys the guard selection reads)."""
    return {
        "feature_name": "up_vol_body_diff",
        "tf": "1d",
        "regime": regime,
        "regime_scope": scope,
        "feature_status_at_eval": status,
    }


def test_lifecycle_guard_cells_exclude_earnings_season_scope() -> None:
    """Cells carrying regime_scope == 'earnings_season' are filtered out before
    the guard's regime_label_to_group mapping runs -- they have no market_regimes
    row by construction and would otherwise raise a permanent false
    ic_engine.regime_label_unmapped data-contract violation (T-176-04-03)."""
    rows = [
        _guard_row("in_season", "earnings_season"),
        _guard_row("off_season", "earnings_season"),
        _guard_row("breadth_vol_high__in_season", "earnings_season"),
        _guard_row("calm", "symbol_hmm"),
    ]

    cells = _lifecycle_guard_cells(rows)

    assert [c["regime"] for c in cells] == ["calm"]


def test_lifecycle_guard_cells_keep_preexisting_scopes_routed() -> None:
    """Cells with the three pre-existing scopes are routed exactly as before the
    extraction (regression-pinned)."""
    rows = [
        _guard_row("trending_up", "cross_sectional"),
        _guard_row("calm", "symbol_hmm"),
        _guard_row("breadth_vol_high", "cross_sectional"),
    ]

    cells = _lifecycle_guard_cells(rows)

    assert len(cells) == 3
    assert {c["regime_scope"] for c in cells} == {"cross_sectional", "symbol_hmm"}


def test_lifecycle_guard_cells_still_require_active_status() -> None:
    """The feature_status_at_eval == 'active' predicate is preserved alongside the
    new scope exclusion."""
    rows = [
        _guard_row("calm", "symbol_hmm", status="demoted"),
        _guard_row("calm", "symbol_hmm", status="active"),
        _guard_row("in_season", "earnings_season", status="active"),
    ]

    cells = _lifecycle_guard_cells(rows)

    assert len(cells) == 1
    assert cells[0]["regime_scope"] == "symbol_hmm"
    assert cells[0]["feature_status_at_eval"] == "active"


def test_lifecycle_guard_cells_filter_by_scope_value_not_label_string() -> None:
    """The exclusion keys on the regime_scope VALUE -- never on matching the
    label strings, so the helper's source contains the scope token but none of
    the bare season-label strings (a future scope carrying the same labels must
    still route through the guard)."""
    source = inspect.getsource(_lifecycle_guard_cells)
    assert "earnings_season" in source
    assert "in_season" not in source
    assert "off_season" not in source


# ---------------------------------------------------------------------------
# Phase 176 plan 06 -- cross-sectional season sub-cell planner
# (_plan_season_subcells), DB-free
# ---------------------------------------------------------------------------


def test_plan_season_subcells_returns_two_entries_when_both_seasons_present() -> None:
    """Both values present, enabled, in-RAM -> two entries, in in_season/off_season
    order, each mask selecting exactly its own season's rows."""
    flag_column = _earnings_flag_column([1.0, 0.0, 1.0, 0.0, 1.0, 0.0])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=False, min_rows=1
    )

    assert skipped == []
    assert [label for _, label in entries] == ["calm__in_season", "calm__off_season"]
    in_mask, _ = entries[0]
    off_mask, _ = entries[1]
    assert list(in_mask) == [True, False, True, False, True, False]
    assert list(off_mask) == [False, True, False, True, False, True]


def test_plan_season_subcells_disk_backed_skips_with_reason() -> None:
    """use_disk=True -> no sub-cells, skip reason 'disk_backed_cell' -- the memory
    guard (T-176-06-01): the parent cell is already at the memory ceiling."""
    flag_column = _earnings_flag_column([1.0, 0.0])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=True, min_rows=1
    )

    assert entries == []
    assert skipped == ["disk_backed_cell"]


def test_plan_season_subcells_apr_disabled_skips_with_reason() -> None:
    """enabled=False (alpha.ic.earnings_season_conditioned off) -> no sub-cells,
    skip reason 'apr_disabled'."""
    flag_column = _earnings_flag_column([1.0, 0.0])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=False, use_disk=False, min_rows=1
    )

    assert entries == []
    assert skipped == ["apr_disabled"]


def test_plan_season_subcells_all_null_flag_column_skips_with_reason() -> None:
    """An entirely-NaN flag column (pre-backfill corpus) -> no sub-cells, skip
    reason 'flag_column_all_null'."""
    flag_column = _earnings_flag_column([None, None, None])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=False, min_rows=1
    )

    assert entries == []
    assert skipped == ["flag_column_all_null"]


def test_plan_season_subcells_drops_only_the_below_min_n_season() -> None:
    """One season below min_rows is dropped individually -- the other season is
    still returned when it clears the bar."""
    flag_column = _earnings_flag_column([1.0, 1.0, 1.0, 1.0, 1.0, 0.0])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=False, min_rows=2
    )

    assert [label for _, label in entries] == ["calm__in_season"]
    assert skipped == ["subset_below_min_n"]


def test_plan_season_subcells_both_below_min_n_drops_both() -> None:
    """Both seasons below min_rows -> no entries, two independent skip reasons."""
    flag_column = _earnings_flag_column([1.0, 0.0])

    entries, skipped = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=False, min_rows=5
    )

    assert entries == []
    assert skipped == ["subset_below_min_n", "subset_below_min_n"]


def test_plan_season_subcells_labels_are_parent_qualified() -> None:
    """Labels are always '{parent}__in_season'/'{parent}__off_season' -- never a
    bare 'in_season'/'off_season' (feature_ic_scores ON CONFLICT collision
    guard, T-176-06-02)."""
    flag_column = _earnings_flag_column([1.0, 0.0])

    entries, _ = _plan_season_subcells(
        flag_column, "breadth_vol_high", enabled=True, use_disk=False, min_rows=1
    )

    labels = [label for _, label in entries]
    assert labels == ["breadth_vol_high__in_season", "breadth_vol_high__off_season"]
    for label in labels:
        assert label not in ("in_season", "off_season")
        assert "__" in label


def test_plan_season_subcells_masks_disjoint_and_exclude_only_nan_rows() -> None:
    """The two returned masks are disjoint and their union excludes only the
    NaN-flag row."""
    flag_column = _earnings_flag_column([1.0, 0.0, None, 1.0])

    entries, _ = _plan_season_subcells(
        flag_column, "calm", enabled=True, use_disk=False, min_rows=1
    )

    in_mask, _ = entries[0]
    off_mask, _ = entries[1]
    assert not np.any(in_mask & off_mask)
    assert list(in_mask | off_mask) == [True, True, False, True]


def test_plan_season_subcells_calls_earnings_season_labels_not_restated() -> None:
    """Component-reuse discipline (D-03): the helper must call
    _earnings_season_labels rather than re-deriving the 1.0/0.0/NaN mapping
    inline."""
    source = inspect.getsource(_plan_season_subcells)
    assert "_earnings_season_labels(" in source
