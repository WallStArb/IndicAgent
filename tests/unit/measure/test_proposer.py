from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.proposer import propose
from src.intelligence.measure.targets import stack_targets
from tests.unit.measure.conftest import make_panel


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
    res = propose(feats, ("f0", "f1"), stack, params)
    assert res.cell.ic[0] > 0.5
    assert abs(res.cell.ic[1]) < 0.1
    assert res.passes_fdr.tolist() == [True, False]
    assert res.bh_adjusted_p[0] < params.fdr_alpha


def test_stride_is_max_of_min_stride_and_horizon(symbols, params):
    panel = make_panel(symbols, 200, 1, seed=11)
    feats = np.random.default_rng(0).normal(size=(200, len(symbols), 1))
    h3 = stack_targets([panel], 3, "2027-01-01")
    assert propose(feats, ("f",), h3, params).cell.stride == 3
    big = dataclasses.replace(params, min_stride=5)
    assert propose(feats, ("f",), h3, big).cell.stride == 5
    h1 = stack_targets([panel], 1, "2027-01-01")
    assert propose(feats, ("f",), h1, params).cell.stride == 1


def test_invalid_rows_are_excluded(symbols, params):
    stack, feats = _fixture(symbols)
    stack = dataclasses.replace(stack, valid=np.zeros_like(stack.valid))
    res = propose(feats, ("f0", "f1"), stack, params)
    assert np.isnan(res.cell.ic).all() and not res.passes_fdr.any()
