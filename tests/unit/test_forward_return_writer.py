"""Unit test: forward_log_return formula correctness and no-lookahead-bias.

Verifies that forward_return_writer.forward_log_return():
  1. Computes ln(open[T+N+1] / open[T+1]) -- entry at T+1, exit at T+N+1.
     NOT ln(open[T+N] / open[T]). The extra +1 shift is the key correctness
     invariant from IC spec §V (executable causal forward returns).
  2. Last n rows are NaN (no complete forward return available).
  3. No lookahead: forward return at T uses only opens at indices > T.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.forward_return_writer import (
    _SCALES,
    _apply_cross_symbol_corroboration,
    _build_corroboration_sql,
    _build_forward_return_sql,
    _build_insert_sql,
    _emit_price_sanity_fact,
    forward_log_return,
)
from src.intelligence.statistics.ic_math import scale_max_abs_return


def _make_opens(n: int = 100, seed: int = 42) -> np.ndarray:
    """Synthetic open price series: random walk starting at 100."""
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(0.0, 0.01, n - 1)
    opens = np.empty(n)
    opens[0] = 100.0
    for i in range(1, n):
        opens[i] = opens[i - 1] * np.exp(log_returns[i - 1])
    return opens


def test_forward_log_return_formula_interior_bar():
    """At interior bar T, return = ln(opens[T+N+1] / opens[T+1]), not T+N/T."""
    opens = _make_opens(100)
    n_lookahead = 5

    result = forward_log_return(opens, n_lookahead)

    # Check an interior bar T=10
    T = 10
    expected = np.log(opens[T + n_lookahead + 1] / opens[T + 1])
    actual = result[T]
    assert abs(actual - expected) < 1e-12, (
        f"T={T}, n={n_lookahead}: expected ln(opens[{T+n_lookahead+1}]/opens[{T+1}]) "
        f"= {expected:.10f}, got {actual:.10f}"
    )


def test_forward_log_return_uses_T_plus_2_open_for_n1():
    """For n=1 (fast lookahead), return[T] = ln(opens[T+2] / opens[T+1])."""
    opens = _make_opens(100)
    n_lookahead = 1

    result = forward_log_return(opens, n_lookahead)

    # For n=1: T+N+1 = T+2, T+1 = T+1
    for T in [5, 10, 20, 50]:
        expected = np.log(opens[T + 2] / opens[T + 1])
        actual = result[T]
        assert abs(actual - expected) < 1e-12, (
            f"n=1, T={T}: expected ln(opens[{T+2}]/opens[{T+1}])={expected:.10f}, "
            f"got {actual:.10f}"
        )


def test_forward_log_return_last_n_rows_are_nan():
    """Last n rows must be NaN (no complete forward return)."""
    opens = _make_opens(100)
    n_lookahead = 5

    result = forward_log_return(opens, n_lookahead)

    # Last n rows: T where T+n+1 >= len(opens), i.e. T >= len(opens)-n-1
    m = len(opens)
    # The last valid T is m-n-2 (result[m-n-1] onwards are NaN)
    # result[m-n-1] through result[m-1] should be NaN (n+1 trailing NaNs? Let me check)
    # valid_end = m - n - 1 so result[valid_end:] = result[m-n-1:] are all NaN
    nan_region = result[m - n_lookahead - 1 :]
    assert (
        len(nan_region) >= n_lookahead
    ), f"Expected at least {n_lookahead} NaN rows at end, got {len(nan_region)}"
    assert np.all(
        np.isnan(nan_region)
    ), f"Last {len(nan_region)} rows should all be NaN, got: {nan_region}"


def test_forward_log_return_no_lookahead():
    """Forward return at T uses only opens at indices > T (no lookahead bias).

    Proof: result[T] = ln(opens[T+n+1] / opens[T+1]).
    Both T+1 and T+n+1 are strictly > T. Modifying opens[0..T] does not
    change result[T] (only the entry and exit prices matter).
    """
    opens_original = _make_opens(100)
    n_lookahead = 5

    result_original = forward_log_return(opens_original, n_lookahead)

    # Corrupt all opens at indices <= T -- this must not affect result[T]
    T = 20
    opens_corrupted = opens_original.copy()
    opens_corrupted[: T + 1] = 999.0  # replace opens[0..T] with garbage

    result_corrupted = forward_log_return(opens_corrupted, n_lookahead)

    # result[T] must be unchanged because it only uses opens[T+1] and opens[T+n+1]
    # which are at indices > T and were not corrupted
    assert abs(result_original[T] - result_corrupted[T]) < 1e-12, (
        f"Lookahead detected: corrupting opens[0..{T}] changed result[{T}] "
        f"from {result_original[T]:.10f} to {result_corrupted[T]:.10f}"
    )


def test_forward_log_return_output_length():
    """Output length must equal input length."""
    opens = _make_opens(100)
    result = forward_log_return(opens, n=5)
    assert len(result) == len(opens), f"Expected output length {len(opens)}, got {len(result)}"


def test_forward_log_return_finite_for_valid_bars():
    """Interior bars with valid prices must produce finite (non-NaN) results."""
    opens = _make_opens(100)
    n_lookahead = 1

    result = forward_log_return(opens, n_lookahead)

    # Bars 0 through m-n-2 should be finite
    m = len(opens)
    valid_end = m - n_lookahead - 1
    valid_region = result[:valid_end]
    assert np.all(
        np.isfinite(valid_region)
    ), f"Non-finite values in valid region: {np.where(~np.isfinite(valid_region))}"


def test_forward_log_return_not_same_bar_ratio():
    """Verify formula is NOT ln(opens[T+N] / opens[T]) -- the naive (wrong) form."""
    opens = _make_opens(100)
    n_lookahead = 5

    result = forward_log_return(opens, n_lookahead)

    # For T=10: wrong formula would be ln(opens[15]/opens[10])
    T = 10
    wrong_formula = np.log(opens[T + n_lookahead] / opens[T])
    correct_formula = np.log(opens[T + n_lookahead + 1] / opens[T + 1])

    assert abs(result[T] - correct_formula) < 1e-12, "Result does not match correct formula"
    assert (
        abs(result[T] - wrong_formula) > 1e-10
    ), "Result matches WRONG formula ln(opens[T+N]/opens[T]) -- check implementation"


# ---------------------------------------------------------------------------
# Price-sanity guard SQL structure (todo 148)
# ---------------------------------------------------------------------------

_LOOKAHEADS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}


def test_forward_return_sql_emits_suspect_flag_per_scale():
    """Every scale gets its own return_{scale}_suspect column, gated on its own
    %(max_abs_return_{scale})s param -- not a single row-level flag (a corrupt exit
    price for one scale must not mark other scales' returns, which use a different
    exit bar, as suspect) and not a single shared ceiling (see
    test_scale_max_abs_return_* below for why a flat ceiling is wrong)."""
    sql = _build_forward_return_sql(_LOOKAHEADS, "5m")
    for scale in _LOOKAHEADS:
        assert f"return_{scale}_suspect" in sql
        assert f"abs(return_{scale}) > %(max_abs_return_{scale})s" in sql


def test_scale_max_abs_return_fast_baseline_unchanged():
    """The fast scale (1 bar, the APR-seeded baseline) must scale to itself."""
    scaled = scale_max_abs_return(0.25, _LOOKAHEADS)
    assert scaled["fast"] == 0.25


def test_scale_max_abs_return_grows_with_horizon():
    """Longer lookaheads get a wider ceiling (sqrt(n) volatility scaling) -- a flat
    ceiling applied uniformly false-flags real multi-month ETF moves at slow/extended
    horizons (verified live: 2,102 false positives on EWZ/XOP/OIH/GDX/AMLP 1d-extended
    rows before this fix, vs. 16 true positives isolating the known UUP/ITA corrupt-
    print cluster after it)."""
    scaled = scale_max_abs_return(0.25, _LOOKAHEADS)
    assert scaled["fast"] < scaled["mid"] < scaled["slow"] < scaled["extended"]


def test_scale_max_abs_return_matches_sqrt_law():
    scaled = scale_max_abs_return(0.25, _LOOKAHEADS)
    assert abs(scaled["extended"] - 0.25 * (60**0.5)) < 1e-9


def test_forward_return_sql_suspect_flag_references_materialized_return():
    """Suspect flags must read the `returns` CTE's already-computed return_{scale}
    column, not re-derive from open_entry/open_{scale} -- Postgres SELECT-list
    aliases aren't visible to sibling expressions at the same query level, so the
    suspect predicate has to live in the outer SELECT over the `returns` CTE."""
    sql = _build_forward_return_sql(_LOOKAHEADS, "1d")
    assert "returns AS (" in sql
    assert sql.index("FROM returns") > sql.index("return_fast_suspect")


def test_insert_sql_includes_suspect_columns_and_params():
    sql = _build_insert_sql(("fast", "mid", "slow", "extended"))
    for scale in _LOOKAHEADS:
        assert f"return_{scale}_suspect" in sql
        assert f"%(return_{scale}_suspect)s" in sql


def test_corroboration_sql_targets_correct_suspect_column():
    """Each scale's corroboration UPDATE must target its OWN return_{scale}_suspect
    column -- a corroboration event on return_fast must not accidentally clear
    return_slow_suspect for the same row (the two scales can have independent
    plausibility verdicts, same as todo 148's original per-scale design)."""
    for scale in ("fast", "mid", "slow", "extended"):
        sql = _build_corroboration_sql(scale)
        assert sql.count(f"return_{scale}_suspect") >= 3  # HAVING gate, SET, WHERE
        for other in ("fast", "mid", "slow", "extended"):
            if other != scale:
                assert f"return_{other}_suspect" not in sql


def test_corroboration_sql_groups_by_tf_and_bar_ts():
    """Corroboration is per (tf, bar_ts) -- a 5m bar and a 1h bar at an overlapping
    wall-clock instant must not cross-contaminate each other's symbol count."""
    sql = _build_corroboration_sql("fast")
    assert "GROUP BY tf, bar_ts" in sql
    assert "count(DISTINCT symbol)" in sql


def test_corroboration_sql_scoped_to_executable_return_type():
    sql = _build_corroboration_sql("fast")
    assert sql.count("executable_open_to_open") >= 2  # CTE filter + UPDATE filter


def _mock_conn_for_corroboration(rowcounts: dict[str, int]) -> MagicMock:
    """A conn whose cursor.rowcount cycles through rowcounts[scale] in call order."""
    cur = MagicMock()
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    rowcount_iter = iter(rowcounts.values())

    def _execute(*_args, **_kwargs):
        cur.rowcount = next(rowcount_iter)

    cur.execute.side_effect = _execute
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_apply_cross_symbol_corroboration_returns_cleared_counts_per_scale():
    conn = _mock_conn_for_corroboration({"fast": 0, "mid": 2, "slow": 4, "extended": 0})
    tracer = MagicMock()

    cleared = _apply_cross_symbol_corroboration(conn, _SCALES, min_symbols=4, tracer=tracer)

    assert cleared == {"fast": 0, "mid": 2, "slow": 4, "extended": 0}
    conn.commit.assert_called_once()


def test_apply_cross_symbol_corroboration_passes_min_symbols_param():
    conn = _mock_conn_for_corroboration({"fast": 0, "mid": 0, "slow": 0, "extended": 0})
    tracer = MagicMock()

    _apply_cross_symbol_corroboration(conn, _SCALES, min_symbols=7, tracer=tracer)

    for call in conn.cursor.return_value.execute.call_args_list:
        params = call.args[1]
        assert params["min_symbols"] == 7


def _mock_conn_with_precheck_result(already_ran: bool) -> MagicMock:
    cur = MagicMock()
    cur.fetchone.return_value = (1,) if already_ran else None
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_emit_price_sanity_fact_skips_insert_when_already_ran():
    """Idempotency pre-check (mirrors ic_engine.py's _run_lifecycle_hook Step 0):
    evaluated_at defaults to now() and is part of the table's composite unique key,
    so ON CONFLICT alone doesn't dedupe a rerun of the same training_window_end
    minutes/hours later -- an explicit pre-check is required, same as ic_lifecycle."""
    conn = _mock_conn_with_precheck_result(already_ran=True)

    _emit_price_sanity_fact(conn, total_suspect=5, training_window_end="2026-01-01T00:00:00+00:00")

    # Only the pre-check SELECT ran (one cursor use) -- no INSERT, no commit.
    assert conn.cursor.call_count == 1
    conn.commit.assert_not_called()


def test_emit_price_sanity_fact_inserts_when_not_already_ran():
    conn = _mock_conn_with_precheck_result(already_ran=False)

    _emit_price_sanity_fact(conn, total_suspect=5, training_window_end="2026-01-01T00:00:00+00:00")

    # Pre-check SELECT + INSERT -- two cursor uses -- and the insert is committed.
    assert conn.cursor.call_count == 2
    conn.commit.assert_called_once()
