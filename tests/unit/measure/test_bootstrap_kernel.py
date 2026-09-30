"""The measure package bootstraps with the counting-rank numba kernel, bit-identical to the scipy
path while the sums of squared ranks stay exact in float64, drawn and run in slices of resamples.

CI-clean: no DB, no network.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from src.intelligence.measure import ic as measure_ic
from src.intelligence.measure.ic import pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.statistics.ic_math import _circular_block_bootstrap_ic

# (n rows, k features, block size, resamples, seed, stride)
_CELLS = [
    (300, 6, 5, 200, 1, 1),
    (2000, 12, 10, 500, 42, 3),
    (9000, 9, 26, 300, 7, 5),
    (1500, 5, 4, 100, 3, 2),
]


def _inputs(case: int, n: int, k: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(case)
    x = rng.normal(size=(n, k))
    x[:, 1] = np.round(x[:, 1], 1)  # ties
    x[:, 2] = 3.0  # constant: degenerate, never bootstrapped
    y = np.round(rng.normal(size=n) + 0.1 * x[:, 0], 4)  # ties in the target too
    return x, y


def _with(params: MeasureParams, **fields: int) -> MeasureParams:
    return dataclasses.replace(params, **fields)


def _scipy_reference(x, y, params, stride):
    rows = np.arange(0, len(y), stride)
    live = np.flatnonzero(np.nanstd(x, axis=0) >= params.degenerate_std)
    return (
        _circular_block_bootstrap_ic(
            x[rows][:, live],
            y[rows],
            params.bootstrap_block_size,
            params.bootstrap_resamples,
            np.random.default_rng(params.rng_seed),
        ),
        live,
    )


@pytest.mark.parametrize("case", range(len(_CELLS)))
def test_kernel_ci_equals_the_scipy_bootstrap_bit_for_bit(params, case: int) -> None:
    n, k, block, resamples, seed, stride = _CELLS[case]
    x, y = _inputs(case, n, k)
    p = _with(
        params,
        bootstrap_block_size=block,
        bootstrap_resamples=resamples,
        rng_seed=seed,
        min_obs=30,
    )
    cell = pooled_rank_ic(x, y, stride=stride, params=p)
    (lo, hi), live = _scipy_reference(x, y, p, stride)
    assert np.array_equal(cell.ci_lower[live], lo)
    assert np.array_equal(cell.ci_upper[live], hi)
    assert np.isnan(cell.ci_lower[2]) and np.isnan(cell.ci_upper[2])  # the constant column


def test_the_cell_bootstraps_through_the_kernel_in_slices_of_the_chunk(
    params, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = measure_ic.blocked_bootstrap_ics

    def spy(dense, starts, offsets, n_valid, n_threads):
        calls.append(starts.shape[0])
        return real(dense, starts, offsets, n_valid, n_threads)

    monkeypatch.setattr(measure_ic, "blocked_bootstrap_ics", spy)
    x, y = _inputs(0, 400, 4)
    p = _with(params, bootstrap_resamples=45, bootstrap_chunk_resamples=20, min_obs=30)
    pooled_rank_ic(x, y, stride=1, params=p)
    assert calls == [20, 20, 5]


@pytest.mark.parametrize("chunk", [1, 7, 50, 51, 10_000])
def test_slice_size_never_moves_a_value(params, chunk: int) -> None:
    x, y = _inputs(1, 1200, 7)
    base = _with(params, bootstrap_resamples=50, min_obs=30, bootstrap_chunk_resamples=50)
    reference = pooled_rank_ic(x, y, stride=2, params=base)
    cell = pooled_rank_ic(x, y, stride=2, params=_with(base, bootstrap_chunk_resamples=chunk))
    assert np.array_equal(cell.ci_lower, reference.ci_lower, equal_nan=True)
    assert np.array_equal(cell.ci_upper, reference.ci_upper, equal_nan=True)


def test_sliced_draws_equal_one_draw_exactly() -> None:
    """The invariant the slicing rests on: slices of the start matrix drawn in order from one
    generator are the rows of a single batched draw."""
    n_valid, n_blocks, resamples, chunk = 12345, 77, 1000, 250
    whole = np.random.default_rng(42).integers(0, n_valid, size=(resamples, n_blocks))
    rng = np.random.default_rng(42)
    parts = [
        rng.integers(0, n_valid, size=(min(chunk, resamples - first), n_blocks))
        for first in range(0, resamples, chunk)
    ]
    assert np.array_equal(np.concatenate(parts), whole)


@pytest.mark.parametrize("threads", [1, 2, 4])
def test_thread_count_never_moves_a_value(params, threads: int) -> None:
    x, y = _inputs(2, 3000, 8)
    base = _with(params, bootstrap_resamples=64, min_obs=30, bootstrap_threads=1)
    reference = pooled_rank_ic(x, y, stride=1, params=base)
    cell = pooled_rank_ic(x, y, stride=1, params=_with(base, bootstrap_threads=threads))
    assert np.array_equal(cell.ci_lower, reference.ci_lower, equal_nan=True)
    assert np.array_equal(cell.ci_upper, reference.ci_upper, equal_nan=True)


# ---------------------------------------------------------------------------
# Jobs that discard the CI do not compute it
# ---------------------------------------------------------------------------


def _spy_slices(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = measure_ic.blocked_bootstrap_ics

    def spy(dense, starts, offsets, n_valid, n_threads):
        calls.append(starts.shape[0])
        return real(dense, starts, offsets, n_valid, n_threads)

    monkeypatch.setattr(measure_ic, "blocked_bootstrap_ics", spy)
    return calls


def test_bootstrap_false_drops_only_the_interval(params) -> None:
    x, y = _inputs(3, 1500, 6)
    p = _with(params, bootstrap_resamples=40, min_obs=30)
    full = pooled_rank_ic(x, y, stride=2, params=p)
    skipped = pooled_rank_ic(x, y, stride=2, params=p, bootstrap=False)
    for field in ("ic", "p_value"):
        assert np.array_equal(getattr(skipped, field), getattr(full, field), equal_nan=True)
    for field in ("n_obs", "n_independent", "reliable"):
        assert np.array_equal(getattr(skipped, field), getattr(full, field))
    assert np.isnan(skipped.ci_lower).all() and np.isnan(skipped.ci_upper).all()
    assert np.isfinite(full.ci_lower[full.reliable]).all()


def test_term_structure_bootstraps_only_the_proposer_horizon(
    symbols, params, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.intelligence.measure.proposer import propose
    from src.intelligence.measure.targets import stack_targets
    from src.intelligence.measure.term_structure import term_structure
    from tests.unit.measure.conftest import all_present, make_panel

    panel = make_panel(symbols, 150, 1, seed=3)
    feats = np.random.default_rng(4).normal(size=(150, len(symbols), 3))
    present = all_present(feats.shape[:2])
    p = _with(params, bootstrap_resamples=40, bootstrap_chunk_resamples=40)
    calls = _spy_slices(monkeypatch)
    term = term_structure(
        feats, ("a", "b", "c"), [panel], (2, 1, 5), "2027-01-01", p, present=present
    )
    assert calls == [40]  # one cell's resamples, not three cells'
    reference = propose(
        feats, ("a", "b", "c"), stack_targets([panel], 2, "2027-01-01"), p, present=present
    ).cell
    cell = term.proposer_cell
    for field in ("ic", "p_value", "ci_lower", "ci_upper", "n_independent", "n_obs", "reliable"):
        assert np.array_equal(getattr(cell, field), getattr(reference, field), equal_nan=True)
    assert np.array_equal(term.ic[:, 0], reference.ic, equal_nan=True)


def test_monitoring_never_bootstraps(symbols, params, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.intelligence.measure.monitoring import member_ic_over_time
    from src.intelligence.measure.targets import stack_targets
    from tests.unit.measure.conftest import all_present, make_panel

    panel = make_panel(symbols, 60, 1, seed=3)
    stack = stack_targets([panel], 1, "2027-01-01")
    feat = np.random.default_rng(4).normal(size=stack.targets.shape)
    calls = _spy_slices(monkeypatch)
    series = member_ic_over_time(feat, "m", stack, params, present=all_present(feat.shape))
    assert calls == [] and np.isfinite(series.ic).any()
