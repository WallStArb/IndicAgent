from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.measure.proposer import propose
from src.intelligence.measure.targets import stack_targets
from src.intelligence.measure.term_structure import term_structure
from tests.unit.measure.conftest import SLOTS, make_panel


def test_term_structure_equals_proposer_per_horizon(symbols, params):
    panel = make_panel(symbols, 150, 1, seed=3)
    rng = np.random.default_rng(4)
    feats = rng.normal(size=(150, len(symbols), 2))
    ts = term_structure(feats, ("a", "b"), [panel], (1, 2, 5), "2027-01-01", params)
    assert ts.ic.shape == (2, 3)
    for h_idx, h in enumerate((1, 2, 5)):
        stack = stack_targets([panel], h, "2027-01-01")
        cell = propose(feats, ("a", "b"), stack, params).cell
        assert np.array_equal(ts.ic[:, h_idx], cell.ic)
    expected = np.asarray((1, 2, 5))[np.argmax(np.abs(ts.ic), axis=1)]
    assert ts.peak_horizon.tolist() == expected.tolist()


def test_intraday_horizon_across_session_is_refused_first(symbols, params):
    panel = make_panel(symbols, 10, SLOTS, seed=5)
    feats = np.zeros((10 * SLOTS, len(symbols), 1))
    with pytest.raises(ValueError, match="1d clock"):
        term_structure(feats, ("a",), [panel], (1, SLOTS), "2027-01-01", params)
