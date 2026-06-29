"""Numba JIT forward filter for HMM regime inference.

Provides alpha_pass_jit — a numerically identical drop-in for regime_writer._alpha_pass.
The key difference: takes log_A (pre-computed) instead of raw transmat_, which moves the
log(max(transmat_, 1e-300)) computation outside the JIT boundary to the Python call site.

Design decisions:
- @numba.njit(cache=True): compiled once, loaded from __pycache__ on all subsequent runs.
  The main process compiles (10-20s first run); workers then load read-only — no race.
- Takes log_A not transmat_: avoids recomputing log(max(...)) on every symbol in the t-loop.
- Scalar-style log-sum-exp with numpy ops that work in nopython mode. No try/except (not
  supported in njit). _log_emit_full and _log_emit_diag remain in Python for this reason.
- Ring 1 placement: no DB imports, no Ring 2 imports, no asyncio.

Usage (from regime_writer):
    log_A = np.log(np.maximum(model.transmat_, 1e-300))
    raw_states, alpha_history = alpha_pass_jit(log_emit, log_A, pi0)
"""

from __future__ import annotations

import numba
import numpy as np


@numba.njit(cache=True)
def alpha_pass_jit(
    log_emit: np.ndarray,
    log_A: np.ndarray,
    pi0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter via Numba JIT. Numerically identical to _alpha_pass.

    Args:
        log_emit: (n, K) float64 — precomputed log emission probabilities.
        log_A: (K, K) float64 — pre-computed log(max(transmat_, 1e-300)).
                Caller computes: np.log(np.maximum(model.transmat_, 1e-300))
        pi0: (K,) float64 — initial state distribution (e.g. stationary distribution).

    Returns:
        states: (n,) int64 — most likely state at each timestep.
        alpha_history: (n, K) float64 — normalised forward probabilities; each row sums to 1.
    """
    n, K = log_emit.shape
    states = np.zeros(n, dtype=np.int64)
    alpha_history = np.zeros((n, K))
    alpha = pi0.copy()

    for t in range(n):
        # log_alpha: (K,) — log of current alpha vector
        log_alpha = np.log(np.maximum(alpha, 1e-300))

        # log-sum-exp over previous states for each next state j.
        # log_trans[i, j] = log_alpha[i] + log_A[i, j].
        # max_lt[j] = max_i(log_trans[i, j]) for numerical stability.
        # Explicit loops required — numba njit does not support .max(axis=0)
        # or np.sum(..., axis=0) on 2-D arrays.
        max_lt = np.empty(K)
        for j in range(K):
            mx = log_alpha[0] + log_A[0, j]
            for i in range(1, K):
                val = log_alpha[i] + log_A[i, j]
                if val > mx:
                    mx = val
            max_lt[j] = mx

        log_alpha_new = np.empty(K)
        for j in range(K):
            s = 0.0
            for i in range(K):
                s += np.exp(log_alpha[i] + log_A[i, j] - max_lt[j])
            log_alpha_new[j] = max_lt[j] + np.log(s)

        # Incorporate emission
        log_alpha_new = log_alpha_new + log_emit[t]

        # Normalise in log space then exponentiate
        max_la = log_alpha_new[0]
        for j in range(1, K):
            if log_alpha_new[j] > max_la:
                max_la = log_alpha_new[j]

        alpha = np.exp(log_alpha_new - max_la)
        total = 0.0
        for j in range(K):
            total += alpha[j]
        if total > 0.0:
            for j in range(K):
                alpha[j] /= total

        # Argmax
        best = 0
        for j in range(1, K):
            if alpha[j] > alpha[best]:
                best = j
        states[t] = best
        alpha_history[t] = alpha

    return states, alpha_history
