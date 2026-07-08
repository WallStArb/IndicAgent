"""Shared test adapter for services.regime_writer's causal HMM decoder.

_causal_decode() takes (log_emit, transmat, pi0) post the 2026-06-25
vectorization (commit 9e7e4213). This adapter reconstructs those inputs from
the pre-refactor (obs, means, covars, transmat, n_components) call shape that
tests in this suite still use, mirroring how _compute_symbol_tf constructs
these inputs in production (services/regime_writer.py _stationary_distribution
+ _log_emit_diag).
"""

from __future__ import annotations

import numpy as np

from services.regime_writer import _causal_decode, _log_emit_diag, _stationary_distribution


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
