"""Unit tests: OOS holdout eval harness pure helpers + canonical return reuse.

Tests verify:
  1. The harness reuses the canonical forward_log_return() from
     services.forward_return_writer (Invariant 1: ln(open[T+N+1] / open[T+1])) rather
     than reimplementing the executable-return formula.
  2. _oos_mask() selects only bars with bar_ts >= a given boundary.
  3. _count_qualifying() counts cells where ic_ci_lower > 0 AND passes_fdr is true.

No DB, no Kafka. Pure numpy/pure python.
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.forward_return_writer import forward_log_return


def test_forward_log_return_matches_executable_formula():
    """forward_log_return must yield ln(open[T+N+1] / open[T+1]) to within 1e-9.

    This documents that the OOS harness reuses the canonical helper rather than
    reimplementing the executable-return formula (CLAUDE.md Invariant 1).
    """
    opens = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    n = 2

    result = forward_log_return(opens, n)

    # T=0: entry at opens[1]=101.0, exit at opens[3]=103.0
    expected_0 = np.log(103.0 / 101.0)
    assert abs(result[0] - expected_0) < 1e-9

    # T=1: entry at opens[2]=102.0, exit at opens[4]=104.0
    expected_1 = np.log(104.0 / 102.0)
    assert abs(result[1] - expected_1) < 1e-9

    # T=2: entry at opens[3]=103.0, exit at opens[5]=105.0
    expected_2 = np.log(105.0 / 103.0)
    assert abs(result[2] - expected_2) < 1e-9


def test_forward_log_return_nan_where_insufficient_forward_bars():
    """The tail of the series (insufficient forward bars) must be NaN, not a lookahead value."""
    opens = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    n = 2
    result = forward_log_return(opens, n)

    # m=5, n=2 -> valid_end = m - n - 1 = 2, so indices >= 2 are NaN
    assert np.isnan(result[2])
    assert np.isnan(result[3])
    assert np.isnan(result[4])


def test_oos_mask_selects_bars_at_or_after_boundary():
    from scripts.ops.corpus.ops_oos_holdout_eval import _oos_mask

    boundary = datetime(2025, 12, 24, 5, 15, 0, tzinfo=UTC)
    bar_ts_arr = np.array(
        [
            boundary - timedelta(days=1),
            boundary - timedelta(seconds=1),
            boundary,
            boundary + timedelta(seconds=1),
            boundary + timedelta(days=1),
        ],
        dtype=object,
    )

    mask = _oos_mask(bar_ts_arr, boundary)

    np.testing.assert_array_equal(mask, np.array([False, False, True, True, True]))


def test_oos_mask_empty_array_returns_empty_mask():
    from scripts.ops.corpus.ops_oos_holdout_eval import _oos_mask

    boundary = datetime(2025, 12, 24, 5, 15, 0, tzinfo=UTC)
    bar_ts_arr = np.array([], dtype=object)

    mask = _oos_mask(bar_ts_arr, boundary)

    assert mask.shape == (0,)
    assert mask.dtype == bool


def test_count_qualifying_requires_both_conditions():
    from scripts.ops.corpus.ops_oos_holdout_eval import _count_qualifying

    ci_lower = np.array([0.05, -0.01, 0.10, 0.02, np.nan])
    passes_fdr = np.array([True, True, False, True, True])

    # Qualifying: index 0 (ci_lower>0 & fdr) and index 3 (ci_lower>0 & fdr).
    # Index 1: ci_lower <= 0. Index 2: fdr False. Index 4: ci_lower is NaN (not > 0).
    count = _count_qualifying(ci_lower, passes_fdr)

    assert count == 2


def test_count_qualifying_zero_when_all_fail():
    from scripts.ops.corpus.ops_oos_holdout_eval import _count_qualifying

    ci_lower = np.array([-0.1, -0.2, 0.0])
    passes_fdr = np.array([True, True, True])

    count = _count_qualifying(ci_lower, passes_fdr)

    assert count == 0


def test_count_qualifying_empty_arrays():
    from scripts.ops.corpus.ops_oos_holdout_eval import _count_qualifying

    count = _count_qualifying(np.array([]), np.array([]))

    assert count == 0


def test_drop_verdict_no_in_sample_baseline():
    from scripts.ops.corpus.ops_oos_holdout_eval import _drop_verdict

    assert _drop_verdict(oos_qualifying=0, in_sample=0, significant_drop_fraction=0.5) == (
        "no in-sample baseline"
    )


def test_drop_verdict_severe_drop_when_oos_zero_and_in_sample_positive():
    from scripts.ops.corpus.ops_oos_holdout_eval import _drop_verdict

    verdict = _drop_verdict(oos_qualifying=0, in_sample=10, significant_drop_fraction=0.5)

    assert verdict == "SEVERE DROP — possible overfitting"


def test_drop_verdict_significant_drop_below_fraction():
    from scripts.ops.corpus.ops_oos_holdout_eval import _drop_verdict

    # 4 < 10 * 0.5 -> significant drop
    verdict = _drop_verdict(oos_qualifying=4, in_sample=10, significant_drop_fraction=0.5)

    assert verdict == "significant drop — investigate"


def test_drop_verdict_consistent_at_or_above_fraction():
    from scripts.ops.corpus.ops_oos_holdout_eval import _drop_verdict

    # 5 >= 10 * 0.5 -> consistent
    verdict = _drop_verdict(oos_qualifying=5, in_sample=10, significant_drop_fraction=0.5)

    assert verdict == "consistent"


def test_drop_verdict_respects_custom_fraction():
    from scripts.ops.corpus.ops_oos_holdout_eval import _drop_verdict

    # 7 < 10 * 0.8 -> significant drop under a stricter threshold,
    # but would be "consistent" under the default 0.5 fraction.
    verdict = _drop_verdict(oos_qualifying=7, in_sample=10, significant_drop_fraction=0.8)

    assert verdict == "significant drop — investigate"


def test_read_oos_rows_queries_tradeable_view_not_raw_table():
    """_read_oos_rows must join market_data_ohlcv_tradeable, not the raw calendar-grid
    table -- the raw table contains synthetic-fill/flat-carry-forward placeholder bars
    (always volume=0) which would corrupt the OOS feature-IC scoring calculation that
    reads m.open unfiltered. See docs/plans/2026-07-16-market-data-ohlcv-active-bars-
    boundary-design.md.
    """
    from scripts.ops.corpus import ops_oos_holdout_eval as module

    source = inspect.getsource(module._read_oos_rows)

    assert "market_data_ohlcv_tradeable" in source
    assert "FROM market_data_ohlcv\n" not in source
    assert "JOIN market_data_ohlcv\n" not in source
