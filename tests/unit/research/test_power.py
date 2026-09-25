"""Exact power-decision primitives (D-12, D-23): b_max, early-stopped replicates, curtailment."""

import math
from fractions import Fraction

import numpy as np
import pytest

from src.intelligence.research.power import (
    ReplicateOutcome,
    b_max,
    curtail,
    replicate_passes,
)


def _brute(k, alpha, m):
    bar = Fraction(str(alpha)) / m
    best = -1
    for b in range(0, k + 1):
        if Fraction(1 + b, 1 + k) < bar:
            best = b
    return best


def test_b_max_known_values():
    assert b_max(4461, 0.05, 30) == 6
    assert b_max(599, 0.05, 30) == -1
    assert b_max(600, 0.05, 30) == 0


def test_b_max_matches_brute_force():
    for k in range(1, 6001, 7):
        assert b_max(k, 0.05, 30) == _brute(k, 0.05, 30), k
    for k in (599, 1199, 1799, 2399):
        assert b_max(k, 0.05, 30) == _brute(k, 0.05, 30)
        assert (Fraction(1, 600) * (1 + k)).denominator == 1


class _Counter:
    def __init__(self, null):
        self.null = null
        self.calls = []

    def __call__(self, k):
        self.calls.append(k)
        return float(self.null[k])


def test_early_stop_equals_full_count():
    rng = np.random.default_rng(0)
    for _ in range(500):
        k = int(rng.integers(50, 2001))
        null = rng.normal(size=k)
        s_obs = float(rng.normal(1.0, 1.0))
        bmax = int(rng.integers(-1, 20))
        counter = _Counter(null)
        out = replicate_passes(s_obs, np.arange(k), counter, bmax, np.random.default_rng(1))
        full = int((null >= s_obs).sum())
        assert out.passed == (full <= bmax)
        assert not out.aborted
        seen = int((null[counter.calls] >= s_obs).sum())
        if not out.passed:
            assert seen == bmax + 1
            if counter.calls:
                assert null[counter.calls[-1]] >= s_obs  # stopped on the deciding exceedance
        else:
            assert len(counter.calls) == k


def test_visit_order_is_seeded_permutation():
    null = np.linspace(-1, 1, 300)
    shifts = np.arange(300) * 26
    lookup = {int(s): v for s, v in zip(shifts, null)}
    a, b = [], []
    replicate_passes(0.5, shifts, lambda s: a.append(s) or lookup[s], 3, np.random.default_rng(9))
    replicate_passes(0.5, shifts, lambda s: b.append(s) or lookup[s], 3, np.random.default_rng(9))
    assert a == b
    assert a == list(np.random.default_rng(9).permutation(shifts)[: len(a)])


def test_stop_aborts_and_curtail_ignores_aborted():
    out = replicate_passes(
        0.0,
        np.arange(100),
        lambda k: -1.0,
        5,
        np.random.default_rng(0),
        stop=lambda: True,
        stop_check_every=10,
    )
    assert out.aborted and not out.passed
    outcomes = [ReplicateOutcome(False, 0, 3, aborted=True)] + [ReplicateOutcome(True, 0, 1)] * 2
    decision = curtail(iter(outcomes), replicates=2, min_power=0.5)
    assert decision.powered and decision.passes == 1


def test_curtail_equals_fixed_r():
    rng = np.random.default_rng(3)
    for _ in range(300):
        seq = rng.random(100) < rng.uniform(0.2, 0.8)
        consumed = []

        def gen(seq=seq, consumed=consumed):
            for passed in seq:
                consumed.append(passed)
                yield ReplicateOutcome(bool(passed), 0, 1)

        decision = curtail(gen(), replicates=100, min_power=0.5)
        assert decision.powered == (seq.sum() >= 50)
        cum_pass = np.cumsum(seq)
        cum_fail = np.cumsum(~seq)
        first = int(np.flatnonzero((cum_pass >= 50) | (cum_fail >= 51))[0]) + 1
        assert len(consumed) == first == decision.decided_after


def test_curtail_needs_exact_ceiling():
    decision = curtail(iter([ReplicateOutcome(True, 0, 1)] * 34), replicates=100, min_power=0.335)
    assert decision.powered and decision.passes == math.ceil(Fraction("0.335") * 100)


def test_curtail_raises_when_undecided():
    with pytest.raises(ValueError):
        curtail(iter([ReplicateOutcome(True, 0, 1)] * 10), replicates=100, min_power=0.5)


# --- estimator (plan 08) ---------------------------------------------------------------------

import functools as _functools  # noqa: E402
import multiprocessing  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor  # noqa: E402

from src.intelligence.research.book import book_returns, book_sharpe, flatten_stack  # noqa: E402
from src.intelligence.research.combiner import RidgeSpec  # noqa: E402
from src.intelligence.research.evaluate import session_shifts, trade_mask  # noqa: E402
from src.intelligence.research.families.intraday_periodicity import same_slot_mean  # noqa: E402
from src.intelligence.research.portfolio import trailing_vol  # noqa: E402
from src.intelligence.research.power import (
    PowerProblem,
    estimate_power,
    run_replicate,
)  # noqa: E402
from src.intelligence.research.spec import ResearchEvaluationConfig  # noqa: E402
from src.intelligence.research.synthetic import (  # noqa: E402
    SyntheticSpec,
    _member_stack,
    combo_rank_ic,
    generate_residual_panel,
    synthetic_price_panel,
)

BPS = 4
SYN = SyntheticSpec(
    bars_per_session=BPS, participation_ratio=10.0, n_common_factors=3, plant_lags_sessions=5
)
CFG = ResearchEvaluationConfig(
    trading_start="2000-01-01",
    sub_periods=(("2000-01-01", "2003-12-31"),),
    min_shift=5,
    bootstrap_mean_block=5,
    bootstrap_reps=10,
    seed=1,
    warmup_sessions=20,
    calibration_refit_sessions=10,
    coverage_fraction=0.5,
    ridge_epsilon_fraction=0.1,
)
MEMBERS2 = ((same_slot_mean, {"window_sessions": 1}), (same_slot_mean, {"window_sessions": 5}))


def _problem(plant, sessions=300, m=30, budget_m=1):
    n = sessions * BPS
    days = np.datetime64("2000-01-03T14:30") + np.repeat(np.arange(sessions), BPS) * np.timedelta64(
        1, "D"
    )
    dates = days + np.tile(np.arange(BPS), sessions) * np.timedelta64(15, "m")
    shifts = session_shifts(n, BPS, 5, 20 * BPS)[:100]
    return PowerProblem(
        synth=SYN,
        plant_coef=plant,
        finite_mask=np.ones((n, m), dtype=bool),
        dates=dates,
        valid=np.ones(n, dtype=bool),
        members=MEMBERS2,
        coverage_floor=20,
        direction=1.0,
        ridge=RidgeSpec(
            window_rows=60 * BPS, refit_rows=10 * BPS, penalty=1.0, embargo=3, min_obs=200
        ),
        vol_window_rows=20 * BPS,
        vol_min_finite=10 * BPS,
        cfg=CFG,
        shifts=shifts,
        bmax=b_max(len(shifts), 0.05, budget_m),
    )


def _full_count_passes(problem, seed):
    resid, target = generate_residual_panel(
        problem.synth, problem.finite_mask, plant_coef=problem.plant_coef, seed=seed
    )
    stack = _member_stack(resid, problem.members, BPS, problem.coverage_floor)
    vol = trailing_vol(
        resid, window_rows=problem.vol_window_rows, min_finite=problem.vol_min_finite
    )
    construction = _functools.partial(
        book_returns,
        n_members=stack.shape[2],
        ridge=problem.ridge,
        vol=vol,
        direction=1.0,
        coverage_floor=20,
    )
    trade = trade_mask(problem.dates, problem.cfg) & problem.valid
    flat = flatten_stack(stack)
    s_obs = book_sharpe(flat, target, construction, trade, bars_per_session=BPS)
    count = sum(
        book_sharpe(flat, target, construction, trade, bars_per_session=BPS, shift=int(k)) >= s_obs
        for k in problem.shifts
    )
    return count <= problem.bmax


def test_run_replicate_is_deterministic_and_pool_safe():
    problem = _problem(0.3)
    a = run_replicate(problem, 11)
    assert a == run_replicate(problem, 11)
    with ThreadPoolExecutor(1) as pool:
        assert pool.submit(run_replicate, problem, 11).result() == a


@pytest.mark.parametrize("plant", [0.0, 0.3, 0.8])
def test_estimate_power_equals_full_count_decision(plant):
    problem = _problem(plant)
    full = [_full_count_passes(problem, 100 + r) for r in range(12)]
    want = sum(full) >= 6
    for workers, factory in ((1, None), (3, lambda w: ThreadPoolExecutor(w))):
        run = estimate_power(
            problem,
            replicates=12,
            min_power=0.5,
            seed=100,
            workers=workers,
            pool_factory=factory,
            stop_check_every=1,
        )
        assert run.decision.powered == want
        assert run.decision.decided_after <= 12
        counted = [o for o in run.outcomes if not o.aborted]
        assert (
            run.decision.passes + run.decision.failures
            == run.decision.decided_after
            <= len(counted)
        )


def test_process_pool_stops_cleanly_without_orphans():
    problem = _problem(0.0)
    run = estimate_power(
        problem,
        replicates=6,
        min_power=0.5,
        seed=3,
        workers=2,
        pool_factory=lambda w: ProcessPoolExecutor(
            w, mp_context=multiprocessing.get_context("forkserver")
        ),
        stop_check_every=1,
    )
    assert not run.decision.powered
    assert multiprocessing.active_children() == []


def test_no_plant_not_powered_strong_plant_powered():
    strict = _problem(0.0, budget_m=2)
    assert not estimate_power(
        strict,
        replicates=4,
        min_power=0.5,
        seed=0,
        workers=1,
        pool_factory=None,
        stop_check_every=1,
    ).decision.powered
    strong = _problem(0.9)
    assert estimate_power(
        strong,
        replicates=4,
        min_power=0.5,
        seed=0,
        workers=1,
        pool_factory=None,
        stop_check_every=1,
    ).decision.powered


@pytest.mark.slow
def test_s1_passes_the_plant_nearly_unchanged():
    from src.intelligence.research.factors import VINTAGE_1, residual_returns
    from src.intelligence.research.panel import bar_returns

    spec = SyntheticSpec(
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
    direct, target = generate_residual_panel(
        spec, np.ones(panel.close.shape, dtype=bool), plant_coef=0.6, seed=4
    )
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
