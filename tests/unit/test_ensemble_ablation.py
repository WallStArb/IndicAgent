"""Unit tests: todo 084 leave-one-family-out ensemble ablation protocol.

All statistical kernels in scripts/ops/alpha/ops_ensemble_ablation.py are pure
module-level functions tested here without any DB or Kafka (project unit-test rule).
The load-bearing properties under test are statistical-correctness properties:
identical code path for baseline and ablated arms, sign convention, complete-gating,
pooling equivalence with ensemble_ic_engine._aggregate_pooled_series, degenerate-arm
handling, and the SQL invariants (executable returns filter, OOS >= boundary).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_ablation import (
    _BASELINE_ARM,
    _CONTROL_FAMILY,
    signed_weights_from_rows,
    weight_mass_fraction,
    zero_family,
)

# ---------------------------------------------------------------------------
# Task 1: weight-vector kernels
# ---------------------------------------------------------------------------


def test_signed_weights_sign_convention():
    """sign comes from stored ensemble_weights.ic_sharpe: negative ic_sharpe flips
    the weight (sign-symmetric challenger case); non-negative keeps it positive
    (champion case, where all eligible features have ic_ci_lower > 0)."""
    weights = np.array([0.2, 0.3, 0.5])
    ic_sharpes = np.array([0.8, -0.4, 0.0])
    signed = signed_weights_from_rows(weights, ic_sharpes)
    assert signed.dtype == np.float64
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_zeroes_only_that_family_and_copies():
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    ablated = zero_family(signed, groups, "momentum")
    np.testing.assert_allclose(ablated, [0.0, -0.3, 0.0])
    # input untouched (must be a copy, or arms contaminate each other)
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_absent_family_is_identity():
    signed = np.array([0.2, -0.3])
    ablated = zero_family(signed, ["momentum", "volume"], _CONTROL_FAMILY)
    np.testing.assert_allclose(ablated, signed)


def test_weight_mass_fraction_uses_absolute_mass():
    """|-0.3| counts as mass 0.3: a contrarian feature's contribution share must not
    be understated (or netted against longs) by signed summation."""
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    assert weight_mass_fraction(signed, groups, "volume") == 0.3 / 1.0
    assert weight_mass_fraction(signed, groups, "momentum") == 0.7 / 1.0
    assert weight_mass_fraction(signed, groups, _CONTROL_FAMILY) == 0.0


def test_weight_mass_fraction_zero_total_returns_zero():
    assert weight_mass_fraction(np.zeros(3), ["a", "b", "c"], "a") == 0.0


def test_baseline_arm_sentinel_is_not_a_plausible_group_name():
    assert _BASELINE_ARM == "__baseline__"


# ---------------------------------------------------------------------------
# Task 2: pooling kernel
# ---------------------------------------------------------------------------


def test_apply_complete_gate_nans_incomplete_and_copies():
    """ic_engine convention (lines 1848-1850): a return is usable only when
    complete AND finite. Gate applied pre-pooling; input untouched."""
    from ops_ensemble_ablation import apply_complete_gate

    returns = np.array([0.01, 0.02, np.nan, 0.04])
    complete = np.array([True, False, True, True])
    gated = apply_complete_gate(returns, complete)
    assert np.isfinite(gated[0]) and gated[0] == 0.01
    assert np.isnan(gated[1])  # complete=False censored even though value present
    assert np.isnan(gated[2])  # already NaN stays NaN
    assert gated[3] == 0.04
    assert returns[1] == 0.02  # input not mutated


def test_pool_means_by_bar_matches_aggregate_pooled_series():
    """Equivalence oracle: our vectorized pooling must produce the exact same
    cross-symbol means as ensemble_ic_engine._aggregate_pooled_series (the
    alpha_ensemble_ic POOLED convention, Pitfall 5: group before averaging),
    including None/NaN-skipping semantics. Two symbols, three bars, one missing
    value and one bar with a single member."""
    from datetime import UTC, datetime

    from ops_ensemble_ablation import pool_means_by_bar

    from services.ensemble_ic_engine import _aggregate_pooled_series

    t1 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    t3 = datetime(2026, 1, 5, 14, 40, tzinfo=UTC)
    oracle_rows = [
        {
            "bar_ts": t1,
            "regime_label": "low_bull",
            "alpha_score": 1.0,
            "return_fast": 0.01,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t1,
            "regime_label": "low_bull",
            "alpha_score": 3.0,
            "return_fast": 0.03,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t2,
            "regime_label": "low_bull",
            "alpha_score": 5.0,
            "return_fast": None,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t3,
            "regime_label": "low_bull",
            "alpha_score": 2.0,
            "return_fast": 0.02,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
        {
            "bar_ts": t3,
            "regime_label": "low_bull",
            "alpha_score": 4.0,
            "return_fast": 0.06,
            "return_mid": None,
            "return_slow": None,
            "return_extended": None,
        },
    ]
    oracle = _aggregate_pooled_series(oracle_rows, "5m")  # sorted by bar_ts

    bar_ts_arr = np.array([t1, t1, t2, t3, t3], dtype=object)
    unique_ts, bar_idx = np.unique(bar_ts_arr, return_inverse=True)
    alpha = np.array([1.0, 3.0, 5.0, 2.0, 4.0])
    ret_fast = np.array([0.01, 0.03, np.nan, 0.02, 0.06])

    pooled_alpha = pool_means_by_bar(bar_idx, len(unique_ts), alpha)
    pooled_fast = pool_means_by_bar(bar_idx, len(unique_ts), ret_fast)

    assert list(unique_ts) == [r["bar_ts"] for r in oracle]
    np.testing.assert_allclose(pooled_alpha, [r["alpha_score"] for r in oracle])
    # oracle returns None for the all-missing bar; ours returns NaN
    oracle_fast = [np.nan if r["return_fast"] is None else r["return_fast"] for r in oracle]
    np.testing.assert_allclose(pooled_fast, oracle_fast)


def test_pool_means_by_bar_all_nan_bar_is_nan_not_zero():
    """A bar with zero finite members must pool to NaN (unmeasurable), never a
    silent 0.0 -- 0.0 would enter downstream rank correlations as fake data."""
    from ops_ensemble_ablation import pool_means_by_bar

    bar_idx = np.array([0, 0, 1])
    values = np.array([np.nan, np.nan, 5.0])
    pooled = pool_means_by_bar(bar_idx, 2, values)
    assert np.isnan(pooled[0])
    assert pooled[1] == 5.0
