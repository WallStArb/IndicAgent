"""Numba circular block bootstrap kernel for ic_engine's per-block CI (todo 385 lever 2).

Replaces the Python-level resample loop in ``services/ic_engine.py::_blocked_bootstrap_ci``
(one scipy ``rankdata`` + ``_vectorized_ic`` call per resample) with one compiled function
whose outer resample loop is a ``numba.prange``.

Counting ranks instead of sorting. A bootstrap resample only repeats rows of the original
sample, so the relative order of its values is already known from the original column. Each
column is dense-ranked ONCE (``_dense_ranks``: one sort per column per call); inside the
resample loop, a column's average ranks come from counting how many times each dense value
was drawn and a prefix sum: a value whose ties occupy sorted positions ``running ..
running+count-1`` gets rank ``running + (count + 1) / 2``, exactly scipy's
``rankdata(method='average')``. That is O(n + K) per column per resample instead of an
O(n log n) argsort, with no sort anywhere in the hot loop.

Semantics match the scipy path, including its edge cases:

- scipy's default ``nan_policy='propagate'`` turns a column's ranks all-NaN when the resample
  draws any NaN row, and ``ic_math._vectorized_ic`` then returns 0.0 for it (a NaN
  denominator fails ``denom > 1e-10``). NaN rows carry dense rank -1 here, and a column that
  draws one gets IC 0.0 directly.
- ``n < 2`` returns zeros; a denominator at or below 1e-10 returns 0.0, as in
  ``_vectorized_ic``.
- Resample indices are built exactly as the scipy path builds them:
  ``(starts[b][:, None] + offsets).ravel()[:n_valid] % n_valid``.

Exactness: ranks are multiples of 0.5 and the rank mean is exactly ``(n + 1) / 2``, so every
centered sum and sum of squares is exact in float64 while it stays below 2**53, and summation
order cannot matter. Against the scipy path fed float64 input the kernel is bit-identical
(``tests/unit/test_ic_bootstrap_jit.py``). It is NOT bit-identical to production's scipy path
on float32 input: scipy >= 1.15 returns float32 ranks for float32 input, so that path
accumulates sums of squares in float32 (~1e-7 relative), and the kernel is the more accurate
of the two. Multi-million-row cross-sectional cells can also exceed 2**53. The kernel choice
is therefore a COMPUTATIONAL config field in ic_engine's fingerprint, not an operational one.

Deterministic: each resample writes only its own row of ``boot_ics`` and reads nothing
another iteration writes, so thread count and scheduling order never change the output.
"""

from __future__ import annotations

import numba
import numpy as np
from numba import prange


def _dense_ranks(values: np.ndarray) -> tuple[np.ndarray, int]:
    """0-based dense rank of each entry (equal values share a rank), -1 for NaN; and the
    number of distinct non-NaN values."""
    dense = np.full(values.shape[0], -1, dtype=np.int32)
    finite = ~np.isnan(values)
    uniques, inverse = np.unique(values[finite], return_inverse=True)
    dense[finite] = inverse
    return dense, uniques.shape[0]


@numba.njit(cache=True, nogil=True)
def _average_ranks_by_count(
    dense: np.ndarray,
    idx: np.ndarray,
    k: int,
    counts: np.ndarray,
    avg: np.ndarray,
    drawn: np.ndarray,
) -> bool:
    """Fill ``avg[v]`` with the average rank of dense value ``v`` within the resample ``idx``,
    and ``drawn[r]`` with row ``r``'s dense value (so callers read it sequentially instead of
    gathering through ``idx`` a second time). Returns False when the resample draws a NaN row
    (dense rank -1)."""
    counts[:k] = 0
    for r in range(idx.shape[0]):
        v = dense[idx[r]]
        if v < 0:
            return False
        drawn[r] = v
        counts[v] += 1
    running = 0
    for v in range(k):
        c = counts[v]
        avg[v] = running + (c + 1) / 2.0
        running += c
    return True


@numba.njit(cache=True, nogil=True, parallel=True)
def _boot_ics_prange(
    dense_X: np.ndarray,
    k_X: np.ndarray,
    dense_Y: np.ndarray,
    k_Y: int,
    starts: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> np.ndarray:
    n_boot = starts.shape[0]
    n_blocks = starts.shape[1]
    n_offsets = offsets.shape[0]
    p = dense_X.shape[1]
    n_idx = min(n_blocks * n_offsets, n_valid)
    max_k = max(k_Y, k_X.max() if p > 0 else 0)
    boot_ics = np.zeros((n_boot, p), dtype=np.float64)
    if n_idx < 2:
        return boot_ics
    mean_rank = (n_idx + 1) / 2.0
    for b in prange(n_boot):
        idx = np.empty(n_idx, dtype=np.int64)
        pos = 0
        for blk in range(n_blocks):
            if pos >= n_idx:
                break
            start = starts[b, blk]
            for o in range(n_offsets):
                if pos >= n_idx:
                    break
                idx[pos] = (start + offsets[o]) % n_valid
                pos += 1
        counts = np.empty(max_k, dtype=np.int32)
        avg = np.empty(max_k, dtype=np.float64)
        drawn = np.empty(n_idx, dtype=np.int32)
        if not _average_ranks_by_count(dense_Y, idx, k_Y, counts, avg, drawn):
            continue  # NaN return drawn: every rank vector is NaN -> every IC is 0.0
        y_c = np.empty(n_idx, dtype=np.float64)
        y_ss = 0.0
        for r in range(n_idx):
            d = avg[drawn[r]] - mean_rank
            y_c[r] = d
            y_ss += d * d
        for c in range(p):
            dense_col = dense_X[:, c]
            if not _average_ranks_by_count(dense_col, idx, k_X[c], counts, avg, drawn):
                continue  # NaN feature value drawn -> IC 0.0
            x_ss = 0.0
            xy = 0.0
            for r in range(n_idx):
                dx = avg[drawn[r]] - mean_rank
                x_ss += dx * dx
                xy += dx * y_c[r]
            denom = np.sqrt(x_ss * y_ss)
            if denom > 1e-10:
                boot_ics[b, c] = xy / denom
    return boot_ics


def dense_rank_inputs(
    X_block: np.ndarray, Y: np.ndarray, n_valid: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Dense-rank the block's columns and the return vector once, for every later
    ``blocked_bootstrap_ics`` call on the same block (the early-stop path calls it once per
    chunk). Column-major int32, so each column is contiguous in the hot loop and the matrix
    costs half of a float64 copy."""
    X_block = X_block[:n_valid]
    p = X_block.shape[1]
    dense_X = np.empty((n_valid, p), dtype=np.int32, order="F")
    k_X = np.empty(p, dtype=np.int64)
    for c in range(p):
        dense_X[:, c], k_X[c] = _dense_ranks(X_block[:, c])
    dense_Y, k_Y = _dense_ranks(np.asarray(Y[:n_valid], dtype=np.float64))
    return dense_X, k_X, dense_Y, k_Y


def blocked_bootstrap_ics(
    dense_inputs: tuple[np.ndarray, np.ndarray, np.ndarray, int],
    starts: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
    n_threads: int,
) -> np.ndarray:
    """Bootstrap IC matrix ``[starts.shape[0], n_features]`` for the given resample rows.

    ``dense_inputs`` comes from ``dense_rank_inputs``. ``starts`` may be any row slice of the
    caller's pre-drawn block-start matrix; rows are independent, so slicing never changes a
    row's result. ``n_threads`` caps numba's thread pool for this call only (clamped to
    ``[1, numba.config.NUMBA_NUM_THREADS]``) and is restored afterwards, so the per-process
    thread budget stays under the caller's control (ic_engine runs several worker processes).
    """
    dense_X, k_X, dense_Y, k_Y = dense_inputs
    n_threads = max(1, min(int(n_threads), numba.config.NUMBA_NUM_THREADS))
    previous = numba.get_num_threads()
    numba.set_num_threads(n_threads)
    try:
        return _boot_ics_prange(
            dense_X,
            k_X,
            dense_Y,
            int(k_Y),
            np.ascontiguousarray(starts, dtype=np.int64),
            np.ascontiguousarray(offsets, dtype=np.int64),
            int(n_valid),
        )
    finally:
        numba.set_num_threads(previous)
