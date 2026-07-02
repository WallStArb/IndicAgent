"""Unit test: vectorized IC matches scipy.stats.spearmanr to 1e-10.

Verifies that compute_ic_vectorized() (Pearson-on-ranks vectorized over all
features simultaneously) produces results identical to scipy.stats.spearmanr
to within floating-point precision (1e-10). This is the correctness anchor
for the IC measurement substrate.

No DB, no Kafka. Pure numpy + scipy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import compute_ic_vectorized


def _make_feature_matrix(n: int = 100, p: int = 5, seed: int = 42) -> np.ndarray:
    """Build deterministic [n, p] raw feature matrix with fixed seed."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, p))


def _make_return_vector(n: int = 100, seed: int = 7) -> np.ndarray:
    """Build deterministic length-n return vector with fixed seed."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n)


def test_vectorized_ic_matches_spearmanr():
    """compute_ic_vectorized matches scipy.stats.spearmanr to 1e-10 for all features."""
    n, p = 100, 5
    X = _make_feature_matrix(n, p, seed=42)
    y = _make_return_vector(n, seed=7)

    ic_vec = compute_ic_vectorized(X, y)

    assert ic_vec.shape == (p,), f"Expected shape ({p},), got {ic_vec.shape}"

    for j in range(p):
        expected = spearmanr(X[:, j], y).correlation
        actual = ic_vec[j]
        diff = abs(actual - expected)
        assert diff < 1e-10, (
            f"Feature {j}: vectorized IC={actual:.15f}, "
            f"scipy.spearmanr={expected:.15f}, diff={diff:.2e} (threshold 1e-10)"
        )


def test_vectorized_ic_matches_spearmanr_second_return_vector():
    """Same assertion with a second independent return vector (seed=99)."""
    n, p = 100, 5
    X = _make_feature_matrix(n, p, seed=42)
    y2 = _make_return_vector(n, seed=99)

    ic_vec = compute_ic_vectorized(X, y2)

    for j in range(p):
        expected = spearmanr(X[:, j], y2).correlation
        diff = abs(ic_vec[j] - expected)
        assert diff < 1e-10, (
            f"Feature {j}, y2: vectorized IC={ic_vec[j]:.15f}, "
            f"scipy.spearmanr={expected:.15f}, diff={diff:.2e}"
        )


def test_vectorized_ic_returns_float_array():
    """Return type must be numpy float array of length n_features."""
    X = _make_feature_matrix(80, 3)
    y = _make_return_vector(80)
    ic_vec = compute_ic_vectorized(X, y)
    assert isinstance(ic_vec, np.ndarray)
    assert ic_vec.dtype.kind == "f", f"Expected float dtype, got {ic_vec.dtype}"
    assert ic_vec.shape == (3,)


def test_vectorized_ic_range():
    """IC values must be in [-1, 1]."""
    X = _make_feature_matrix(200, 10)
    y = _make_return_vector(200)
    ic_vec = compute_ic_vectorized(X, y)
    assert np.all(ic_vec >= -1.0 - 1e-10), f"IC below -1: {ic_vec.min()}"
    assert np.all(ic_vec <= 1.0 + 1e-10), f"IC above +1: {ic_vec.max()}"


def test_vectorized_ic_perfect_correlation():
    """Feature identical to returns should yield IC == 1.0."""
    n = 50
    y = np.arange(n, dtype=float)
    X = y.reshape(-1, 1)
    ic_vec = compute_ic_vectorized(X, y)
    assert abs(ic_vec[0] - 1.0) < 1e-10, f"Expected IC=1.0 for identical feature, got {ic_vec[0]}"


def test_vectorized_ic_perfect_anticorrelation():
    """Feature perfectly inversely correlated with returns should yield IC == -1.0."""
    n = 50
    y = np.arange(n, dtype=float)
    X = (-y).reshape(-1, 1)
    ic_vec = compute_ic_vectorized(X, y)
    assert (
        abs(ic_vec[0] + 1.0) < 1e-10
    ), f"Expected IC=-1.0 for anti-correlated feature, got {ic_vec[0]}"
