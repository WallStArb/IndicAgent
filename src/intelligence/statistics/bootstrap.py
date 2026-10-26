"""Politis-Romano stationary bootstrap indices (geometric blocks, circular).

One index draw serves every series resampled together (StepM's joint draw, design 7.3.2) and
the research evaluator's Sharpe interval. The draw order of the generator is part of each
caller's recorded numbers: changing it moves frozen verdicts (repro_frozen).
"""

from __future__ import annotations

import numpy as np


def stationary_bootstrap_indices(
    n: int, mean_block: float, reps: int, rng: np.random.Generator
) -> np.ndarray:
    """[reps, n] row indices: each row starts at a uniform index and continues the previous
    index + 1 (mod n), restarting at a fresh uniform index with probability 1 / mean_block."""
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    restart = rng.random((reps, n)) < 1.0 / mean_block
    fresh = rng.integers(0, n, (reps, n))
    for t in range(1, n):
        idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
    return idx
