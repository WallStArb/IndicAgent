"""Shared test adapter for the causal HMM forward filter.

`_causal_decode` below is the numpy reference forward filter (formerly
`_alpha_pass` in the regime kernel, deleted in 186-16 once production ran only
the Numba `alpha_pass_jit`). It takes (log_emit, transmat, pi0). This adapter reconstructs those inputs from
the pre-refactor (obs, means, covars, transmat, n_components) call shape that
tests in this suite still use, mirroring how _compute_symbol_tf constructs
these inputs in production (services/regime_writer.py _stationary_distribution
+ _log_emit_diag).
"""

from __future__ import annotations

import numpy as np

from services.regime_writer import _log_emit_diag, _stationary_distribution


def _causal_decode(
    log_emit: np.ndarray,
    A: np.ndarray,
    pi0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter. log_emit shape (n, K). Returns (states, alpha_history).

    Sequential t-loop is required: alpha[t] depends on alpha[t-1] for causality.
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


def decode(
    obs: np.ndarray,
    means: np.ndarray,
    covars_diag: np.ndarray,
    transmat: np.ndarray,
    n_components: int,
) -> tuple[np.ndarray, np.ndarray]:
    log_emit = _log_emit_diag(obs, means, covars_diag)
    pi0 = _stationary_distribution(transmat)
    return _causal_decode(log_emit, transmat, pi0)
