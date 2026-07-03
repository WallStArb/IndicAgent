"""
Unit tests for the Phase 142B.1 empirical-Bayes IC shrinkage library.

All imports from src.intelligence.ensemble only — no DB, no Kafka.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.ensemble.shrinkage import leave_one_out_group_prior, shrink_ic

# ---------------------------------------------------------------------------
# shrink_ic tests
# ---------------------------------------------------------------------------


class TestShrinkIc:
    def test_zero_n_eff_returns_prior_untouched(self) -> None:
        """n_eff == 0 -> degenerate guard returns (ic_prior, 0.0), no divide-by-zero."""
        result = shrink_ic(ic_raw=0.9, n_eff=0, ic_prior=0.1, k=100)
        assert result == (0.1, 0.0)

    def test_negative_n_eff_returns_prior_untouched(self) -> None:
        """n_eff < 0 -> (ic_prior, 0.0), no raise."""
        ic_shrunk, w = shrink_ic(ic_raw=0.9, n_eff=-5, ic_prior=0.1, k=100)
        assert ic_shrunk == pytest.approx(0.1)
        assert w == pytest.approx(0.0)

    def test_large_n_eff_trusts_raw(self) -> None:
        """As n_eff >> k, ic_shrunk -> ic_raw and w -> 1.0 (approx)."""
        ic_shrunk, w = shrink_ic(ic_raw=0.9, n_eff=1_000_000, ic_prior=0.1, k=100)
        assert w == pytest.approx(1.0, abs=1e-3)
        assert ic_shrunk == pytest.approx(0.9, abs=1e-3)

    def test_small_n_eff_trusts_prior(self) -> None:
        """n_eff much smaller than k -> ic_shrunk closer to ic_prior."""
        ic_shrunk, w = shrink_ic(ic_raw=0.9, n_eff=1, ic_prior=0.1, k=100)
        assert w < 0.5
        # ic_shrunk should be much closer to ic_prior (0.1) than to ic_raw (0.9)
        assert abs(ic_shrunk - 0.1) < abs(ic_shrunk - 0.9)

    def test_shrinkage_weight_in_unit_interval(self) -> None:
        """For any n_eff >= 0, k > 0, 0 <= w <= 1."""
        for n_eff in (0, 0.5, 1, 10, 100, 1000, 1_000_000):
            _, w = shrink_ic(ic_raw=0.5, n_eff=n_eff, ic_prior=0.05, k=50)
            assert 0.0 <= w <= 1.0

    def test_w_equals_half_at_n_eff_equals_k(self) -> None:
        """n_eff == k -> w == 0.5 exactly (the seed calibration invariant)."""
        _, w = shrink_ic(ic_raw=0.5, n_eff=100, ic_prior=0.05, k=100)
        assert w == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# leave_one_out_group_prior tests
# ---------------------------------------------------------------------------


class TestLeaveOneOutGroupPrior:
    def test_leave_one_out_excludes_self(self) -> None:
        """group [0.2, 0.4, 0.9], self_index=2 -> prior == mean([0.2, 0.4]) == 0.3."""
        group = np.array([0.2, 0.4, 0.9])
        prior = leave_one_out_group_prior(group, self_index=2)
        assert prior == pytest.approx(0.3)

    def test_leave_one_out_small_group_n_equals_3(self) -> None:
        """n=3 group does not divide by zero and excludes self correctly (D-06)."""
        group = np.array([0.10, 0.20, 0.30])
        prior_0 = leave_one_out_group_prior(group, self_index=0)
        prior_1 = leave_one_out_group_prior(group, self_index=1)
        prior_2 = leave_one_out_group_prior(group, self_index=2)
        assert prior_0 == pytest.approx((0.20 + 0.30) / 2)
        assert prior_1 == pytest.approx((0.10 + 0.30) / 2)
        assert prior_2 == pytest.approx((0.10 + 0.20) / 2)

    def test_leave_one_out_single_member_group(self) -> None:
        """n_group==1 handled per contract (documented sentinel/behavior), no ZeroDivisionError."""
        group = np.array([0.42])
        prior = leave_one_out_group_prior(group, self_index=0)
        # Contract: with no peers, the leave-one-out mean is undefined; the function
        # falls back to the self value rather than raising ZeroDivisionError or NaN.
        assert prior == pytest.approx(0.42)
