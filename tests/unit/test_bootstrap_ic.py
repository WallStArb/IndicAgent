"""Unit tests: corrected circular block bootstrap CI (Component A, todo 091, Phase 143.1-01).

Tests verify that `_circular_block_bootstrap_ic()` from
src.intelligence.statistics.ic_math:
  1. Resamples + re-ranks RAW paired observations per iteration (guards against the
     pre-ranking bug the 2026-06-26 removed version had -- see Pitfall 3/RESEARCH.md).
  2. CI width shrinks as N grows (asymptotic consistency, same property _fisher_z_ci
     must have).
  3. Same seed produces identical bounds across two independent calls (determinism --
     required for worker-safe reproducibility under ProcessPoolExecutor).
  4. Circular-wrap block indices near the boundary stay in-range and do not raise, even
     when block_size exceeds n.

No DB, no Kafka. Pure numpy/scipy.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scipy.stats import rankdata

from src.intelligence.statistics.ic_math import (
    _circular_block_bootstrap_ic,
    _vectorized_ic,
    circular_block_bootstrap_ic_serial,
)


def _buggy_pre_ranked_bootstrap(
    ranks_X: np.ndarray,
    ranks_Y: np.ndarray,
    block_size: int,
    n_boot: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Reproduction of the REMOVED (buggy) bootstrap (git commit c6f5056b^) for
    comparison only -- NOT imported from production code. Resamples already-globally-
    ranked values and never re-ranks the resampled subset. This is the exact defect
    the 2026-07-09 diagnostic proved exists; this helper exists solely so the test
    below can assert the corrected version behaves differently.
    """
    n, p = ranks_X.shape
    n_blocks = math.ceil(n / block_size)
    boot_ics = np.zeros((n_boot, p))
    offsets = np.arange(block_size)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        boot_ics[b] = _vectorized_ic(ranks_X[idx], ranks_Y[idx])
    ci_lower = np.percentile(boot_ics, 2.5, axis=0)
    ci_upper = np.percentile(boot_ics, 97.5, axis=0)
    return ci_lower, ci_upper


def _ar1_fixture(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic AR(1)-like paired series with strong local autocorrelation, so a
    circularly-resampled block changes local rank order relative to the full series
    (the condition under which pre-ranked-resampling and re-rank-per-iteration diverge).
    """
    gen = np.random.default_rng(seed)
    noise = gen.normal(size=n)
    y_raw = np.cumsum(noise)  # random walk -- strong autocorrelation
    x_raw = np.roll(y_raw, 1) + gen.normal(scale=0.1, size=n)  # lag-1 correlated with y
    return x_raw, y_raw


def test_reranking_differs_from_pre_ranked_resampling():
    """Resample+re-rank must yield a DIFFERENT CI than resampling pre-ranked values,
    on an AR(1) fixture where a resampled block changes local rank order."""
    n = 300
    block_size = 10
    n_boot = 200
    x_raw, y_raw = _ar1_fixture(n, seed=7)

    ranks_X = rankdata(x_raw.reshape(-1, 1), axis=0)
    ranks_Y = rankdata(y_raw)

    rng_old = np.random.default_rng(42)
    ci_lower_old, ci_upper_old = _buggy_pre_ranked_bootstrap(
        ranks_X, ranks_Y, block_size, n_boot, rng_old
    )

    rng_new = np.random.default_rng(42)
    ci_lower_new, ci_upper_new = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_new
    )

    differs = not np.allclose(ci_lower_old, ci_lower_new, atol=1e-9) or not np.allclose(
        ci_upper_old, ci_upper_new, atol=1e-9
    )
    assert differs, (
        "Re-ranking the resampled subset must produce a different CI than resampling "
        f"pre-ranked values: old=({ci_lower_old}, {ci_upper_old}), "
        f"new=({ci_lower_new}, {ci_upper_new})"
    )


def test_bootstrap_ci_width_shrinks_with_n():
    """CI width must decrease as N increases (same asymptotic consistency property
    _fisher_z_ci is held to)."""
    block_size = 10
    n_boot = 500

    x_small, y_small = _ar1_fixture(200, seed=11)
    x_large, y_large = _ar1_fixture(2000, seed=11)

    rng_small = np.random.default_rng(1)
    ci_lower_small, ci_upper_small = _circular_block_bootstrap_ic(
        x_small.reshape(-1, 1), y_small, block_size, n_boot, rng_small
    )

    rng_large = np.random.default_rng(1)
    ci_lower_large, ci_upper_large = _circular_block_bootstrap_ic(
        x_large.reshape(-1, 1), y_large, block_size, n_boot, rng_large
    )

    width_small = ci_upper_small - ci_lower_small
    width_large = ci_upper_large - ci_lower_large

    assert np.all(width_large < width_small), (
        f"CI width did not shrink with N: width_small={width_small}, " f"width_large={width_large}"
    )


def test_determinism_same_seed_identical_bounds():
    """Same seed must produce IDENTICAL bounds across two independent calls -- required
    for worker-safe reproducibility under ProcessPoolExecutor (no shared RNG state)."""
    n = 400
    block_size = 10
    n_boot = 300
    x_raw, y_raw = _ar1_fixture(n, seed=3)

    rng_a = np.random.default_rng(99)
    ci_lower_a, ci_upper_a = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_a
    )

    rng_b = np.random.default_rng(99)
    ci_lower_b, ci_upper_b = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_b
    )

    np.testing.assert_array_equal(ci_lower_a, ci_lower_b)
    np.testing.assert_array_equal(ci_upper_a, ci_upper_b)


def test_threaded_matches_serial_bit_for_bit():
    """max_workers>1 must produce IDENTICAL CI bounds to max_workers=1 (the historical
    default) given the same seed and inputs -- threading changes execution order only,
    never the sequence of RNG draws or which draw feeds which output slot."""
    n = 800
    block_size = 10
    n_boot = 137  # deliberately not a multiple of any worker count, to exercise the
    # final partial batch
    x_raw, y_raw = _ar1_fixture(n, seed=21)

    rng_serial = np.random.default_rng(7)
    ci_lower_serial, ci_upper_serial = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_serial, max_workers=1
    )

    rng_threaded = np.random.default_rng(7)
    ci_lower_threaded, ci_upper_threaded = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_threaded, max_workers=8
    )

    np.testing.assert_array_equal(ci_lower_serial, ci_lower_threaded)
    np.testing.assert_array_equal(ci_upper_serial, ci_upper_threaded)


def test_threaded_determinism_same_seed_identical_bounds():
    """Same seed must produce IDENTICAL bounds across two independent threaded calls --
    threading must not introduce nondeterminism from thread-scheduling order."""
    n = 800
    block_size = 10
    n_boot = 137
    x_raw, y_raw = _ar1_fixture(n, seed=21)

    rng_a = np.random.default_rng(55)
    ci_lower_a, ci_upper_a = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_a, max_workers=8
    )

    rng_b = np.random.default_rng(55)
    ci_lower_b, ci_upper_b = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_b, max_workers=8
    )

    np.testing.assert_array_equal(ci_lower_a, ci_lower_b)
    np.testing.assert_array_equal(ci_upper_a, ci_upper_b)


def test_circular_wrap_handles_boundary_without_raising():
    """Circular-wrap block indices must stay in-range (max index < n) and must not
    raise, even when block_size exceeds n (forces heavy wraparound)."""
    n = 5
    block_size = 10  # larger than n -- forces wraparound within a single block
    n_boot = 50
    x_raw, y_raw = _ar1_fixture(n, seed=13)

    rng = np.random.default_rng(5)
    ci_lower, ci_upper = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng
    )

    assert ci_lower.shape == (1,)
    assert ci_upper.shape == (1,)
    assert np.all(np.isfinite(ci_lower)), f"ci_lower contains non-finite: {ci_lower}"
    assert np.all(np.isfinite(ci_upper)), f"ci_upper contains non-finite: {ci_upper}"


def test_circular_block_bootstrap_ic_serial_matches_max_workers_1():
    """The per-symbol call sites' wrapper (no max_workers knob) must produce bit-
    identical output to calling the underlying function directly with max_workers=1 --
    it's a thin delegator, not a reimplementation."""
    n = 200
    block_size = 10
    n_boot = 50
    x_raw, y_raw = _ar1_fixture(n, seed=7)

    rng_direct = np.random.default_rng(3)
    ci_lower_direct, ci_upper_direct = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_direct, max_workers=1
    )

    rng_wrapper = np.random.default_rng(3)
    ci_lower_wrapper, ci_upper_wrapper = circular_block_bootstrap_ic_serial(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng_wrapper
    )

    np.testing.assert_array_equal(ci_lower_direct, ci_lower_wrapper)
    np.testing.assert_array_equal(ci_upper_direct, ci_upper_wrapper)


def test_circular_wrap_handles_boundary_without_raising_threaded():
    """Same heavy-wraparound boundary case as above, but through the max_workers>1
    path -- the wraparound/index-safety guarantee must hold under threading too, not
    just in the serial default."""
    n = 5
    block_size = 10
    n_boot = 50
    x_raw, y_raw = _ar1_fixture(n, seed=13)

    rng = np.random.default_rng(5)
    ci_lower, ci_upper = _circular_block_bootstrap_ic(
        x_raw.reshape(-1, 1), y_raw, block_size, n_boot, rng, max_workers=8
    )

    assert ci_lower.shape == (1,)
    assert ci_upper.shape == (1,)
    assert np.all(np.isfinite(ci_lower)), f"ci_lower contains non-finite: {ci_lower}"
    assert np.all(np.isfinite(ci_upper)), f"ci_upper contains non-finite: {ci_upper}"
