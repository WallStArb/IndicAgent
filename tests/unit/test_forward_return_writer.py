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

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.forward_return_writer import forward_log_return


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
