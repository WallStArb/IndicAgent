"""The fixed smoothing menu for a member's input (design D3, phase 184 B5).

One menu, never tuned on outcomes: a member pins `smoothing_half_life` from
SMOOTHING_HALF_LIVES before any run, and the choice is counted like any other spec field. The
smoother is a causal finite FIR: weights a * (1 - a) ** k for k = 0..k_max with
a = 1 - 2 ** (-1 / h), normalized once by their fixed total (a constant, never data
dependent), so a constant finite input passes through unchanged. k_max is the lag at which the
exponential impulse response falls below MEMORY_TOLERANCE of its peak (the same cut signals.py
uses to declare a recursive filter's memory), and the window is truncated there, so the
declared memory is exact rather than approximate.

No fill (184-REVIEWS row 6): the output at t is NaN when any input in t - k_max .. t is NaN.
There is no renormalization over the finite cells of a window, which would be a fill. Rows
before k_max finite history are NaN.

Daily clock only in this phase: one row is one session (RESEARCH A5), so the memory in rows is
the memory in sessions.
"""

from __future__ import annotations

import math

import numpy as np

from src.intelligence.research.guards import MEMORY_TOLERANCE

# A design constant (APR-exempt): the menu is the pre-registered choice set; changing it is a
# methodology change, not a tuning.
SMOOTHING_HALF_LIVES = (5, 21, 63)


def _check_half_life(half_life: int) -> None:
    if isinstance(half_life, bool) or half_life not in SMOOTHING_HALF_LIVES:
        raise ValueError(
            f"smoothing half-life must be one of {SMOOTHING_HALF_LIVES}, got {half_life!r}"
        )


def smoothing_memory_sessions(half_life: int) -> int:
    """k_max: the rows before t the smoothed value at t reads (67, 280, 838 for the menu)."""
    _check_half_life(half_life)
    return math.ceil(half_life * math.log2(1.0 / MEMORY_TOLERANCE))


def smoothing_weights(half_life: int) -> np.ndarray:
    """[k_max + 1] normalized weights; index k multiplies x[t - k]."""
    k_max = smoothing_memory_sessions(half_life)
    a = 1.0 - 2.0 ** (-1.0 / half_life)
    w = a * (1.0 - a) ** np.arange(k_max + 1, dtype=np.float64)
    return w / w.sum()


def smooth(x: np.ndarray, half_life: int) -> np.ndarray:
    """[n, m] smoothed x. Each output is the weighted sum over its own window (accumulated one
    lag at a time, bounded memory, never a recursion or a prefix difference), NaN if any input
    in the window is NaN."""
    if x.ndim != 2:
        raise ValueError(f"x must be 2-D [rows, columns], got shape {x.shape}")
    if not np.issubdtype(x.dtype, np.floating):
        raise ValueError(f"x must be floating point, got {x.dtype}")
    w = smoothing_weights(half_life)
    k_max = len(w) - 1
    n = x.shape[0]
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n <= k_max:
        return out.astype(x.dtype)
    src = x.astype(np.float64, copy=False)
    acc = np.zeros((n - k_max, x.shape[1]), dtype=np.float64)
    for k, wk in enumerate(w):
        # rows t = k_max .. n - 1 read x[t - k]; NaN propagates through the sum
        acc += wk * src[k_max - k : n - k]
    out[k_max:] = acc
    return out.astype(x.dtype, copy=False)
