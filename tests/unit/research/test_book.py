"""S8 under E16: ridge once, R1, timing test; diagnostic shift memory."""

import numpy as np

from src.intelligence.research.book import book_memory_rows, book_timing
from src.intelligence.research.combiner import RidgeSpec, walk_forward_ridge
from src.intelligence.research.portfolio import rank_vol_neutral_weights
from src.intelligence.research.timing import timing_test

BPS = 4
RIDGE = RidgeSpec(window_rows=80 * BPS, refit_rows=10 * BPS, penalty=1.0, embargo=3, min_obs=200)


def test_book_timing_is_ridge_then_r1_then_timing():
    rng = np.random.default_rng(1)
    n, m, k = 300 * BPS, 40, 3
    stack = rng.normal(size=(n, m, k))
    stack[np.arange(n) % 2 == 0] = np.nan
    fwd = rng.normal(0, 0.01, (n, m)) + 0.003 * np.nan_to_num(stack[:, :, 0])
    vol = rng.uniform(0.5, 2.0, (n, m))
    trade = np.ones(n, dtype=bool)
    got = book_timing(
        stack,
        fwd,
        vol,
        trade,
        ridge=RIDGE,
        direction=1.0,
        coverage_floor=20,
        bars_per_session=BPS,
        warmup_sessions=60,
    )
    combined = walk_forward_ridge(stack, fwd, RIDGE)
    w, has = rank_vol_neutral_weights(combined, vol=vol, direction=1.0, coverage_floor=20)
    want = timing_test(w, fwd, has, trade, bars_per_session=BPS, warmup_sessions=60)
    assert got.timing == want
    np.testing.assert_array_equal(got.combined, combined)
    assert got.timing.hac.p < 0.05  # the planted relation is found


def test_book_memory_rows():
    assert book_memory_rows([7124, 7228, 7618, 8138], 2, RIDGE) == 8138 + 80 * BPS + 3 + 3
