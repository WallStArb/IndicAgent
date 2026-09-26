"""Power of the E16 book test (D-12, D-23): exact fixed-R curtailment and planted replicates
scored by exactly the real statistic."""

import math
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from fractions import Fraction

import numpy as np
import pytest

from src.intelligence.research.book import book_timing
from src.intelligence.research.combiner import RidgeSpec
from src.intelligence.research.evaluate import trade_mask
from src.intelligence.research.families.intraday_periodicity import SameSlotPlant, same_slot_mean
from src.intelligence.research.portfolio import trailing_vol
from src.intelligence.research.power import (
    PowerProblem,
    ReplicateOutcome,
    curtail,
    estimate_power,
    run_replicate,
)
from src.intelligence.research.spec import ResearchEvaluationConfig
from src.intelligence.research.synthetic import (
    _member_stack,
    combo_rank_ic,
    synthetic_price_panel,
)


def _out(passed):
    return ReplicateOutcome(passed, 0.0 if passed else 1.0, 0.0)


def test_curtail_equals_fixed_r():
    rng = np.random.default_rng(3)
    for _ in range(300):
        seq = rng.random(100) < rng.uniform(0.2, 0.8)
        consumed = []

        def gen(seq=seq, consumed=consumed):
            for passed in seq:
                consumed.append(passed)
                yield _out(bool(passed))

        decision = curtail(gen(), replicates=100, min_power=0.5)
        assert decision.powered == (seq.sum() >= 50)
        cum_pass = np.cumsum(seq)
        cum_fail = np.cumsum(~seq)
        first = int(np.flatnonzero((cum_pass >= 50) | (cum_fail >= 51))[0]) + 1
        assert len(consumed) == first == decision.decided_after


def test_curtail_needs_exact_ceiling():
    decision = curtail(iter([_out(True)] * 34), replicates=100, min_power=0.335)
    assert decision.powered and decision.passes == math.ceil(Fraction("0.335") * 100)


def test_curtail_raises_when_undecided():
    with pytest.raises(ValueError):
        curtail(iter([_out(True)] * 10), replicates=100, min_power=0.5)


BPS = 4
SYN = SameSlotPlant(
    bars_per_session=BPS, participation_ratio=10.0, n_common_factors=3, plant_lags_sessions=5
)
CFG = ResearchEvaluationConfig(
    trading_start="2000-01-01",
    sub_periods=(("2000-01-01", "2003-12-31"),),
    min_shift=5,
    bootstrap_mean_block=5,
    bootstrap_reps=10,
    seed=1,
    warmup_sessions=60,
    calibration_refit_sessions=10,
    coverage_fraction=0.5,
    ridge_epsilon_fraction=0.1,
)
MEMBERS2 = ((same_slot_mean, {"window_sessions": 1}), (same_slot_mean, {"window_sessions": 5}))
RIDGE = RidgeSpec(window_rows=60 * BPS, refit_rows=10 * BPS, penalty=1.0, embargo=3, min_obs=200)


def _problem(plant, sessions=400, m=30, bar=0.05):
    n = sessions * BPS
    days = np.datetime64("2000-01-03T14:30") + np.repeat(np.arange(sessions), BPS) * np.timedelta64(
        1, "D"
    )
    dates = days + np.tile(np.arange(BPS), sessions) * np.timedelta64(15, "m")
    return PowerProblem(
        plant=SYN,
        plant_coef=plant,
        finite_mask=np.ones((n, m), dtype=bool),
        target_mask=None,
        dates=dates,
        valid=np.ones(n, dtype=bool),
        members=MEMBERS2,
        coverage_floor=20,
        direction=1.0,
        ridge=RIDGE,
        vol_window_rows=20 * BPS,
        vol_min_finite=10 * BPS,
        cfg=CFG,
        memory_sessions=5,  # the members' largest slot history
        bar=bar,
    )


def test_replicate_is_the_real_statistic_on_a_planted_panel():
    problem = _problem(0.3)
    out = run_replicate(problem, 11)
    resid, target = SYN.generate(problem.finite_mask, plant_coef=0.3, seed=11)
    stack = _member_stack(resid, MEMBERS2, BPS, 20)
    vol = trailing_vol(resid, window_rows=20 * BPS, min_finite=10 * BPS)
    trade = trade_mask(problem.dates, CFG) & problem.valid
    want = book_timing(
        stack,
        target,
        vol,
        trade,
        ridge=RIDGE,
        direction=1.0,
        coverage_floor=20,
        bars_per_session=BPS,
        warmup_sessions=60,
        memory_sessions=5,
    )
    assert out.p == want.timing.hac.p and out.passed == (want.timing.hac.p < 0.05)
    assert out == run_replicate(problem, 11)


@pytest.mark.parametrize("plant", [0.0, 0.4])
def test_estimate_power_equals_fixed_r_decision(plant):
    problem = _problem(plant)
    full = [run_replicate(problem, 100 + r).passed for r in range(8)]
    want = sum(full) >= 4
    for workers, factory in ((1, None), (3, lambda w: ThreadPoolExecutor(w))):
        run = estimate_power(
            problem, replicates=8, min_power=0.5, seed=100, workers=workers, pool_factory=factory
        )
        assert run.decision.powered == want
        assert run.decision.passes + run.decision.failures == run.decision.decided_after <= 8


def test_process_pool_leaves_no_workers():
    run = estimate_power(
        _problem(0.0),
        replicates=4,
        min_power=0.5,
        seed=3,
        workers=2,
        pool_factory=lambda w: ProcessPoolExecutor(
            w, mp_context=multiprocessing.get_context("forkserver")
        ),
    )
    assert run.decision.decided_after <= 4
    assert multiprocessing.active_children() == []


def test_no_plant_is_not_powered_at_a_strict_bar_and_a_strong_plant_is():
    assert not estimate_power(
        _problem(0.0, bar=0.001), replicates=4, min_power=0.5, seed=0, workers=1, pool_factory=None
    ).decision.powered
    assert estimate_power(
        _problem(0.6), replicates=4, min_power=0.5, seed=0, workers=1, pool_factory=None
    ).decision.powered


@pytest.mark.slow
def test_s1_passes_the_plant_nearly_unchanged():
    from src.intelligence.research.factors import VINTAGE_1, residual_returns
    from src.intelligence.research.panel import bar_returns

    spec = SameSlotPlant(
        bars_per_session=BPS, participation_ratio=20.0, n_common_factors=5, plant_lags_sessions=5
    )
    panel = synthetic_price_panel(
        spec,
        n_sessions=400,
        n_names=40,
        plant_coef=0.6,
        seed=4,
        start="2010-01-04",
        missing_fraction=0.0,
    )
    direct, target = spec.generate(np.ones(panel.close.shape, dtype=bool), plant_coef=0.6, seed=4)
    via_s1 = residual_returns(bar_returns(panel), bars_per_session=BPS, spec=VINTAGE_1).residual
    rows = np.isfinite(via_s1).any(axis=1)
    members = ((same_slot_mean, {"window_sessions": 1}), (same_slot_mean, {"window_sessions": 5}))
    ic_direct = combo_rank_ic(
        _member_stack(np.where(rows[:, None], direct, np.nan), members, BPS, 20),
        np.where(rows[:, None], target, np.nan),
        coverage_floor=20,
        bars_per_session=BPS,
    )
    ic_s1 = combo_rank_ic(
        _member_stack(via_s1, members, BPS, 20),
        np.where(rows[:, None], target, np.nan),
        coverage_floor=20,
        bars_per_session=BPS,
    )
    assert 0.7 <= ic_s1 / ic_direct <= 1.3, (ic_s1, ic_direct)
