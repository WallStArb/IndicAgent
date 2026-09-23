"""Blocked replacements for the two full-cell copies in ic_engine's cross-sectional cells.

Phase 174 code review CR-03: `np.std(X_raw, axis=0, dtype=np.float64)` allocated a full
float64 copy of the cell (2x a float32 cell), and `X_raw[:, broadcast_mask]` a full-height
copy of the broadcast columns, voiding the disk-backed cell's bounded-memory guarantee.
These tests pin (a) numerical equivalence to the numpy expressions they replace, including
NaN behavior and the first-violation index, (b) block-size invariance, and (c) the memory
bound itself, traced with tracemalloc on a memmap-backed input, both for the helpers and
for the cell's own setup phase end to end.
"""

from __future__ import annotations

import dataclasses
import sys
import tracemalloc
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services.ic_engine as ic_module
from services.ic_engine import (
    _blocked_column_moments,
    _collapse_invariant_groups,
    _streaming_feature_correlation,
)


def _blocked_column_std(X, row_block):
    return _blocked_column_moments(X, row_block)[1]


_RNG = np.random.default_rng(174)


def _reference_collapse(X, col_mask, group_starts, threshold):
    X_bc = X[:, col_mask]
    spread = np.fmax.reduceat(X_bc, group_starts, axis=0) - np.fmin.reduceat(
        X_bc, group_starts, axis=0
    )
    violating = np.argwhere(spread > threshold)
    violation = None
    if len(violating):
        gi, ci = violating[0]
        violation = (int(gi), int(ci), float(spread[gi, ci]))
    return X_bc[group_starts], violation


# ---------------------------------------------------------------------------
# _blocked_column_moments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row_block", [1, 7, 100, 10_000])
def test_blocked_std_matches_numpy(row_block):
    X = (_RNG.normal(size=(2_003, 9)) * 50 + 1_000).astype(np.float32)
    X[:, 3] = 5.0  # degenerate column
    expected = np.std(X, axis=0, dtype=np.float64)
    np.testing.assert_allclose(_blocked_column_std(X, row_block), expected, rtol=1e-12, atol=0)


def test_blocked_std_propagates_nan_like_numpy():
    X = _RNG.normal(size=(500, 4)).astype(np.float32)
    X[17, 2] = np.nan
    got = _blocked_column_std(X, 64)
    assert np.isnan(got[2])
    assert np.isfinite(np.delete(got, 2)).all()


def test_blocked_std_degenerate_mask_identical_to_numpy():
    """The only consumer is `std < 1e-8`; the mask must not change."""
    X = _RNG.normal(size=(3_000, 12)).astype(np.float32)
    X[:, [0, 5]] = 3.25
    X[:, 7] = 1e-10 * _RNG.normal(size=3_000)
    expected = np.std(X, axis=0, dtype=np.float64) < 1e-8
    assert (_blocked_column_std(X, 257) < 1e-8).tolist() == expected.tolist()


def test_blocked_means_match_numpy():
    X = _RNG.normal(size=(1_234, 6)).astype(np.float32)
    means, _ = _blocked_column_moments(X, 100)
    np.testing.assert_allclose(means, X.astype(np.float64).mean(axis=0), rtol=1e-13, atol=1e-15)


@pytest.mark.parametrize("row_block", [1, 97, 5_000])
@pytest.mark.parametrize("memmap_backed", [False, True])
def test_passing_moments_means_to_correlation_is_bit_identical(tmp_path, row_block, memmap_backed):
    """The cross-sectional cell hands _blocked_column_moments' means (column-subset) to
    _streaming_feature_correlation to skip its pass 1. That is only sound if the result is
    exactly -- not approximately -- what the function computes on its own."""
    n_rows, n_cols = 3_001, 11
    X = _RNG.normal(size=(n_rows, n_cols)).astype(np.float32)
    if memmap_backed:
        mm = np.memmap(tmp_path / "x.memmap", dtype=np.float32, mode="w+", shape=X.shape)
        mm[:] = X
        X = mm
    mask = np.zeros(n_cols, dtype=bool)
    mask[[0, 2, 3, 7, 10]] = True
    X_nd = np.ascontiguousarray(X[:, mask])
    means, _ = _blocked_column_moments(X, row_block)
    expected = _streaming_feature_correlation(X_nd, None, row_block)
    got = _streaming_feature_correlation(X_nd, None, row_block, means=means[mask])
    np.testing.assert_array_equal(got, expected)


# ---------------------------------------------------------------------------
# _collapse_invariant_groups
# ---------------------------------------------------------------------------


def _grouped_matrix(n_groups=300, max_group=9, n_cols=10, bc_cols=(1, 4, 8)):
    sizes = _RNG.integers(1, max_group + 1, size=n_groups)
    group_starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.intp)
    n_rows = int(sizes.sum())
    X = _RNG.normal(size=(n_rows, n_cols)).astype(np.float32)
    group_id = np.repeat(np.arange(n_groups), sizes)
    for c in bc_cols:
        X[:, c] = _RNG.normal(size=n_groups).astype(np.float32)[group_id]
    mask = np.zeros(n_cols, dtype=bool)
    mask[list(bc_cols)] = True
    return X, mask, group_starts, group_id


@pytest.mark.parametrize("row_block", [1, 5, 64, 1_000_000])
def test_collapse_matches_reference_when_invariant(row_block):
    X, mask, group_starts, _ = _grouped_matrix()
    X[_RNG.integers(0, len(X), size=40), 4] = np.nan  # partial NaNs inside groups
    got, violation = _collapse_invariant_groups(X, mask, group_starts, row_block, 1e-6)
    expected, expected_violation = _reference_collapse(X, mask, group_starts, 1e-6)
    assert violation is None and expected_violation is None
    np.testing.assert_array_equal(got, expected)
    assert got.dtype == X.dtype


@pytest.mark.parametrize("row_block", [1, 5, 64, 1_000_000])
def test_collapse_reports_the_same_first_violation(row_block):
    X, mask, group_starts, group_id = _grouped_matrix()
    for g, col in ((210, 8), (57, 4), (57, 1)):
        rows = np.flatnonzero(group_id == g)
        if len(rows) < 2:
            rows = np.flatnonzero(group_id == g + 1)
        X[rows[-1], col] += 1.0
    _, violation = _collapse_invariant_groups(X, mask, group_starts, row_block, 1e-6)
    _, expected = _reference_collapse(X, mask, group_starts, 1e-6)
    assert violation is not None
    assert violation[:2] == expected[:2]
    assert violation[2] == pytest.approx(expected[2])


def test_collapse_all_nan_group_never_violates():
    X, mask, group_starts, group_id = _grouped_matrix()
    X[group_id == 3, 1] = np.nan
    _, violation = _collapse_invariant_groups(X, mask, group_starts, 16, 1e-6)
    assert violation is None


# ---------------------------------------------------------------------------
# Memory bound (tracemalloc; memmap-backed input, as in a disk-backed cell)
# ---------------------------------------------------------------------------


def _memmap(tmp_path, n_rows, n_cols, name):
    X = np.memmap(tmp_path / name, dtype=np.float32, mode="w+", shape=(n_rows, n_cols))
    for start in range(0, n_rows, 50_000):
        stop = min(start + 50_000, n_rows)
        X[start:stop] = _RNG.normal(size=(stop - start, n_cols)).astype(np.float32)
    X.flush()
    return X


def _peak_bytes(fn):
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.performance
def test_blocked_std_peak_is_bounded_by_the_block_not_the_cell(tmp_path):
    n_rows, n_cols, row_block = 400_000, 40, 20_000
    X = _memmap(tmp_path, n_rows, n_cols, "std.memmap")
    cell_f64_bytes = n_rows * n_cols * 8
    peak = _peak_bytes(lambda: _blocked_column_std(X, row_block))
    # Allowance: a few row_block-sized float64 temporaries. np.std here would be >= 1x.
    assert peak < 4 * row_block * n_cols * 8
    assert peak < cell_f64_bytes / 4


@pytest.mark.performance
def test_collapse_peak_is_bounded_by_the_block_not_the_column_slice(tmp_path):
    n_groups, per_group, n_cols, row_block = 40_000, 10, 40, 20_000
    n_rows = n_groups * per_group
    X = _memmap(tmp_path, n_rows, n_cols, "bc.memmap")
    mask = np.zeros(n_cols, dtype=bool)
    mask[:10] = True
    group_starts = np.arange(0, n_rows, per_group, dtype=np.intp)
    full_slice_bytes = n_rows * int(mask.sum()) * 4
    peak = _peak_bytes(lambda: _collapse_invariant_groups(X, mask, group_starts, row_block, np.inf))
    collapsed_bytes = n_groups * int(mask.sum()) * 4
    # Output + a few block-sized temporaries; the old full-height slice alone is 1x.
    assert peak < collapsed_bytes + 6 * row_block * int(mask.sum()) * 4
    assert peak < full_slice_bytes / 2


class _StopAfterSetup(Exception):
    pass


@pytest.mark.performance
def test_cross_sectional_cell_setup_phase_is_memory_bounded(tmp_path, monkeypatch):
    """End to end: the disk-backed cell's setup (degenerate detection + X_nd build) must
    not allocate anything cell-sized. Stops at the first post-setup step."""
    from tests.unit.test_ic_engine_cell_memory_bound import _make_config

    n_features = len(ic_module._FEATURE_NAMES)
    n_rows = 200_000  # cell must dwarf the block for the bound to be distinguishable
    config = dataclasses.replace(
        _make_config(memmap_scratch_dir=str(tmp_path / "scratch")), corr_row_block=5_000
    )
    X_raw = _memmap(tmp_path, n_rows, n_features, "cell.memmap")

    def _stop(*_args, **_kwargs):
        raise _StopAfterSetup

    monkeypatch.setattr(ic_module, "_streaming_feature_correlation", _stop)
    cell_f32_bytes = n_rows * n_features * 4

    def _run():
        with ExitStack() as stack, pytest.raises(_StopAfterSetup):
            ic_module._compute_one_cross_sectional_cell(
                "all",
                X_raw=X_raw,
                returns_mat=np.zeros((n_rows, 1), dtype=np.float32),
                complete_mat=np.ones((n_rows, 1), dtype=bool),
                config=config,
                tf="1h",
                rng=np.random.default_rng(0),
                training_window_end=None,
                feature_status_map=None,
                run_ts=datetime.now(UTC),
                prior_e_values={},
                disk_backed=True,
                cleanup_stack=stack,
            )

    peak = _peak_bytes(_run)
    block_f64_bytes = config.corr_row_block * n_features * 8
    # A few block-sized temporaries; the old np.std alone allocated 2x the float32 cell.
    assert peak < 4 * block_f64_bytes
    assert peak < cell_f32_bytes / 4
