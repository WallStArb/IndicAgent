"""One source of a book's E17 memory (design 4.5, plan 187-08)."""

import math

from src.intelligence.research.book import book_memory, book_memory_rows
from src.intelligence.research.combiner import EqualWeight, RidgeSpec
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.timing import e17_memory

EQ = EqualWeight((1.0, -1.0))
RIDGE = RidgeSpec(window_rows=80 * 26, refit_rows=10 * 26, penalty=1.0, embargo=2, min_obs=200)


def test_equal_weight_kappa_one_is_todays_memory():
    for bps, horizon in ((26, 26), (1, 5)):
        mem = book_memory([20, 40], [500, 900], horizon, EQ, HorizonRule(1.0), bps)
        assert mem.sessions == e17_memory(40, horizon, bps)
        assert mem.rows == book_memory_rows([500, 900], horizon, EQ)


def test_ridge_and_kappa_add_their_reach():
    rule = HorizonRule(0.5)
    mem = book_memory([20, 40], [500, 900], 26, RIDGE, rule, 26)
    assert (mem.combiner_rows, mem.horizon_rows) == (RIDGE.training_rows, rule.reach_rows)
    # The fitted reaches are summed in rows and rounded once, consistent with `rows`.
    assert mem.sessions == 40 + math.ceil((RIDGE.training_rows + rule.reach_rows) / 26)
    assert mem.rows == book_memory_rows([500, 900], 26, RIDGE) + rule.reach_rows
