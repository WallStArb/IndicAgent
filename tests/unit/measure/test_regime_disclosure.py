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
