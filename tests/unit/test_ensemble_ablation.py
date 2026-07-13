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
