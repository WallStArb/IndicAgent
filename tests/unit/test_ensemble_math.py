"""
Unit tests for the ensemble math library's surviving functions (effective_n,
compute_shrinkage_covariance). The old-chain functions were deleted in phase 186 plan 19.

All imports from src.intelligence.ensemble only; no DB, no Kafka.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.ensemble.covariance import compute_shrinkage_covariance
from src.intelligence.ensemble.weights import effective_n


class TestEffectiveN:
    def test_equal_weights_yield_n(self) -> None:
        """5 equal weights of 0.2 → effective_n = 5.0."""
        w = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        result = effective_n(w)
        assert result == pytest.approx(5.0, abs=1e-9)

    def test_inverse_hhi_formula(self) -> None:
        """effective_n = 1/sum(w^2) on a known vector."""
        w = np.array([0.5, 0.3, 0.2])
        expected = 1.0 / float(np.sum(w**2))
        assert effective_n(w) == pytest.approx(expected, abs=1e-9)

    def test_zero_weights_return_zero(self) -> None:
        """All-zero weight vector → effective_n = 0.0."""
        w = np.zeros(5)
        assert effective_n(w) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_alpha_score tests
# ---------------------------------------------------------------------------


# compute_shrinkage_covariance tests
# ---------------------------------------------------------------------------


class TestComputeShrinkageCovariance:
    def test_returns_correct_shape(self) -> None:
        """LW covariance has shape [n_features, n_features]."""
        X = np.random.default_rng(42).standard_normal((100, 5))
        cov, shrinkage = compute_shrinkage_covariance(X)
        assert cov.shape == (5, 5)

    def test_shrinkage_in_unit_interval(self) -> None:
        """Shrinkage coefficient is in [0, 1]."""
        X = np.random.default_rng(42).standard_normal((100, 5))
        _, shrinkage = compute_shrinkage_covariance(X)
        assert 0.0 <= shrinkage <= 1.0

    def test_degenerate_single_row_returns_zeros(self) -> None:
        """Fewer than 2 rows → returns zero covariance without raising."""
        X = np.ones((1, 3))
        cov, shrinkage = compute_shrinkage_covariance(X)
        assert cov.shape == (3, 3)
        assert shrinkage == pytest.approx(0.0)

    def test_covariance_is_symmetric(self) -> None:
        """LW covariance must be symmetric."""
        X = np.random.default_rng(7).standard_normal((50, 4))
        cov, _ = compute_shrinkage_covariance(X)
        np.testing.assert_allclose(cov, cov.T, atol=1e-12)


# ---------------------------------------------------------------------------
# covariance_to_correlation tests -- extracted from ensemble_trainer.py's own inline
# conversion (todo 240 follow-on, so scripts/analysis' new linear-ensemble comparison arm
# could reuse it instead of a third ad hoc copy of the same guarded division).
# ---------------------------------------------------------------------------
