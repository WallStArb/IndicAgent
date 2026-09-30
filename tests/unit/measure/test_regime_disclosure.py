from __future__ import annotations

import numpy as np

from src.intelligence.measure.ic import observation_rows, pooled_rank_ic
from src.intelligence.measure.regime_disclosure import regime_volatility_disclosure
from src.intelligence.measure.targets import stack_targets
from tests.unit.measure.conftest import all_present, make_panel


def test_one_cell_per_label_and_unlabelled_counted(symbols, params):
    stack = stack_targets([make_panel(symbols, 120, 1, seed=13)], 1, "2027-01-01")
    n, m = stack.targets.shape
    rng = np.random.default_rng(14)
    feats = rng.normal(size=(n, m, 2))
    labels = np.where(np.arange(n)[:, None] % 2 == 0, "low", "high").astype(object)
    labels = np.repeat(labels, m, axis=1)
    labels[5, :] = None
    labels[6, 0] = ""
    cells, n_unlabelled = regime_volatility_disclosure(
        feats, ("a", "b"), stack, labels, params, present=all_present((n, m))
    )
    assert set(cells) == {"low", "high"}
    assert n_unlabelled == m + 1
    mask = (labels == "low") & stack.valid[:, None]
    X, y = observation_rows(feats, stack.targets, mask)
    want = pooled_rank_ic(X, y, stride=1, params=params, feature_names=("a", "b"))
    assert np.array_equal(cells["low"].ic, want.ic, equal_nan=True)


def test_numeric_codes_with_nan(symbols, params):
    stack = stack_targets([make_panel(symbols, 80, 1, seed=13)], 1, "2027-01-01")
    n, m = stack.targets.shape
    feats = np.random.default_rng(15).normal(size=(n, m, 1))
    codes = np.zeros((n, m))
    codes[::2] = 1.0
    codes[3] = np.nan
    cells, n_unlabelled = regime_volatility_disclosure(
        feats, ("a",), stack, codes, params, present=all_present((n, m))
    )
    assert set(cells) == {"0.0", "1.0"} and n_unlabelled == m


def test_label_row_masks_partition_the_labelled_existing_rows(symbols, params):
    from src.intelligence.measure.regime_disclosure import label_row_masks

    n, m = 30, len(symbols)
    labels = np.where(np.arange(n)[:, None] % 3 == 0, "a", "b").astype(object)
    labels = np.repeat(labels, m, axis=1)
    labels[4, :] = None
    existing = np.ones((n, m), dtype=bool)
    existing[7, 1] = False
    masks, n_unlabelled = label_row_masks(existing, labels)
    assert list(masks) == ["a", "b"] and n_unlabelled == m
    assert not (masks["a"] & masks["b"]).any()
    assert int(masks["a"].sum() + masks["b"].sum()) == n * m - m - 1


def test_blocks_with_per_label_family_completeness_equal_the_whole_family(symbols, params):
    from src.intelligence.measure.ic import FamilyCompleteness
    from src.intelligence.measure.regime_disclosure import label_row_masks

    stack = stack_targets([make_panel(symbols, 150, 1, seed=13)], 1, "2027-01-01")
    n, m = stack.targets.shape
    rng = np.random.default_rng(14)
    feats = rng.normal(size=(n, m, 6))
    feats[rng.random((n, m)) < 0.05, 4] = np.nan
    labels = np.repeat(np.where(np.arange(n)[:, None] % 2 == 0, "low", "high"), m, axis=1)
    present = all_present((n, m))
    names = tuple(f"f{i}" for i in range(6))
    whole, _ = regime_volatility_disclosure(feats, names, stack, labels, params, present=present)
    masks, _ = label_row_masks(stack.valid_grid() & present, labels)
    families = {label: FamilyCompleteness(params) for label in masks}
    for first, stop in ((0, 3), (3, 6)):
        for label, mask in masks.items():
            families[label].add(feats[:, :, first:stop].reshape(-1, stop - first)[mask.reshape(-1)])
    complete = {label: fam.complete for label, fam in families.items()}
    for first, stop in ((0, 3), (3, 6)):
        cells, _ = regime_volatility_disclosure(
            feats[:, :, first:stop],
            names[first:stop],
            stack,
            labels,
            params,
            present=present,
            complete=complete,
        )
        for label, cell in cells.items():
            for field in ("ic", "p_value", "ci_lower", "ci_upper", "n_independent"):
                assert np.array_equal(
                    getattr(cell, field), getattr(whole[label], field)[first:stop], equal_nan=True
                ), (label, field)
