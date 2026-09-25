"""S8 book test (D-11): joint whole-session shift of the member stack, combiner refit per
shift, R1 construction, session scoring, through the unchanged evaluate()."""

import functools
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import numpy as np
import pytest
from scipy.stats import binom

from src.intelligence.research import book as book_mod
from src.intelligence.research.book import (
    BOOK_ARM,
    book_construction,
    book_memory_rows,
    book_returns,
    book_sharpe,
    evaluate_book,
    flatten_stack,
)
from src.intelligence.research.combiner import RidgeSpec, walk_forward_ridge
from src.intelligence.research.evaluate import session_shifts, trade_mask
from src.intelligence.research.guards import GuardFailure, require_testable
from src.intelligence.research.portfolio import rank_vol_neutral_returns
from src.intelligence.research.spec import ResearchEvaluationConfig
from src.intelligence.statistics.panel_null import shift_panel

BPS = 4
RIDGE = RidgeSpec(window_rows=80 * BPS, refit_rows=10 * BPS, penalty=1.0, embargo=3, min_obs=200)
CFG = ResearchEvaluationConfig(
    trading_start="2000-01-01",
    sub_periods=(("2000-01-01", "2002-12-31"),),
    min_shift=20,
    bootstrap_mean_block=5,
    bootstrap_reps=50,
    seed=1,
    warmup_sessions=20,
    calibration_refit_sessions=10,
    coverage_fraction=0.5,
    ridge_epsilon_fraction=1e-4,
)
KW = {"mv_condition_max": 1e6, "ic_shrinkage_k": 100.0}
MEMORY = 5 * BPS


def _panel(seed, sessions=400, m=40, k=3, plant=0.0):
    rng = np.random.default_rng(seed)
    n = sessions * BPS
    stack = rng.normal(size=(n, m, k))
    stack[np.arange(n) % 2 == 0] = np.nan  # members sit on placement rows only
    target = rng.normal(0, 0.01, (n, m))
    if plant:
        target = target + plant * 0.01 * np.nan_to_num(stack[:, :, 0])
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, (n, m)), axis=0))
    vol = rng.uniform(0.5, 2.0, (n, m))
    days = np.datetime64("2000-01-03T14:30") + np.repeat(np.arange(sessions), BPS) * np.timedelta64(
        1, "D"
    )
    dates = days + np.tile(np.arange(BPS), sessions) * np.timedelta64(15, "m")
    return stack, target, closes, vol, dates


def _run(stack, target, closes, vol, dates, **extra):
    extra.setdefault("workers", 1)
    extra.setdefault("pool_factory", None)
    return evaluate_book(
        stack,
        target,
        closes,
        dates,
        None,
        CFG,
        ridge=RIDGE,
        vol=vol,
        direction=1.0,
        coverage_floor=20,
        memory=MEMORY,
        bars_per_session=BPS,
        **KW,
        **extra,
    )


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_flatten_roll_is_joint_roll(dtype):
    stack = np.random.default_rng(0).normal(size=(12, 5, 3)).astype(dtype)
    for k in (1, 4, 8):
        rolled = shift_panel(flatten_stack(stack), k).reshape(stack.shape)
        np.testing.assert_array_equal(rolled, np.roll(stack, k, axis=0))


def test_book_returns_is_ridge_then_r1():
    stack, target, _, vol, _ = _panel(1, sessions=150)
    got = book_returns(
        flatten_stack(stack),
        target,
        None,
        n_members=3,
        ridge=RIDGE,
        vol=vol,
        direction=1.0,
        coverage_floor=20,
    )[BOOK_ARM]
    combined = walk_forward_ridge(stack, target, RIDGE)
    want = next(
        iter(
            rank_vol_neutral_returns(
                combined, target, None, vol=vol, direction=1.0, coverage_floor=20
            ).values()
        )
    )
    np.testing.assert_array_equal(got, want)


def test_null_refits_per_shift(monkeypatch):
    stack, target, closes, vol, dates = _panel(2, sessions=200, plant=0.3)
    calls = []
    real = book_mod.combiner.walk_forward_ridge

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(book_mod.combiner, "walk_forward_ridge", counting)
    shifts = np.array([40, 80, 120]) * BPS
    res = _run(stack, target, closes, vol, dates, shifts=shifts)
    assert len(calls) == 1 + len(shifts)

    monkeypatch.setattr(book_mod.combiner, "walk_forward_ridge", real)
    construction = book_construction(
        n_members=3, ridge=RIDGE, vol=vol, direction=1.0, coverage_floor=20
    )
    trade = trade_mask(dates, CFG)
    flat = flatten_stack(stack)
    for k, shift in enumerate(shifts):
        want = book_sharpe(
            flat, target, construction, trade, bars_per_session=BPS, shift=int(shift)
        )
        assert res.sharpe_null[k, 0] == pytest.approx(want, rel=1e-12)

    # Shifting the fitted combined alpha instead of refitting gives a different null.
    combined = walk_forward_ridge(stack, target, RIDGE)
    post_fit = []
    for shift in shifts:
        r = next(
            iter(
                rank_vol_neutral_returns(
                    shift_panel(combined, int(shift)),
                    target,
                    None,
                    vol=vol,
                    direction=1.0,
                    coverage_floor=20,
                ).values()
            )
        )
        post_fit.append(
            book_mod.scored_sharpe(
                r, trade, periods_per_year=252 * BPS, bars_per_session=BPS, session_scoring=True
            )
        )
    assert not np.allclose(post_fit, res.sharpe_null[:, 0])


def test_shifts_are_whole_sessions():
    stack, target, closes, vol, dates = _panel(3, sessions=160)
    res = _run(stack, target, closes, vol, dates)
    assert (res.shifts % BPS == 0).all()
    np.testing.assert_array_equal(
        res.shifts, session_shifts(len(dates), BPS, CFG.min_shift, MEMORY)
    )


def test_book_memory_rows():
    assert book_memory_rows([7124, 7228, 7618, 8138], 2) == 8141


def test_small_panel_is_refused_on_shift_count():
    n_shifts = len(session_shifts(160 * BPS, BPS, CFG.min_shift, MEMORY))
    assert n_shifts < 600
    with pytest.raises(GuardFailure, match="cannot resolve"):
        require_testable(n_shifts=n_shifts, alpha_level=0.05, budget_m=30, power=1.0)


def test_book_complete_cases_only():
    stack, target, _, vol, _ = _panel(4, sessions=150)
    stack[-50:, 0, 1] = np.nan
    combined = walk_forward_ridge(stack, target, RIDGE)
    assert np.isnan(combined[-50:, 0]).all()


def test_worker_pool_equals_serial():
    stack, target, closes, vol, dates = _panel(5, sessions=160)
    shifts = np.array([30, 60, 90, 120]) * BPS
    serial = _run(stack, target, closes, vol, dates, shifts=shifts)
    pooled = _run(
        stack,
        target,
        closes,
        vol,
        dates,
        shifts=shifts,
        workers=2,
        pool_factory=lambda w: ThreadPoolExecutor(w),
    )
    np.testing.assert_array_equal(serial.sharpe_null, pooled.sharpe_null)


def test_planted_book_is_detected_and_unplanted_is_not():
    planted = _run(*_panel(6, sessions=300, plant=0.5))
    unplanted = _run(*_panel(6, sessions=300))
    assert planted.adjusted_p[0] < 0.05
    assert unplanted.adjusted_p[0] > 0.05


def _exact_size(k):
    """Rejection probability of p = (1 + b) / (1 + K) < 0.05 under exchangeability."""
    bound = Fraction(1, 20) * (1 + k)
    return Fraction(max(0, -(-bound.numerator // bound.denominator) - 1), 1 + k)


@pytest.mark.slow
def test_book_null_is_calibrated():
    small = functools.partial(_panel, sessions=150, m=30)
    rejections = 0
    k_seen = None
    for seed in range(100):
        res = _run(*small(seed))
        k_seen = len(res.shifts)
        rejections += int(res.adjusted_p[0] < 0.05)
    size = float(_exact_size(k_seen))
    lo, hi = binom.ppf(0.005, 100, size), binom.ppf(0.995, 100, size)
    assert lo <= rejections <= hi, (rejections, lo, hi, k_seen)
