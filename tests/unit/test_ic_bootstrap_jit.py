"""Parity: the numba bootstrap kernel must reproduce ic_engine's scipy resample loop exactly."""

import numpy as np
import pytest
from scipy.stats import rankdata

from src.intelligence.statistics.ic_bootstrap_jit import blocked_bootstrap_ics as _kernel
from src.intelligence.statistics.ic_bootstrap_jit import dense_rank_inputs


def blocked_bootstrap_ics(X, Y, starts, offsets, n_valid, n_threads):
    return _kernel(dense_rank_inputs(X, Y, n_valid), starts, offsets, n_valid, n_threads)


from src.intelligence.statistics.ic_math import _vectorized_ic


def _scipy_boot_ics(X_block, Y, starts, offsets, n_valid):
    """Verbatim body of services/ic_engine.py::_blocked_bootstrap_ci's _resample_ic."""
    out = np.zeros((starts.shape[0], X_block.shape[1]))
    for b in range(starts.shape[0]):
        idx = (starts[b][:, None] + offsets).ravel()[:n_valid] % n_valid
        out[b] = _vectorized_ic(rankdata(X_block[idx], axis=0), rankdata(Y[idx]))
    return out


def _case(n_valid, p, block_size, n_boot, seed, dtype=np.float32):
    rng = np.random.default_rng(seed)
    # Rounded values force heavy ties, the case the tie-averaging must get right.
    X = np.round(rng.normal(size=(n_valid, p)), 1).astype(dtype)
    Y = np.round(rng.normal(size=n_valid) + 0.3 * X[:, 0], 2).astype(np.float64)
    n_blocks = -(-n_valid // block_size)
    starts = rng.integers(0, n_valid, size=(n_boot, n_blocks))
    offsets = np.arange(block_size)
    return X, Y, starts, offsets


@pytest.mark.parametrize(
    ("n_valid", "p", "block_size", "n_boot", "dtype"),
    [
        (500, 7, 10, 60, np.float32),
        (1_203, 32, 26, 40, np.float32),
        (997, 5, 78, 30, np.float64),
        (50, 3, 7, 25, np.float32),
    ],
)
@pytest.mark.parametrize("n_threads", [1, 4])
def test_matches_scipy_exactly(n_valid, p, block_size, n_boot, dtype, n_threads):
    """Exact against the scipy path fed float64 (the cast preserves order and ties, so ranks are
    identical); within float32 rounding of the production path fed the raw dtype.

    scipy >= 1.15 returns float32 ranks for float32 input, so production's _vectorized_ic
    accumulates sums of squares in float32. The kernel accumulates in float64 throughout, so it
    is exact against the float64 reference and closer to the true value than production.
    """
    X, Y, starts, offsets = _case(n_valid, p, block_size, n_boot, seed=n_valid + p, dtype=dtype)
    got = blocked_bootstrap_ics(X, Y, starts, offsets, n_valid, n_threads)
    exact = _scipy_boot_ics(X.astype(np.float64), Y, starts, offsets, n_valid)
    np.testing.assert_array_equal(got, exact)
    production = _scipy_boot_ics(X, Y, starts, offsets, n_valid)
    np.testing.assert_allclose(got, production, rtol=0, atol=1e-6)


def test_nan_and_constant_columns_match_scipy():
    X, Y, starts, offsets = _case(400, 4, 10, 30, seed=7)
    X[5, 1] = np.nan  # any NaN in the column -> scipy ranks it all-NaN -> IC falls to 0.0
    X[:, 2] = 1.5  # constant column -> zero variance -> IC 0.0
    expected = _scipy_boot_ics(X.astype(np.float64), Y, starts, offsets, 400)
    got = blocked_bootstrap_ics(X, Y, starts, offsets, 400, 2)
    np.testing.assert_array_equal(got, expected)


def test_row_slices_equal_full_matrix():
    """The early-stop path computes one chunk of starts rows at a time."""
    X, Y, starts, offsets = _case(600, 6, 10, 90, seed=11)
    full = blocked_bootstrap_ics(X, Y, starts, offsets, 600, 3)
    chunked = np.vstack(
        [blocked_bootstrap_ics(X, Y, starts[i : i + 25], offsets, 600, 3) for i in range(0, 90, 25)]
    )
    np.testing.assert_array_equal(chunked, full)


def test_non_contiguous_column_slice_input():
    """ic_engine passes X_raw_scale[:, block_start:block_end], a non-contiguous view."""
    X, Y, starts, offsets = _case(300, 10, 10, 20, seed=3)
    view = X[:, 2:7]
    assert not view.flags["C_CONTIGUOUS"]
    np.testing.assert_array_equal(
        blocked_bootstrap_ics(view, Y, starts, offsets, 300, 2),
        _scipy_boot_ics(view.astype(np.float64), Y, starts, offsets, 300),
    )


def test_thread_count_is_restored():
    import numba

    before = numba.get_num_threads()
    X, Y, starts, offsets = _case(100, 2, 5, 5, seed=1)
    blocked_bootstrap_ics(X, Y, starts, offsets, 100, 1)
    assert numba.get_num_threads() == before


@pytest.mark.parametrize("early_stop", [False, True])
def test_ic_engine_blocked_bootstrap_ci_kernel_matches_scipy_path(early_stop):
    """ic_engine._blocked_bootstrap_ci with numba_threads>0 equals its scipy path on float64
    input, including the early-stop chunking (same chunk boundaries, same stop decision)."""
    from services.ic_engine import _blocked_bootstrap_ci

    X, Y, starts, offsets = _case(800, 9, 10, 600, seed=5, dtype=np.float64)
    kwargs = dict(
        early_stop_enabled=early_stop,
        early_stop_check_interval=200,
        early_stop_tol=0.002,
        early_stop_min_resamples=200,
        early_stop_stable_checks=2,
    )
    scipy_lo, scipy_hi = _blocked_bootstrap_ci(X, Y, starts, offsets, 800, None, **kwargs)
    jit_lo, jit_hi = _blocked_bootstrap_ci(
        X, Y, starts, offsets, 800, None, numba_threads=4, **kwargs
    )
    np.testing.assert_array_equal(jit_lo, scipy_lo)
    np.testing.assert_array_equal(jit_hi, scipy_hi)


def test_nan_row_drawn_by_only_some_resamples():
    """A NaN feature row zeroes the IC only in resamples that draw it; others rank normally."""
    X, Y, starts, offsets = _case(40, 3, 4, 200, seed=13, dtype=np.float64)
    X[17, 0] = np.nan
    got = blocked_bootstrap_ics(X, Y, starts, offsets, 40, 2)
    np.testing.assert_array_equal(got, _scipy_boot_ics(X, Y, starts, offsets, 40))
    assert (got[:, 0] == 0.0).any() and (got[:, 0] != 0.0).any()


def test_nan_return_zeroes_every_feature_in_drawing_resamples():
    X, Y, starts, offsets = _case(40, 3, 4, 200, seed=17, dtype=np.float64)
    Y[9] = np.nan
    np.testing.assert_array_equal(
        blocked_bootstrap_ics(X, Y, starts, offsets, 40, 2),
        _scipy_boot_ics(X, Y, starts, offsets, 40),
    )
