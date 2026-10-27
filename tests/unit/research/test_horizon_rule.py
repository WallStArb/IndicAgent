"""The horizon rule (design 4.4, plan 187-08)."""

import math

import numpy as np
import pytest

from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.spec import HorizonRuleSpec


def test_kappa_one_is_a_read_only_identity():
    w = np.array([[0.5, -0.5], [0.0, 0.0]])
    has = np.array([True, False])
    out, out_has = HorizonRule(1.0).apply(w, has)
    assert np.shares_memory(out, w) and np.array_equal(out, w) and np.array_equal(out_has, has)
    assert HorizonRule(1.0).reach_rows == 0
    with pytest.raises(ValueError):
        out[0, 0] = 1.0


def test_step_target_closes_the_gap_geometrically():
    w = np.ones((12, 1))
    out, has = HorizonRule(0.5).apply(w, np.ones(12, dtype=bool))
    assert np.allclose(out[:, 0], [1 - 0.5 ** (j + 1) for j in range(12)])
    assert has.all()
    assert HorizonRule(0.5).reach_rows == math.ceil(math.log(1e-3) / math.log(0.5)) == 10


@pytest.mark.parametrize("kappa", [0.0, -0.1, 1.5])
def test_kappa_outside_unit_interval_raises(kappa):
    with pytest.raises(ValueError):
        HorizonRule(kappa)


def test_the_spec_writes_the_identity_only_by_leaving_the_rule_unset():
    """kappa 1.0 in a spec would be a second canonical form (and hash) of the same book."""
    with pytest.raises(ValueError):
        HorizonRuleSpec(kappa=1.0)
    assert HorizonRuleSpec(kappa=0.5).kappa == 0.5


def test_reach_is_the_first_lag_below_the_cutoff_exactly():
    for kappa in (0.5, 0.9, 0.2, 0.999):
        reach = HorizonRule(kappa).reach_rows
        assert (1 - kappa) ** reach < 1e-3 <= (1 - kappa) ** (reach - 1)


def test_a_flat_target_keeps_the_decaying_book_scored():
    """Rows without a target position still hold the decaying book (AGY review): has_position
    stays True while any smoothed weight is nonzero, so timing.py does not mask it away."""
    w = np.array([[1.0, -1.0]] * 3 + [[0.0, 0.0]] * 3)
    has = np.array([True] * 3 + [False] * 3)
    out, out_has = HorizonRule(0.5).apply(w, has)
    assert out_has.all()
    assert np.allclose(out[3:, 0], out[2, 0] * 0.5 ** np.arange(1, 4))


def test_missing_rows_and_exits_are_flat_targets():
    w = np.array([[np.nan, 1.0], [1.0, 1.0], [1.0, np.nan]])
    out, _ = HorizonRule(0.5).apply(w, np.array([True, True, True]))
    assert np.allclose(out[:, 0], [0.0, 0.5, 0.75])  # a NaN target is a flat target
    assert np.allclose(out[:, 1], [0.5, 0.75, 0.375])  # an exit decays


def test_horizon_rule_is_causal():
    rng = np.random.default_rng(0)
    w = rng.normal(size=(50, 4))
    has = np.ones(50, dtype=bool)
    later = w.copy()
    later[30:] = rng.normal(size=(20, 4))
    a, _ = HorizonRule(0.3).apply(w, has)
    b, _ = HorizonRule(0.3).apply(later, has)
    assert np.array_equal(a[:30], b[:30])


def test_a_name_closes_out_exactly_after_its_reach():
    rule = HorizonRule(0.5)
    n = 1 + rule.reach_rows + 3
    w = np.zeros((n, 1))
    w[0] = 1.0
    has = np.zeros(n, dtype=bool)
    has[0] = True
    out, out_has = rule.apply(w, has)
    assert (out[1 : 1 + rule.reach_rows, 0] > 0).all()
    assert (out[1 + rule.reach_rows :, 0] == 0).all() and not out_has[1 + rule.reach_rows :].any()


def test_the_book_holds_on_rows_where_nothing_can_trade():
    w = np.ones((4, 1))
    has = np.ones(4, dtype=bool)
    out, _ = HorizonRule(0.5).apply(w, has, tradable=np.array([True, False, False, True]))
    assert np.allclose(out[:, 0], [0.5, 0.5, 0.5, 0.75])


def test_smoothed_output_is_read_only_too():
    out, has = HorizonRule(0.5).apply(np.ones((3, 2)), np.ones(3, dtype=bool))
    with pytest.raises(ValueError):
        out[0, 0] = 0.0
    with pytest.raises(ValueError):
        has[0] = False
