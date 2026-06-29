"""Tests for src.intelligence.hmm_jit — Numba JIT forward filter.

The _alpha_pass_ref function is a verbatim copy of _alpha_pass from services/regime_writer.py.
Tests verify numerical identity between the JIT and Python reference implementations.
"""

from __future__ import annotations

import math

import numpy as np

from src.intelligence.hmm_jit import alpha_pass_jit

# ---------------------------------------------------------------------------
# Reference implementation (verbatim copy of services/regime_writer._alpha_pass)
# ---------------------------------------------------------------------------


def _alpha_pass_ref(
    log_emit: np.ndarray,
    A: np.ndarray,
    pi0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter. log_emit shape (n, K). Returns (states, alpha_history).

    Sequential t-loop is required — alpha[t] depends on alpha[t-1] for causality.
    Log emission matrix is precomputed outside for the full series at once.
    """
    n, K = log_emit.shape
    log_A = np.log(np.maximum(A, 1e-300))
    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    alpha = pi0.copy()

    for t in range(n):
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_trans = log_alpha[:, np.newaxis] + log_A  # (K, K)
        max_lt = log_trans.max(axis=0)
        log_alpha_new = max_lt + np.log(np.sum(np.exp(log_trans - max_lt), axis=0))
        log_alpha_new += log_emit[t]
        max_la = log_alpha_new.max()
        alpha = np.exp(log_alpha_new - max_la)
        total = alpha.sum()
        alpha /= total if total > 0 else 1.0
        states[t] = int(alpha.argmax())
        alpha_history[t] = alpha

    return states, alpha_history


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _random_inputs(
    n: int = 100, K: int = 5, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (log_emit, transmat, log_A, pi0) with valid HMM parameters."""
    rng = np.random.default_rng(seed)
    log_emit = rng.standard_normal((n, K)).astype(np.float64)
    # Row-stochastic transmat
    raw = rng.random((K, K)) + 0.1
    transmat = (raw / raw.sum(axis=1, keepdims=True)).astype(np.float64)
    log_A = np.log(np.maximum(transmat, 1e-300))
    pi0 = (rng.random(K) + 0.01).astype(np.float64)
    pi0 /= pi0.sum()
    return log_emit, transmat, log_A, pi0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_jit_states_match_reference() -> None:
    """JIT states must be array-equal to Python reference for same inputs."""
    log_emit, transmat, log_A, pi0 = _random_inputs(n=200, K=5, seed=7)
    ref_states, _ = _alpha_pass_ref(log_emit, transmat, pi0)
    jit_states, _ = alpha_pass_jit(log_emit, log_A, pi0)
    np.testing.assert_array_equal(jit_states, ref_states)


def test_jit_alpha_history_matches_reference() -> None:
    """JIT alpha_history must match Python reference within rtol=1e-10."""
    log_emit, transmat, log_A, pi0 = _random_inputs(n=200, K=5, seed=13)
    _, ref_alpha = _alpha_pass_ref(log_emit, transmat, pi0)
    _, jit_alpha = alpha_pass_jit(log_emit, log_A, pi0)
    np.testing.assert_allclose(jit_alpha, ref_alpha, rtol=1e-10)


def test_alpha_rows_sum_to_one() -> None:
    """Each row of alpha_history must sum to 1.0 within atol=1e-10."""
    log_emit, transmat, log_A, pi0 = _random_inputs(n=150, K=3, seed=99)
    _, jit_alpha = alpha_pass_jit(log_emit, log_A, pi0)
    row_sums = jit_alpha.sum(axis=1)
    np.testing.assert_allclose(row_sums, np.ones(len(row_sums)), atol=1e-10)


def test_diag_cov_path_identity() -> None:
    """JIT matches reference when log_emit is produced by a diag-covariance HMM."""
    rng = np.random.default_rng(17)
    K, d, n = 5, 3, 80
    means = rng.standard_normal((K, d))
    # Diagonal covariance: (K, d) variances
    covars_diag = (rng.random((K, d)) + 0.1) ** 2
    obs = rng.standard_normal((n, d))

    # Build log_emit using the same formula as _log_emit_diag in regime_writer
    log_emit = np.zeros((n, K))
    for k in range(K):
        diff = obs - means[k]
        diag_var = np.maximum(covars_diag[k], 1e-300)
        log_emit[:, k] = -0.5 * (
            np.sum(diff**2 / diag_var, axis=1) + np.sum(np.log(2 * math.pi * diag_var))
        )

    raw = rng.random((K, K)) + 0.1
    transmat = (raw / raw.sum(axis=1, keepdims=True)).astype(np.float64)
    log_A = np.log(np.maximum(transmat, 1e-300))
    pi0 = np.full(K, 1.0 / K)

    ref_states, ref_alpha = _alpha_pass_ref(log_emit, transmat, pi0)
    jit_states, jit_alpha = alpha_pass_jit(log_emit, log_A, pi0)

    np.testing.assert_array_equal(jit_states, ref_states)
    np.testing.assert_allclose(jit_alpha, ref_alpha, rtol=1e-10)


def test_full_cov_path_identity() -> None:
    """JIT matches reference when log_emit is produced by a full-covariance HMM."""
    rng = np.random.default_rng(31)
    K, d, n = 3, 2, 60
    means = rng.standard_normal((K, d))
    obs = rng.standard_normal((n, d))

    # Build positive-definite full covariance matrices
    log_emit = np.zeros((n, K))
    for k in range(K):
        L = rng.standard_normal((d, d)) * 0.5
        cov = L @ L.T + np.eye(d) * 0.5  # SPD
        diff = obs - means[k]
        try:
            cov_inv = np.linalg.inv(cov)
            sign, log_det = np.linalg.slogdet(cov)
            log_emit[:, k] = -0.5 * (
                np.einsum("ni,ij,nj->n", diff, cov_inv, diff) + log_det + d * math.log(2 * math.pi)
            )
        except np.linalg.LinAlgError:
            pass

    raw = rng.random((K, K)) + 0.1
    transmat = (raw / raw.sum(axis=1, keepdims=True)).astype(np.float64)
    log_A = np.log(np.maximum(transmat, 1e-300))
    pi0 = np.full(K, 1.0 / K)

    ref_states, ref_alpha = _alpha_pass_ref(log_emit, transmat, pi0)
    jit_states, jit_alpha = alpha_pass_jit(log_emit, log_A, pi0)

    np.testing.assert_array_equal(jit_states, ref_states)
    np.testing.assert_allclose(jit_alpha, ref_alpha, rtol=1e-10)
