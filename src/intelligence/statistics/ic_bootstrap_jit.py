"""Numba circular block bootstrap kernel for ic_engine's per-block CI (todo 385 lever 2).

Replaces the Python-level resample loop in ``services/ic_engine.py::_blocked_bootstrap_ci``
(one scipy ``rankdata`` + ``_vectorized_ic`` call per resample, dispatched from a Python
for-loop or a ThreadPoolExecutor) with one compiled function whose outer resample loop is a
``numba.prange``. Measured 2026-09-23 on the production shapes: 10.8-13.1x over the serial
scipy loop, ~2.3-2.8x over the best threaded scipy arm at equal core budget
(``scripts/analysis/ic_engine_bootstrap_ci_numba_benchmark.py``).

Semantics match the scipy path exactly, including the edge cases:

- ``_rankdata_average_1d`` is scipy's ``rankdata(method='average')``: 1-indexed ranks, ties
  averaged. scipy's default ``nan_policy='propagate'`` returns an all-NaN rank vector when
  the input holds any NaN; this kernel does the same, so a NaN-bearing column's IC falls
  through the same ``denom > 1e-10`` test to 0.0 on both paths.
- ``_vectorized_ic_jit`` mirrors ``ic_math._vectorized_ic``: ``n < 2`` returns zeros, a
  denominator at or below 1e-10 (or NaN) returns 0.0.
- Resample indices are built exactly as the scipy path builds them:
  ``(starts[b][:, None] + offsets).ravel()[:n_valid] % n_valid``.

Exactness: the kernel ranks and accumulates in float64. Against the scipy path fed float64
input it is bit-identical (``tests/unit/test_ic_bootstrap_jit.py``): ranks are multiples of
0.5, so centered sums and sums of squares are exact while they stay below 2**53. It is NOT
bit-identical to production's scipy path on float32 input: scipy >= 1.15 returns float32
ranks for float32 input, so that path accumulates sums of squares in float32 (~1e-7
relative), and the kernel is the more accurate of the two. Multi-million-row cross-sectional
cells can also exceed 2**53. The kernel choice is therefore a COMPUTATIONAL config field in
ic_engine's fingerprint, not an operational one.

Deterministic: each resample writes only its own row of ``boot_ics`` and reads nothing
another iteration writes, so thread count and scheduling order never change the output.
"""

from __future__ import annotations

import numba
import numpy as np
from numba import prange


@numba.njit(cache=True, nogil=True)
def _rankdata_average_1d(a: np.ndarray) -> np.ndarray:
    n = a.shape[0]
    ranks = np.empty(n, dtype=np.float64)
    for i in range(n):
        if np.isnan(a[i]):
            ranks[:] = np.nan
            return ranks
    order = np.argsort(a)
    i = 0
    while i < n:
        j = i
        while j < n - 1 and a[order[j + 1]] == a[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


@numba.njit(cache=True, nogil=True)
def _vectorized_ic_jit(ranks_X: np.ndarray, ranks_Y: np.ndarray) -> np.ndarray:
    n, p = ranks_X.shape
    out = np.zeros(p, dtype=np.float64)
    if n < 2:
        return out
    y_mean = ranks_Y.sum() / n
    y_ss = 0.0
    for r in range(n):
        d = ranks_Y[r] - y_mean
        y_ss += d * d
    for c in range(p):
        x_mean = 0.0
        for r in range(n):
            x_mean += ranks_X[r, c]
        x_mean /= n
        x_ss = 0.0
        xy = 0.0
        for r in range(n):
            dx = ranks_X[r, c] - x_mean
            x_ss += dx * dx
            xy += dx * (ranks_Y[r] - y_mean)
        denom = np.sqrt(x_ss * y_ss)
        if denom > 1e-10:
            out[c] = xy / denom
    return out


@numba.njit(cache=True, nogil=True, parallel=True)
def _boot_ics_prange(
    X_block: np.ndarray,
    Y: np.ndarray,
    starts: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> np.ndarray:
    n_boot = starts.shape[0]
    n_blocks = starts.shape[1]
    n_offsets = offsets.shape[0]
    p = X_block.shape[1]
    n_idx = min(n_blocks * n_offsets, n_valid)
    boot_ics = np.zeros((n_boot, p), dtype=np.float64)
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
        ranks_Y = _rankdata_average_1d(Y[idx])
        ranks_X = np.empty((n_idx, p), dtype=np.float64)
        col = np.empty(n_idx, dtype=X_block.dtype)
        for c in range(p):
            for r in range(n_idx):
                col[r] = X_block[idx[r], c]
            ranks_X[:, c] = _rankdata_average_1d(col)
        boot_ics[b] = _vectorized_ic_jit(ranks_X, ranks_Y)
    return boot_ics


def blocked_bootstrap_ics(
    X_block: np.ndarray,
    Y: np.ndarray,
    starts: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
    n_threads: int,
) -> np.ndarray:
    """Bootstrap IC matrix ``[starts.shape[0], X_block.shape[1]]`` for the given resample rows.

    ``starts`` may be any row slice of the caller's pre-drawn block-start matrix (the early-stop
    path passes one chunk at a time); rows are independent, so slicing never changes a row's
    result. ``n_threads`` caps numba's thread pool for this call only (clamped to
    ``[1, numba.config.NUMBA_NUM_THREADS]``) and is restored afterwards, so the per-process
    thread budget stays under the caller's control (ic_engine runs several worker processes).
    """
    n_threads = max(1, min(int(n_threads), numba.config.NUMBA_NUM_THREADS))
    previous = numba.get_num_threads()
    numba.set_num_threads(n_threads)
    try:
        return _boot_ics_prange(
            np.ascontiguousarray(X_block),
            np.ascontiguousarray(Y, dtype=np.float64),
            np.ascontiguousarray(starts, dtype=np.int64),
            np.ascontiguousarray(offsets, dtype=np.int64),
            int(n_valid),
        )
    finally:
        numba.set_num_threads(previous)
