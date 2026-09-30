from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.measure.proposer import propose
from src.intelligence.measure.targets import stack_targets
from src.intelligence.measure.term_structure import term_structure
from tests.unit.measure.conftest import SLOTS, all_present, make_panel


def test_term_structure_equals_proposer_per_horizon(symbols, params):
    panel = make_panel(symbols, 150, 1, seed=3)
    rng = np.random.default_rng(4)
    present = rng.random((150, len(symbols))) > 0.1  # some (bar, symbol) rows do not exist
    feats = rng.normal(size=(150, len(symbols), 2))
    ts = term_structure(
        feats, ("a", "b"), [panel], (1, 2, 5), "2027-01-01", params, present=present
    )
    assert ts.ic.shape == (2, 3)
    for h_idx, h in enumerate((1, 2, 5)):
        stack = stack_targets([panel], h, "2027-01-01")
        cell = propose(feats, ("a", "b"), stack, params, present=present).cell
        assert np.array_equal(ts.ic[:, h_idx], cell.ic)
    expected = np.asarray((1, 2, 5))[np.argmax(np.abs(ts.ic), axis=1)]
    assert ts.peak_horizon.tolist() == expected.tolist()


def test_intraday_horizon_across_session_is_refused_first(symbols, params):
    panel = make_panel(symbols, 10, SLOTS, seed=5)
    feats = np.zeros((10 * SLOTS, len(symbols), 1))
    with pytest.raises(ValueError, match="1d clock"):
        term_structure(
            feats,
            ("a",),
            [panel],
            (1, SLOTS),
            "2027-01-01",
            params,
            present=all_present(feats.shape[:2]),
        )


def test_list_arguments_are_stored_as_tuples_and_detached_from_the_caller(symbols, params):
    panel = make_panel(symbols, 150, 1, seed=3)
    rng = np.random.default_rng(4)
    feats = rng.normal(size=(150, len(symbols), 2))
    present = all_present(feats.shape[:2])
    names, horizons = ["a", "b"], [1, 2, 5]
    from_lists = term_structure(
        feats, names, [panel], horizons, "2027-01-01", params, present=present
    )
    names.append("mutated")
    horizons.append(99)
    twin = term_structure(
        feats, ("a", "b"), [panel], (1, 2, 5), "2027-01-01", params, present=present
    )
    assert isinstance(from_lists.features, tuple) and isinstance(from_lists.horizons, tuple)
    assert from_lists.features == twin.features == ("a", "b")
    assert from_lists.horizons == twin.horizons == (1, 2, 5)
    assert np.array_equal(from_lists.ic, twin.ic, equal_nan=True)
    assert hash(from_lists.features) == hash(twin.features)


def test_blocks_with_family_completeness_merge_to_the_whole_term_structure(symbols, params):
    from src.intelligence.measure.ic import FamilyCompleteness, existing_rows
    from src.intelligence.measure.term_structure import merge_term_structures

    panel = make_panel(symbols, 150, 1, seed=3)
    rng = np.random.default_rng(4)
    present = rng.random((150, len(symbols))) > 0.1
    feats = rng.normal(size=(150, len(symbols), 6))
    feats[rng.random((150, len(symbols))) < 0.05, 4] = np.nan
    names = tuple(f"f{i}" for i in range(6))
    end = "2027-01-01"
    whole = term_structure(feats, names, [panel], (1, 2, 5), end, params, present=present)
    stack = stack_targets([panel], 1, end)
    rows = existing_rows(stack.valid_grid(), present).reshape(-1)
    family = FamilyCompleteness(params)
    parts = []
    for first, stop in ((0, 3), (3, 6)):
        family.add(feats[:, :, first:stop].reshape(-1, stop - first)[rows])
    for first, stop in ((0, 3), (3, 6)):
        parts.append(
            term_structure(
                feats[:, :, first:stop],
                names[first:stop],
                [panel],
                (1, 2, 5),
                end,
                params,
                present=present,
                complete=family.complete,
            )
        )
    merged = merge_term_structures(parts)
    assert merged.features == whole.features
    for field in ("ic", "n_obs", "p_value", "peak_horizon"):
        assert np.array_equal(getattr(merged, field), getattr(whole, field), equal_nan=True), field
    with pytest.raises(ValueError, match="horizons"):
        merge_term_structures(
            [
                parts[0],
                term_structure(
                    feats[:, :, :3], names[:3], [panel], (1,), end, params, present=present
                ),
            ]
        )
