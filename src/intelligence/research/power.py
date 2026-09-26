"""Synthetic power of the book test (D-12, D-23; methodology-change-ledger E16 (d), E17).

A replicate is a planted synthetic panel scored by exactly the real test: book.book_timing
(the book's combiner once, R1, the E17 timing test) at the vintage bar. It passes when its
one-sided HAC p is below the bar. curtail consumes replicate outcomes until the fixed-R
decision "passes / R >= min_power" is determined, which is identical to running all R.

estimate_power runs replicates one per pool task and feeds them to curtail in completion order
(the fixed-R decision does not depend on order); once decided, queued replicates are cancelled
and running ones finish. Workers compute and return outcomes, nothing else (D-17).
"""

from __future__ import annotations

import dataclasses
import math
import time
from collections.abc import Callable, Iterable
from concurrent.futures import as_completed
from fractions import Fraction
from typing import Any

import numpy as np


@dataclasses.dataclass(frozen=True)
class ReplicateOutcome:
    passed: bool
    p: float
    t: float


@dataclasses.dataclass(frozen=True)
class PowerDecision:
    powered: bool
    passes: int
    failures: int
    replicates: int
    min_power: float
    decided_after: int


def curtail(
    outcomes: Iterable[ReplicateOutcome], *, replicates: int, min_power: float
) -> PowerDecision:
    """Consume replicate outcomes until the fixed-R decision 'passes / replicates >=
    min_power' is determined."""
    need = math.ceil(Fraction(str(min_power)) * replicates)
    passes = failures = 0
    for outcome in outcomes:
        if outcome.passed:
            passes += 1
        else:
            failures += 1
        if passes >= need or failures > replicates - need:
            return PowerDecision(
                powered=passes >= need,
                passes=passes,
                failures=failures,
                replicates=replicates,
                min_power=min_power,
                decided_after=passes + failures,
            )
    raise ValueError(
        f"power undecided after {passes + failures} of {replicates} replicates "
        f"({passes} passed, need {need})"
    )


@dataclasses.dataclass(frozen=True)
class PowerProblem:
    plant: Any  # synthetic.Plant, from the family's module
    plant_coef: float
    finite_mask: np.ndarray  # the real residual bar returns' availability
    target_mask: np.ndarray | None  # the real residual target's availability
    dates: np.ndarray
    valid: np.ndarray
    members: tuple[tuple[Callable, dict], ...]
    coverage_floor: int
    direction: float
    combiner: Any  # a combiner.Combiner (EqualWeight or RidgeSpec)
    vol_window_rows: int
    vol_min_finite: int
    cfg: Any  # an evaluate.EvaluationConfig (trade span, warmup_sessions)
    memory_sessions: int  # the book's E17 memory: the largest slot history over its members
    bar: float  # alpha / M


def run_replicate(problem: PowerProblem, seed: int) -> ReplicateOutcome:
    """One planted replicate through the real test's statistic (compute-only)."""
    from src.intelligence.research.book import book_timing
    from src.intelligence.research.evaluate import trade_mask
    from src.intelligence.research.portfolio import trailing_vol
    from src.intelligence.research.synthetic import _member_stack

    bps = problem.plant.bars_per_session
    resid, target = problem.plant.generate(
        problem.finite_mask,
        plant_coef=problem.plant_coef,
        seed=seed,
        target_mask=problem.target_mask,
    )
    stack = _member_stack(resid, problem.members, bps, problem.coverage_floor)
    vol = trailing_vol(
        resid, window_rows=problem.vol_window_rows, min_finite=problem.vol_min_finite
    )
    del resid
    result = book_timing(
        stack,
        target,
        vol,
        trade_mask(problem.dates, problem.cfg) & problem.valid,
        combiner=problem.combiner,
        direction=problem.direction,
        coverage_floor=problem.coverage_floor,
        bars_per_session=bps,
        warmup_sessions=problem.cfg.warmup_sessions,
        memory_sessions=problem.memory_sessions,
    )
    hac = result.timing.hac
    return ReplicateOutcome(passed=hac.p < problem.bar, p=hac.p, t=hac.t)


@dataclasses.dataclass(frozen=True)
class PowerRun:
    decision: PowerDecision
    outcomes: tuple[ReplicateOutcome, ...]
    seconds: float


def estimate_power(
    problem: PowerProblem,
    *,
    replicates: int,
    min_power: float,
    seed: int,
    workers: int,
    pool_factory: Callable[[int], Any] | None,
) -> PowerRun:
    """The exact fixed-R power decision (D-23): replicate r uses seed + r."""
    start = time.monotonic()
    outcomes: list[ReplicateOutcome] = []

    def record(outcome: ReplicateOutcome) -> ReplicateOutcome:
        outcomes.append(outcome)
        return outcome

    if workers <= 1:
        decision = curtail(
            (record(run_replicate(problem, seed + r)) for r in range(replicates)),
            replicates=replicates,
            min_power=min_power,
        )
        return PowerRun(decision, tuple(outcomes), time.monotonic() - start)

    if pool_factory is None:
        raise TypeError("workers > 1 needs a pool_factory")
    pool = pool_factory(workers)
    try:
        futures = [pool.submit(run_replicate, problem, seed + r) for r in range(replicates)]
        decision = curtail(
            (record(f.result()) for f in as_completed(futures)),
            replicates=replicates,
            min_power=min_power,
        )
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return PowerRun(decision, tuple(outcomes), time.monotonic() - start)
