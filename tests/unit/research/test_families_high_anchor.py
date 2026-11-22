"""Family 9 kernel (52-week-high anchoring): the pure high_distance on small synthetic closes."""

import numpy as np
import pytest

from src.intelligence.research.families import high_anchor
from src.intelligence.research.families.high_anchor import high_distance, high_distance_member


def _reference(close: np.ndarray, window: int, min_finite: int) -> np.ndarray:
    """The definition, one cell at a time."""
    out = np.full(close.shape, np.nan)
    for d in range(window - 1, len(close)):
        for i in range(close.shape[1]):
            w = close[d - window + 1 : d + 1, i]
            fin = w[np.isfinite(w)]
            if np.isfinite(close[d, i]) and len(fin) >= min_finite and fin.max() > 0:
                out[d, i] = (close[d, i] - fin.max()) / fin.max()
    return out


def _closes(seed=0, sessions=40, names=6):
    rng = np.random.default_rng(seed)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, (sessions, names)), axis=0))
    c[5:8, 1] = np.nan  # a gap
    c[:12, 2] = np.nan  # a late listing
    return c


def test_matches_the_definition_cell_by_cell():
    c = _closes()
    got = high_distance(c, window=10, min_finite=8)
    np.testing.assert_allclose(got, _reference(c, 10, 8), equal_nan=True, rtol=1e-12)


def test_new_high_is_zero_and_values_are_never_positive():
    c = np.array([[1.0], [2.0], [3.0], [2.0], [4.0], [3.0]])
    got = high_distance(c, window=3, min_finite=3)[:, 0]
    assert np.isnan(got[:2]).all()
    np.testing.assert_allclose(got[2:], [0.0, (2 - 3) / 3, 0.0, (3 - 4) / 4])
    assert np.nanmax(got) <= 0.0


def test_the_high_leaves_the_window_exactly_at_the_edge():
    c = np.array([[10.0], [5.0], [5.0], [5.0], [6.0]])
    got = high_distance(c, window=4, min_finite=4)[:, 0]
    assert got[3] == pytest.approx(5 / 10 - 1)  # window rows 0..3 still holds 10
    assert got[4] == pytest.approx(6 / 6 - 1)  # row 0 has left the window


def test_min_finite_rule_masks_a_window_that_could_hide_the_high():
    c = np.array([[1.0], [2.0], [np.nan], [1.5], [1.4]])
    assert np.isnan(high_distance(c, window=4, min_finite=4)[3, 0])
    assert high_distance(c, window=4, min_finite=3)[3, 0] == pytest.approx(1.5 / 2 - 1)


def test_a_window_reaching_before_the_panel_is_not_filled():
    c = np.full((6, 1), 3.0)
    got = high_distance(c, window=5, min_finite=1)[:, 0]
    assert np.isnan(got[:4]).all() and got[4] == 0.0


def test_missing_own_close_and_non_positive_maximum_are_nan():
    c = np.array([[1.0, -2.0], [2.0, -1.0], [np.nan, -3.0], [1.0, 0.0]])
    got = high_distance(c, window=3, min_finite=2)
    assert np.isnan(got[2, 0]) and got[3, 0] == pytest.approx(1 / 2 - 1)
    assert np.isnan(got[2:, 1]).all()  # maximum -1 then 0 is not positive


def test_invariant_to_a_constant_rescale_of_a_name():
    c = _closes(seed=3)
    scaled = c.copy()
    scaled[:, 4] *= 37.0
    np.testing.assert_allclose(
        high_distance(scaled, window=10, min_finite=8)[:, 4],
        high_distance(c, window=10, min_finite=8)[:, 4],
        equal_nan=True,
        rtol=1e-12,
    )


def test_causal_a_later_close_never_moves_an_earlier_row():
    c = _closes(seed=5)
    base = high_distance(c, window=10, min_finite=8)
    changed = c.copy()
    changed[25:] *= 3.0
    after = high_distance(changed, window=10, min_finite=8)
    np.testing.assert_array_equal(base[:25], after[:25])


def test_full_size_window_has_no_value_before_row_251():
    c = _closes(sessions=300, names=3)
    c[:, 0] = np.where(np.isfinite(c[:, 0]), c[:, 0], 100.0)
    got = high_distance(c, window=252, min_finite=240)[:, 0]
    assert np.isnan(got[:251]).all() and np.isfinite(got[251:]).all()


def test_member_ranks_the_nearer_name_higher_and_follows_the_contract():
    c = np.array([[1.0, 1.0, 1.0], [2.0, 2.0, 3.0], [3.0, 2.5, 3.0], [3.0, 1.5, 0.9]])
    # row 3, window rows 1..3: name 0 at its high, name 1 at -0.4, name 2 at -0.7
    alpha = high_distance_member(c, bars_per_session=1, coverage_floor=2, window=3, min_finite=3)
    assert alpha[3, 0] > alpha[3, 1] > alpha[3, 2]
    assert alpha[3, 0] == pytest.approx(0.5) and alpha[3, 2] == pytest.approx(-0.5)
    with pytest.raises(ValueError, match="1d panel"):
        high_distance_member(c, bars_per_session=78, coverage_floor=2, window=3, min_finite=3)


def test_arguments_are_checked():
    with pytest.raises(ValueError, match="min_finite"):
        high_distance(np.ones((5, 1)), window=3, min_finite=4)
    with pytest.raises(ValueError, match="sessions, names"):
        high_distance(np.ones(5), window=3, min_finite=2)


def test_the_family_names_no_battery_so_a_run_is_refused_before_the_ledger():
    assert not hasattr(high_anchor, "NULL_BATTERY")
