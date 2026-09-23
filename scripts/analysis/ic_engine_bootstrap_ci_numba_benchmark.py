"""
Scratch benchmark: does Numba-JIT-compiling the blocked-bootstrap resampling
loop in ic_engine._blocked_bootstrap_ci beat the current scipy/numpy-vectorized
implementation, at realistic scale?

This is a READ-ONLY research script. It does not touch services/ic_engine.py,
does not import it, does not connect to the database, and does not touch the
live ic_engine.py process. It reimplements the two functions under test
(_resample_ic's body and _vectorized_ic) verbatim from services/ic_engine.py
(as read on 2026-09-19) and src/intelligence/statistics/ic_math.py, so the
"current" arm here is a faithful copy, not the live code.

Realistic scale parameters (from services/ic_engine.py ICEngineConfig defaults
and docstrings, read 2026-09-19):
  - bootstrap_resamples = 2000 (alpha.ic.bootstrap_resamples)
  - feature_block_columns = 32
  - bootstrap_block_size: 5m=78, 15m=26, 1h=10, 1d=10 (bars, per-tf)
  - n_valid: varies by symbol/tf/regime cell; a few hundred to a few thousand
    rows after stride-subsampling + valid_mask. Using 2000 as a representative
    mid-large cell (5m pooled-regime cell), and 400 as a smaller cell (a thin
    regime slice) for a second data point.

Extended 2026-09-23 (todo 385 lever 2) with threading arms: nogil=True +
ThreadPoolExecutor, and numba.prange. Production ALREADY threads the scipy loop
(cross_sectional_bootstrap_threads 8/8/8/6, per_symbol_bootstrap_threads 2), so
the decision-relevant baseline is scipy + ThreadPoolExecutor at those thread
counts, not the serial loop.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import numba
import numpy as np
from numba import prange
from scipy.stats import rankdata

# ---------------------------------------------------------------------------
# Verbatim reimplementation of the "current" (scipy) code path
# ---------------------------------------------------------------------------


def vectorized_ic(ranks_X: np.ndarray, ranks_Y: np.ndarray) -> np.ndarray:
    """Copied verbatim from src/intelligence/statistics/ic_math.py::_vectorized_ic."""
    n = ranks_X.shape[0]
    if n < 2:
        return np.zeros(ranks_X.shape[1])
    X_c = ranks_X - ranks_X.mean(axis=0)
    Y_c = ranks_Y - ranks_Y.mean()
    denom = np.sqrt((X_c**2).sum(axis=0) * (Y_c**2).sum())
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denom > 1e-10, (X_c * Y_c[:, None]).sum(axis=0) / denom, 0.0)


def blocked_bootstrap_ci_current(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Copied verbatim (serial / pool=None path) from
    services/ic_engine.py::_blocked_bootstrap_ci, early_stop disabled.
    """
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]

    def _resample_ic(b: int) -> np.ndarray:
        idx = (starts_matrix[b][:, None] + offsets).ravel()[:n_valid] % n_valid
        ranks_X_boot = rankdata(X_raw_block[idx], axis=0)
        ranks_Y_boot = rankdata(Y_scale[idx])
        return vectorized_ic(ranks_X_boot, ranks_Y_boot)

    boot_ics = np.zeros((n_boot, block_p))
    for b in range(n_boot):
        boot_ics[b] = _resample_ic(b)
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Numba-JIT reimplementation, same statistical method, byte-identical target
# ---------------------------------------------------------------------------


@numba.njit(cache=True)
def _rankdata_average_1d(a: np.ndarray) -> np.ndarray:
    """Average-rank ranking of a 1D array, matching scipy.stats.rankdata(method='average').

    Standard argsort + tie-run-averaging algorithm. 1-indexed ranks, same
    convention as scipy.
    """
    n = a.shape[0]
    order = np.argsort(a)
    sorted_a = a[order]
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j < n - 1 and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


@numba.njit(cache=True)
def _rankdata_average_2d_axis0(a: np.ndarray) -> np.ndarray:
    """Column-wise average-rank ranking, matching rankdata(a, axis=0)."""
    n, p = a.shape
    out = np.empty((n, p), dtype=np.float64)
    for c in range(p):
        out[:, c] = _rankdata_average_1d(np.ascontiguousarray(a[:, c]))
    return out


@numba.njit(cache=True)
def _vectorized_ic_jit(ranks_X: np.ndarray, ranks_Y: np.ndarray) -> np.ndarray:
    n, p = ranks_X.shape
    out = np.zeros(p, dtype=np.float64)
    if n < 2:
        return out
    y_mean = ranks_Y.mean()
    y_c = ranks_Y - y_mean
    y_ss = (y_c**2).sum()
    for c in range(p):
        x_col = ranks_X[:, c]
        x_mean = x_col.mean()
        x_c = x_col - x_mean
        x_ss = (x_c**2).sum()
        denom = np.sqrt(x_ss * y_ss)
        if denom > 1e-10:
            out[c] = (x_c * y_c).sum() / denom
        else:
            out[c] = 0.0
    return out


@numba.njit(cache=True)
def _blocked_bootstrap_ci_jit_core(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> np.ndarray:
    """Whole resampling loop compiled into one function -- no per-resample
    Python-level call overhead at all (unlike the current path's
    _resample_ic closure invoked n_boot times from a Python for-loop).
    """
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]
    boot_ics = np.zeros((n_boot, block_p), dtype=np.float64)
    n_offsets = offsets.shape[0]
    n_blocks = starts_matrix.shape[1]
    total_len = n_blocks * n_offsets

    for b in range(n_boot):
        idx = np.empty(min(total_len, n_valid), dtype=np.int64)
        pos = 0
        for blk in range(n_blocks):
            start = starts_matrix[b, blk]
            for o in range(n_offsets):
                if pos >= n_valid:
                    break
                idx[pos] = (start + offsets[o]) % n_valid
                pos += 1
            if pos >= n_valid:
                break
        X_boot = X_raw_block[idx]
        Y_boot = Y_scale[idx]
        ranks_X_boot = _rankdata_average_2d_axis0(X_boot)
        ranks_Y_boot = _rankdata_average_1d(Y_boot)
        boot_ics[b] = _vectorized_ic_jit(ranks_X_boot, ranks_Y_boot)
    return boot_ics


def blocked_bootstrap_ci_numba(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> tuple[np.ndarray, np.ndarray]:
    boot_ics = _blocked_bootstrap_ci_jit_core(X_raw_block, Y_scale, starts_matrix, offsets, n_valid)
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Threading arms (todo 385 lever 2). Production threads the scipy loop via
# pool.map(_resample_ic, ...) over a shared ThreadPoolExecutor
# (services/ic_engine.py:2118) -- the scipy-threads arm below copies that
# verbatim. The numba nogil arms answer whether a GIL-free kernel scales
# where scipy's (partially GIL-bound) loop cannot.
# ---------------------------------------------------------------------------


def blocked_bootstrap_ci_scipy_threads(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
    n_threads: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Current scipy path + ThreadPoolExecutor, mirroring the production pool
    path (services/ic_engine.py:2112-2121, early_stop disabled)."""
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]

    def _resample_ic(b: int) -> np.ndarray:
        idx = (starts_matrix[b][:, None] + offsets).ravel()[:n_valid] % n_valid
        ranks_X_boot = rankdata(X_raw_block[idx], axis=0)
        ranks_Y_boot = rankdata(Y_scale[idx])
        return vectorized_ic(ranks_X_boot, ranks_Y_boot)

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        boot_ics = np.array(list(pool.map(_resample_ic, range(n_boot))))
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


@numba.njit(cache=True, nogil=True)
def _blocked_bootstrap_ci_jit_core_nogil(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> np.ndarray:
    """Body identical to _blocked_bootstrap_ci_jit_core above -- only the
    nogil=True flag differs, releasing the GIL so ThreadPoolExecutor workers
    can run this concurrently."""
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]
    boot_ics = np.zeros((n_boot, block_p), dtype=np.float64)
    n_offsets = offsets.shape[0]
    n_blocks = starts_matrix.shape[1]
    total_len = n_blocks * n_offsets

    for b in range(n_boot):
        idx = np.empty(min(total_len, n_valid), dtype=np.int64)
        pos = 0
        for blk in range(n_blocks):
            start = starts_matrix[b, blk]
            for o in range(n_offsets):
                if pos >= n_valid:
                    break
                idx[pos] = (start + offsets[o]) % n_valid
                pos += 1
            if pos >= n_valid:
                break
        X_boot = X_raw_block[idx]
        Y_boot = Y_scale[idx]
        ranks_X_boot = _rankdata_average_2d_axis0(X_boot)
        ranks_Y_boot = _rankdata_average_1d(Y_boot)
        boot_ics[b] = _vectorized_ic_jit(ranks_X_boot, ranks_Y_boot)
    return boot_ics


def blocked_bootstrap_ci_nogil_threads(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
    n_threads: int,
) -> tuple[np.ndarray, np.ndarray]:
    """nogil JIT core + ThreadPoolExecutor. Splits starts_matrix into n_threads
    contiguous row slices so each thread writes a disjoint boot_ics segment
    (same output ordering as serial, so outputs are comparable row-for-row)."""
    n_boot = starts_matrix.shape[0]
    edges = np.linspace(0, n_boot, n_threads + 1).astype(int)

    def _run_slice(i: int) -> np.ndarray:
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            return np.zeros((0, X_raw_block.shape[1]), dtype=np.float64)
        return _blocked_bootstrap_ci_jit_core_nogil(
            X_raw_block, Y_scale, starts_matrix[lo:hi], offsets, n_valid
        )

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        parts = list(pool.map(_run_slice, range(n_threads)))
    boot_ics = np.concatenate(parts, axis=0)
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


@numba.njit(parallel=True)
def _blocked_bootstrap_ci_prange_core(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> np.ndarray:
    """Body identical to _blocked_bootstrap_ci_jit_core with the outer
    resample loop as numba.prange. Disjoint per-row writes, no reductions, so
    deterministic. Not cached: numba cannot cache parallel=True functions."""
    n_boot = starts_matrix.shape[0]
    block_p = X_raw_block.shape[1]
    boot_ics = np.zeros((n_boot, block_p), dtype=np.float64)
    n_offsets = offsets.shape[0]
    n_blocks = starts_matrix.shape[1]
    total_len = n_blocks * n_offsets

    for b in prange(n_boot):
        idx = np.empty(min(total_len, n_valid), dtype=np.int64)
        pos = 0
        for blk in range(n_blocks):
            start = starts_matrix[b, blk]
            for o in range(n_offsets):
                if pos >= n_valid:
                    break
                idx[pos] = (start + offsets[o]) % n_valid
                pos += 1
            if pos >= n_valid:
                break
        X_boot = X_raw_block[idx]
        Y_boot = Y_scale[idx]
        ranks_X_boot = _rankdata_average_2d_axis0(X_boot)
        ranks_Y_boot = _rankdata_average_1d(Y_boot)
        boot_ics[b] = _vectorized_ic_jit(ranks_X_boot, ranks_Y_boot)
    return boot_ics


def blocked_bootstrap_ci_prange(
    X_raw_block: np.ndarray,
    Y_scale: np.ndarray,
    starts_matrix: np.ndarray,
    offsets: np.ndarray,
    n_valid: int,
) -> tuple[np.ndarray, np.ndarray]:
    boot_ics = _blocked_bootstrap_ci_prange_core(
        X_raw_block, Y_scale, starts_matrix, offsets, n_valid
    )
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


# ---------------------------------------------------------------------------
# Correctness check: does the Numba path match scipy exactly (with ties)?
# ---------------------------------------------------------------------------


def check_rankdata_matches_scipy():
    rng = np.random.default_rng(42)
    # Inject exact ties (rounding) to stress tie-handling, not just continuous data.
    a = rng.normal(size=500)
    a = np.round(a, 1)  # forces real ties
    got = _rankdata_average_1d(a)
    want = rankdata(a)
    assert np.allclose(got, want), f"1D rank mismatch: max diff {np.max(np.abs(got - want))}"

    b = rng.normal(size=(300, 10))
    b = np.round(b, 1)
    got2 = _rankdata_average_2d_axis0(b)
    want2 = rankdata(b, axis=0)
    assert np.allclose(got2, want2), f"2D rank mismatch: max diff {np.max(np.abs(got2 - want2))}"
    print("Rank correctness check PASSED (matches scipy.stats.rankdata exactly, incl. ties).")


def check_full_ci_matches():
    rng = np.random.default_rng(7)
    n_valid = 500
    block_p = 8
    X = rng.normal(size=(n_valid, block_p))
    X = np.round(X, 2)  # induce some ties
    Y = rng.normal(size=n_valid)
    Y = np.round(Y, 2)
    block_size = 26
    n_time_blocks = -(-n_valid // block_size)
    n_boot = 300
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    ci_lo_a, ci_hi_a = blocked_bootstrap_ci_current(X, Y, starts_matrix, offsets, n_valid)
    ci_lo_b, ci_hi_b = blocked_bootstrap_ci_numba(X, Y, starts_matrix, offsets, n_valid)
    max_diff = max(np.max(np.abs(ci_lo_a - ci_lo_b)), np.max(np.abs(ci_hi_a - ci_hi_b)))
    print(f"Full CI output max abs diff (scipy path vs numba path): {max_diff:.3e}")
    assert max_diff < 1e-9, "CI outputs diverge beyond float noise -- NOT byte-identical"
    print("Full-CI correctness check PASSED (byte-identical to float64 noise floor).")


def check_thread_variants_match():
    """Every threading arm must reproduce the serial scipy path to the same
    1e-9 tolerance (disjoint writes, deterministic order -- threading must not
    change a single bit)."""
    rng = np.random.default_rng(11)
    n_valid = 500
    block_p = 8
    X = np.round(rng.normal(size=(n_valid, block_p)), 2)
    Y = np.round(rng.normal(size=n_valid), 2)
    block_size = 26
    n_time_blocks = -(-n_valid // block_size)
    n_boot = 300
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    ref_lo, ref_hi = blocked_bootstrap_ci_current(X, Y, starts_matrix, offsets, n_valid)
    arms = {
        "scipy threads=4": blocked_bootstrap_ci_scipy_threads(
            X, Y, starts_matrix, offsets, n_valid, 4
        ),
        "nogil threads=4": blocked_bootstrap_ci_nogil_threads(
            X, Y, starts_matrix, offsets, n_valid, 4
        ),
        "prange": blocked_bootstrap_ci_prange(X, Y, starts_matrix, offsets, n_valid),
    }
    for name, (lo, hi) in arms.items():
        diff = max(np.max(np.abs(ref_lo - lo)), np.max(np.abs(ref_hi - hi)))
        assert diff < 1e-9, f"{name} diverges from serial scipy: max diff {diff:.3e}"
        print(f"  {name}: max diff {diff:.3e} -- PASSED")
    print("Thread-variant correctness checks PASSED (all arms byte-identical to scipy serial).")


# ---------------------------------------------------------------------------
# Benchmark harness
# ---------------------------------------------------------------------------


def run_benchmark(n_valid: int, block_p: int, block_size: int, n_boot: int, label: str):
    rng = np.random.default_rng(123)
    X_raw_block = rng.normal(size=(n_valid, block_p)).astype(np.float64)
    Y_scale = rng.normal(size=n_valid).astype(np.float64)
    n_time_blocks = -(-n_valid // block_size)
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    # Warm up JIT compilation (excluded from timing -- cache=True means this
    # cost is paid once per process in the real service, amortized across
    # thousands of cells).
    _ = blocked_bootstrap_ci_numba(X_raw_block, Y_scale, starts_matrix[:5], offsets, n_valid)

    t0 = time.perf_counter()
    ci_lo_cur, ci_hi_cur = blocked_bootstrap_ci_current(
        X_raw_block, Y_scale, starts_matrix, offsets, n_valid
    )
    t1 = time.perf_counter()
    scipy_time = t1 - t0

    t0 = time.perf_counter()
    ci_lo_jit, ci_hi_jit = blocked_bootstrap_ci_numba(
        X_raw_block, Y_scale, starts_matrix, offsets, n_valid
    )
    t1 = time.perf_counter()
    numba_time = t1 - t0

    max_diff = max(np.max(np.abs(ci_lo_cur - ci_lo_jit)), np.max(np.abs(ci_hi_cur - ci_hi_jit)))

    print(
        f"\n=== {label} (n_valid={n_valid}, block_p={block_p}, block_size={block_size}, n_boot={n_boot}) ==="
    )
    print(f"  scipy/current path : {scipy_time:.4f} s")
    print(f"  numba JIT path     : {numba_time:.4f} s  (excludes one-time compile)")
    print(f"  speedup            : {scipy_time / numba_time:.2f}x")
    print(f"  max abs CI diff    : {max_diff:.3e}")


def run_parallel_benchmark(
    n_valid: int,
    block_p: int,
    block_size: int,
    n_boot: int,
    label: str,
    thread_counts: tuple[int, ...] = (2, 4, 8),
):
    """All threading arms against the scipy serial baseline. Every arm's output
    is checked against scipy serial within the run -- a speedup that changes
    bits is a correctness bug, not a win."""
    rng = np.random.default_rng(123)
    X_raw_block = rng.normal(size=(n_valid, block_p)).astype(np.float64)
    Y_scale = rng.normal(size=n_valid).astype(np.float64)
    n_time_blocks = -(-n_valid // block_size)
    starts_matrix = rng.integers(0, n_valid, size=(n_boot, n_time_blocks))
    offsets = np.arange(block_size)

    # Warm up every JIT variant (excluded from timing).
    _ = blocked_bootstrap_ci_numba(X_raw_block, Y_scale, starts_matrix[:5], offsets, n_valid)
    _ = blocked_bootstrap_ci_nogil_threads(
        X_raw_block, Y_scale, starts_matrix[:8], offsets, n_valid, 2
    )
    _ = blocked_bootstrap_ci_prange(X_raw_block, Y_scale, starts_matrix[:8], offsets, n_valid)

    arms: list[tuple[str, object]] = [
        (
            "scipy serial (baseline)",
            lambda: blocked_bootstrap_ci_current(
                X_raw_block, Y_scale, starts_matrix, offsets, n_valid
            ),
        ),
    ]
    for t in thread_counts:
        arms.append(
            (
                f"scipy threads={t}",
                lambda t=t: blocked_bootstrap_ci_scipy_threads(
                    X_raw_block, Y_scale, starts_matrix, offsets, n_valid, t
                ),
            )
        )
    arms.append(
        (
            "numba serial",
            lambda: blocked_bootstrap_ci_numba(
                X_raw_block, Y_scale, starts_matrix, offsets, n_valid
            ),
        )
    )
    for t in thread_counts:
        arms.append(
            (
                f"numba nogil threads={t}",
                lambda t=t: blocked_bootstrap_ci_nogil_threads(
                    X_raw_block, Y_scale, starts_matrix, offsets, n_valid, t
                ),
            )
        )
    arms.append(
        (
            "numba prange",
            lambda: blocked_bootstrap_ci_prange(
                X_raw_block, Y_scale, starts_matrix, offsets, n_valid
            ),
        )
    )

    print(
        f"\n=== {label} (n_valid={n_valid}, block_p={block_p}, "
        f"block_size={block_size}, n_boot={n_boot}) -- threading arms ==="
    )
    ref: tuple[np.ndarray, np.ndarray] | None = None
    baseline_s: float | None = None
    for name, fn in arms:
        t0 = time.perf_counter()
        ci_lo, ci_hi = fn()
        elapsed = time.perf_counter() - t0
        if ref is None:
            ref = (ci_lo, ci_hi)
            baseline_s = elapsed
            diff = 0.0
        else:
            diff = max(np.max(np.abs(ref[0] - ci_lo)), np.max(np.abs(ref[1] - ci_hi)))
        assert diff < 1e-9, f"{name}: output changed ({diff:.3e}) -- not byte-identical"
        assert baseline_s is not None
        print(
            f"  {name:26s}: {elapsed:8.4f} s   "
            f"{baseline_s / elapsed:6.2f}x vs scipy serial   diff {diff:.1e}"
        )


if __name__ == "__main__":
    print("Compiling Numba functions (first call, one-time cost, excluded from benchmark)...")
    t0 = time.perf_counter()
    check_rankdata_matches_scipy()
    check_full_ci_matches()
    print(f"(compile+correctness time: {time.perf_counter() - t0:.2f} s)")

    # One feature block, typical 5m cell, full 2000 resamples, block_size=78 (5m).
    run_benchmark(
        n_valid=2000,
        block_p=32,
        block_size=78,
        n_boot=2000,
        label="5m pooled cell, one feature block",
    )

    # Smaller cell (thin regime slice), 15m block size.
    run_benchmark(
        n_valid=400,
        block_p=32,
        block_size=26,
        n_boot=2000,
        label="thin 15m regime cell, one feature block",
    )

    # 1h/1d: small block_size=10, moderate n_valid.
    run_benchmark(
        n_valid=1000, block_p=32, block_size=10, n_boot=2000, label="1h cell, one feature block"
    )

    # Full ~290-feature cell = 9 feature blocks of 32 -- simulate as one call
    # with block_p=290 to get the aggregate per-cell number (structurally
    # equivalent since blocks are processed independently and sequentially).
    run_benchmark(
        n_valid=2000,
        block_p=290,
        block_size=78,
        n_boot=2000,
        label="5m pooled cell, ALL ~290 features (9 blocks worth)",
    )

    # Threading arms (todo 385 lever 2). Production already threads the scipy
    # loop (CS 8/8/8/6, per-symbol 2), so the decision number is
    # threads-vs-threads at those counts, not threads-vs-serial.
    print("\nRunning thread-variant correctness checks...")
    check_thread_variants_match()

    run_parallel_benchmark(
        n_valid=2000,
        block_p=32,
        block_size=78,
        n_boot=2000,
        label="5m pooled cell, one feature block",
    )
    run_parallel_benchmark(
        n_valid=400,
        block_p=32,
        block_size=26,
        n_boot=2000,
        label="thin 15m regime cell, one feature block",
    )
    run_parallel_benchmark(
        n_valid=2000,
        block_p=290,
        block_size=78,
        n_boot=2000,
        label="5m pooled cell, ALL ~290 features",
    )
