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
import pytest

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


# ---------------------------------------------------------------------------
# Task 3: arm IC measurement + reconstruction check
# ---------------------------------------------------------------------------


def _monotone_series(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Perfectly rank-aligned alpha/returns pair: Spearman IC exactly 1.0."""
    rng = np.random.default_rng(42)
    alpha = np.sort(rng.normal(size=n))
    returns = np.sort(rng.normal(size=n))
    return alpha, returns


def test_compute_arm_ic_perfect_rank_alignment():
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 300
    assert arm.ic == 1.0
    # CI machinery present, never a bare correlation (project rule)
    assert arm.ci_lower is not None and arm.ci_upper is not None
    assert arm.ci_lower <= arm.ic <= arm.ci_upper


def test_clamp_ci_to_ic_absorbs_boundary_noise_silently():
    """Float64 tanh/arctanh round-trip noise (e.g. the ~8e-11 case observed at
    IC=1.0 in _monotone_series(300)) is within tolerance -- clamps silently,
    same behavior as the pre-fix inline np.clip."""
    from ops_ensemble_ablation import _clamp_ci_to_ic

    lower, upper = _clamp_ci_to_ic(ci_lower=0.5, ci_upper=0.9 - 1e-11, ic=0.9)
    assert lower == 0.5
    assert upper == 0.9


def test_clamp_ci_to_ic_raises_on_material_violation():
    """A violation far larger than float64 noise (e.g. a sign error in
    _fisher_z_ci) must raise loudly, not silently clamp into a tight, misleading
    range around ic -- 'silent wrong answers are worse than loud crashes'."""
    from ops_ensemble_ablation import _clamp_ci_to_ic

    with pytest.raises(ValueError, match="ci_upper"):
        _clamp_ci_to_ic(ci_lower=0.1, ci_upper=0.5, ic=0.9)


def test_compute_arm_ic_stride_subsamples_before_gating():
    """stride = max(subsample_min_stride, lookahead_bars) applied to the pooled
    series (ensemble_ic_engine lines 770-773): 300 bars at stride 60 -> 5 obs,
    below min_reliable_n -> None, even though the raw series was long enough."""
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    assert compute_arm_ic(alpha, returns, stride=60, min_reliable_n=100) is None


def test_compute_arm_ic_nan_pairs_excluded_from_n():
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    returns = returns.copy()
    returns[:150] = np.nan
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 150


def test_compute_arm_ic_degenerate_series_is_none_not_zero():
    """Zeroing the only weighted family makes the composite constant; Spearman on a
    constant is UNDEFINED. Must return None (rendered DEGENERATE), never IC=0.0 --
    an IC of 0.0 would fake 'family removal made the model exactly neutral'."""
    from ops_ensemble_ablation import compute_arm_ic

    returns = np.linspace(-1.0, 1.0, 300)
    constant_alpha = np.zeros(300)
    assert compute_arm_ic(constant_alpha, returns, stride=1, min_reliable_n=100) is None


def test_compute_arm_ic_identical_code_path_for_identical_inputs():
    """The zero-delta property the control family relies on: an arm whose weights
    equal the baseline's must produce the bit-identical ArmIC (same function, same
    inputs). Guards against any future baseline-only shortcut."""
    from ops_ensemble_ablation import compute_arm_ic

    alpha, returns = _monotone_series(300)
    a = compute_arm_ic(alpha, returns, stride=3, min_reliable_n=50)
    b = compute_arm_ic(alpha.copy(), returns.copy(), stride=3, min_reliable_n=50)
    assert a == b


def test_reconstruction_check_pass_and_mismatch():
    from ops_ensemble_ablation import reconstruction_check

    stored = np.array([1.0, 2.0, 3.0, 4.0])
    n, diff, ok = reconstruction_check(stored.copy(), stored, tol=0.01)
    assert (n, diff, ok) == (4, 0.0, True)
    off = stored + np.array([0.0, 0.0, 0.0, 1.0])  # 1.0 abs diff vs std ~1.118
    n, diff, ok = reconstruction_check(off, stored, tol=0.01)
    assert n == 4 and diff is not None and diff > 0.01 and ok is False


def test_reconstruction_check_no_stored_overlap_is_skipped_not_failed():
    """Stored ensemble_alpha may not cover OOS bars (e.g. trainer ran before those
    bars existed): zero overlap is SKIPPED (ok=True, diff None), not a mismatch."""
    from ops_ensemble_ablation import reconstruction_check

    recomputed = np.array([1.0, 2.0])
    stored = np.array([np.nan, np.nan])
    assert reconstruction_check(recomputed, stored, tol=0.01) == (0, None, True)
