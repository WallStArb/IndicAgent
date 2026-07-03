"""
Unit tests for the Phase 142B.1 mean-variance (Sigma^-1 . IC) weight combination.

All imports from src.intelligence.ensemble only — no DB, no Kafka.
"""

from __future__ import annotations

import numpy as np

from src.intelligence.ensemble.weights import mean_variance_weights

# ---------------------------------------------------------------------------
# mean_variance_weights tests
# ---------------------------------------------------------------------------


class TestMeanVarianceWeights:
    def test_well_conditioned_returns_normalized_weights(self) -> None:
        """Diagonal covariance -> weights == (ic_shrunk / diag) normalized by sum of abs."""
        cov = np.diag([1.0, 2.0, 4.0])
        ic_shrunk = np.array([1.0, 1.0, 1.0])
        weights, cond = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)

        assert weights is not None
        assert np.isfinite(cond)
        raw = np.array([1.0, 0.5, 0.25])
        expected = raw / np.sum(np.abs(raw))
        np.testing.assert_allclose(weights, expected, atol=1e-9)

    def test_diagonal_case_matches_analytic_solve(self) -> None:
        """For diagonal Sigma=diag([1,2,4]) and ic=[1,1,1], raw solution == [1, 0.5, 0.25]
        before normalization (proves solve semantics, indirectly proving not-inv via
        exactness)."""
        cov = np.diag([1.0, 2.0, 4.0])
        ic_shrunk = np.array([1.0, 1.0, 1.0])
        weights, _cond = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)

        assert weights is not None
        # weights are normalized raw / sum(|raw|); ratio must match [1, 0.5, 0.25]
        ratio = weights / weights[0]
        np.testing.assert_allclose(ratio, [1.0, 0.5, 0.25], atol=1e-9)

    def test_ill_conditioned_returns_none_and_cond(self) -> None:
        """Near-singular covariance (cond > condition_max) -> (None, cond), no raise."""
        # Two nearly-identical rows/cols -> very high condition number
        cov = np.array(
            [
                [1.0, 0.999999999, 0.0],
                [0.999999999, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        weights, cond = mean_variance_weights(cov, np.array([1.0, 1.0, 1.0]), condition_max=1000.0)

        assert weights is None
        assert cond > 1000.0

    def test_non_finite_cond_returns_none(self) -> None:
        """All-zero matrix (cond == inf, exact SVD zero) -> (None, cond)."""
        cov = np.zeros((2, 2))
        weights, cond = mean_variance_weights(cov, np.array([1.0, 1.0]), condition_max=1000.0)

        assert weights is None
        assert not np.isfinite(cond)

    def test_returns_raw_uncapped_unsigned(self) -> None:
        """Output is NOT capped/sign-flipped — a large ic_shrunk entry can exceed any
        per-feature cap; cap/sign is a later step (D-08)."""
        cov = np.diag([1.0, 100.0])
        ic_shrunk = np.array([1.0, 0.001])
        weights, _cond = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)

        assert weights is not None
        # Dominant feature 0 should exceed a typical 0.20 per-feature cap since no
        # cap logic is applied inside this function.
        assert weights[0] > 0.20

    def test_zero_solution_returns_zeros_not_nan(self) -> None:
        """If solve yields all-near-zero (sum |raw| < 1e-10), return zeros of correct
        shape, not NaN."""
        cov = np.diag([1.0, 1.0])
        ic_shrunk = np.array([0.0, 0.0])
        weights, cond = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)

        assert weights is not None
        assert not np.any(np.isnan(weights))
        np.testing.assert_allclose(weights, np.zeros(2), atol=1e-12)
        assert np.isfinite(cond)
