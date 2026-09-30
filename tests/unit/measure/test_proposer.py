from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from src.intelligence.measure.proposer import propose
from src.intelligence.measure.targets import stack_targets
from tests.unit.measure.conftest import all_present, make_panel


def _fixture(symbols, sessions=200):
    panel = make_panel(symbols, sessions, 1, seed=11)
    stack = stack_targets([panel], 1, "2027-01-01")
    rng = np.random.default_rng(12)
    target = np.where(np.isfinite(stack.targets), stack.targets, 0.0)
    f0 = target + rng.normal(0, 0.005, target.shape)
    f1 = rng.normal(size=target.shape)
    return stack, np.stack([f0, f1], axis=-1)


def test_proposer_finds_signal_not_noise(symbols, params):
    stack, feats = _fixture(symbols)
    res = propose(feats, ("f0", "f1"), stack, params, present=all_present(stack.targets.shape))
    assert res.cell.ic[0] > 0.5
    assert abs(res.cell.ic[1]) < 0.1
    assert res.passes_fdr.tolist() == [True, False]
    assert res.bh_adjusted_p[0] < params.fdr_alpha


def test_stride_is_max_of_min_stride_and_horizon(symbols, params):
    panel = make_panel(symbols, 200, 1, seed=11)
    feats = np.random.default_rng(0).normal(size=(200, len(symbols), 1))
    ones = all_present(feats.shape[:2])
    h3 = stack_targets([panel], 3, "2027-01-01")
    assert propose(feats, ("f",), h3, params, present=ones).cell.stride == 3
    big = dataclasses.replace(params, min_stride=5)
    assert propose(feats, ("f",), h3, big, present=ones).cell.stride == 5
    h1 = stack_targets([panel], 1, "2027-01-01")
    assert propose(feats, ("f",), h1, params, present=ones).cell.stride == 1


def test_invalid_rows_are_excluded(symbols, params):
    stack, feats = _fixture(symbols)
    stack = dataclasses.replace(stack, valid=np.zeros_like(stack.valid))
    res = propose(feats, ("f0", "f1"), stack, params, present=all_present(stack.targets.shape))
    assert np.isnan(res.cell.ic).all() and not res.passes_fdr.any()


def _family(symbols, k=9):
    stack, feats = _fixture(symbols, sessions=120)
    rng = np.random.default_rng(21)
    extra = rng.normal(size=(*feats.shape[:2], k - 2))
    extra[rng.random(feats.shape[:2]) < 0.05, 3] = np.nan  # completeness couples the columns
    return stack, np.concatenate([feats, extra], axis=-1)


def test_blocked_cells_with_family_completeness_and_one_fdr_equal_the_whole_family(symbols, params):
    from src.intelligence.measure.ic import FamilyCompleteness, existing_rows, merge_cells
    from src.intelligence.measure.proposer import family_fdr, propose_cell

    stack, feats = _family(symbols)
    names = tuple(f"f{i}" for i in range(feats.shape[2]))
    present = all_present(stack.targets.shape)
    whole = propose(feats, names, stack, params, present=present)
    rows = existing_rows(stack.valid_grid(), present).reshape(-1)
    for size in (2, 4, 7):
        blocks = [slice(i, min(i + size, len(names))) for i in range(0, len(names), size)]
        if blocks[-1].stop - blocks[-1].start == 1:
            blocks[-2:] = [slice(blocks[-2].start, blocks[-1].stop)]
        family = FamilyCompleteness(params)
        for b in blocks:
            family.add(feats[:, :, b].reshape(-1, b.stop - b.start)[rows])
        cells = [
            propose_cell(
                feats[:, :, b], names[b], stack, params, present=present, complete=family.complete
            )
            for b in blocks
        ]
        merged = merge_cells(cells)
        adjusted, passes = family_fdr(merged.p_value, params.fdr_alpha)
        for field in ("ic", "p_value", "ci_lower", "ci_upper", "n_independent"):
            assert np.array_equal(
                getattr(merged, field), getattr(whole.cell, field), equal_nan=True
            ), (size, field)
        assert np.array_equal(adjusted, whole.bh_adjusted_p, equal_nan=True), size
        assert np.array_equal(passes, whole.passes_fdr), size


def test_family_fdr_leaves_missing_p_values_unadjusted():
    from src.intelligence.measure.proposer import family_fdr

    adjusted, passes = family_fdr(np.array([0.001, np.nan, 0.9, 0.002]), 0.05)
    assert np.isnan(adjusted[1]) and not passes[1]
    assert passes.tolist() == [True, False, False, True]
    assert family_fdr(np.array([np.nan, np.nan]), 0.05)[1].tolist() == [False, False]


def test_a_block_local_family_is_a_different_answer(symbols, params):
    stack, feats = _family(symbols)
    names = tuple(f"f{i}" for i in range(feats.shape[2]))
    present = all_present(stack.targets.shape)
    whole = propose(feats, names, stack, params, present=present)
    first = propose(feats[:, :, :3], names[:3], stack, params, present=present)
    # same features, but the cell is masked by its own block only and BH ranks only three p-values
    assert not np.array_equal(first.cell.n_independent, whole.cell.n_independent[:3])


def test_a_completeness_mask_admitting_a_non_finite_row_is_refused(symbols, params):
    from src.intelligence.measure.proposer import propose_cell

    stack, feats = _family(symbols)
    names = tuple(f"f{i}" for i in range(feats.shape[2]))
    present = all_present(stack.targets.shape)
    every_row = np.ones(int(stack.valid.sum()) * len(symbols), dtype=bool)
    with pytest.raises(ValueError, match="non-finite live feature"):
        propose_cell(feats, names, stack, params, present=present, complete=every_row)
