"""Exact decision primitives of the book test's power check (D-12, D-23).

The real book test passes when (1 + b) / (1 + K) < alpha / M, with b the number of the K
admissible shifts whose Sharpe reaches the observed one. A synthetic replicate asks the same
question of a planted panel, and two shortcuts keep the answer identical to evaluating every
shift of every replicate:

- Within a replicate, shifts are visited in a seeded random order and counting stops at the
  first exceedance count above b_max (Besag and Clifford 1991). The count only grows, so a
  replicate stopped there fails exactly as the full count would; a passing replicate still
  visits every shift.
- Across a fixed number R of replicates, consumption stops once the fixed-R outcome is
  determined (enough passes, or too many failures for the rest to matter). The decision equals
  the one R full replicates would give.

Rejected: subsampling shifts per replicate (the sleeve harness's method), which is neither
exact nor consistently conservative; and one null shared across replicates, which is not
provably equivalent. MIN_POWER lives in guards.py; curtail takes it as an argument.

estimate_power runs replicates in parallel, one per worker task, so each early stop frees a
worker; outcomes feed curtail in completion order (the fixed-R decision does not depend on
order), and once decided a shared stop flag makes in-flight replicates abort. Replicates are
scored exactly as the real S8 test (same construction, session scoring and shift set); only
the panel differs. Workers compute and return outcomes, nothing else (D-17).
"""

from __future__ import annotations

import dataclasses
import functools
import math
import multiprocessing
import time
from collections.abc import Callable, Iterable
from concurrent.futures import as_completed
from fractions import Fraction
from typing import Any

import numpy as np


def b_max(n_shifts: int, alpha_level: float, budget_m: int) -> int:
    """Largest exceedance count b >= -1 with (1 + b) / (1 + n_shifts) < alpha_level / budget_m;
    -1 when no count passes (fewer than M / alpha shifts)."""
    bar = Fraction(str(alpha_level)) / budget_m
    bound = bar * (1 + n_shifts)  # need 1 + b < bound
    return math.ceil(bound) - 2


@dataclasses.dataclass(frozen=True)
class ReplicateOutcome:
    passed: bool
    exceedances: int
    visited: int
    aborted: bool = False


def replicate_passes(
    s_obs: float,
    shifts: np.ndarray,
    shifted_sharpe: Callable[[int], float],
    bmax: int,
    rng: np.random.Generator,
    stop: Callable[[], bool] | None = None,
    stop_check_every: int = 1,
) -> ReplicateOutcome:
    """One replicate's screen outcome over the full shift set, stopped as soon as it fails."""
    if bmax < 0:
        return ReplicateOutcome(False, 0, 0)
    exceed = 0
    for visited, shift in enumerate(rng.permutation(shifts), start=1):
        if stop is not None and (visited - 1) % stop_check_every == 0 and stop():
            return ReplicateOutcome(False, exceed, visited - 1, aborted=True)
        if shifted_sharpe(int(shift)) >= s_obs:
            exceed += 1
            if exceed > bmax:
                return ReplicateOutcome(False, exceed, visited)
    return ReplicateOutcome(True, exceed, len(shifts))


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
    """Consume replicate outcomes (aborted ones ignored) until the fixed-R decision
    'passes / replicates >= min_power' is determined."""
    need = math.ceil(Fraction(str(min_power)) * replicates)
    passes = failures = 0
    for outcome in outcomes:
        if outcome.aborted:
            continue
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
    synth: Any  # synthetic.SyntheticSpec
    plant_coef: float
    finite_mask: np.ndarray
    dates: np.ndarray
    valid: np.ndarray
    members: tuple[tuple[Callable, dict], ...]
    coverage_floor: int
    direction: float
    ridge: Any  # combiner.RidgeSpec
    vol_window_rows: int
    vol_min_finite: int
    cfg: Any  # an evaluate.EvaluationConfig
    shifts: np.ndarray
    bmax: int
    # The real residual target's finite pattern (availability only, no return values).
    target_mask: np.ndarray | None = None


def run_replicate(
    problem: PowerProblem, seed: int, stop: Any | None = None, stop_check_every: int = 1
) -> ReplicateOutcome:
    """One synthetic replicate of the book test (compute-only). `stop` is an Event-like object
    or None."""
    # Imported here: power's decision primitives stay importable without the book stack.
    from src.intelligence.research.book import book_returns, book_sharpe, flatten_stack
    from src.intelligence.research.evaluate import trade_mask
    from src.intelligence.research.portfolio import trailing_vol
    from src.intelligence.research.synthetic import _member_stack, generate_residual_panel

    bps = problem.synth.bars_per_session
    resid, target = generate_residual_panel(
        problem.synth,
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
    construction = functools.partial(
        book_returns,
        n_members=stack.shape[2],
        ridge=problem.ridge,
        vol=vol,
        direction=problem.direction,
        coverage_floor=problem.coverage_floor,
    )
    trade = trade_mask(problem.dates, problem.cfg) & problem.valid
    flat = flatten_stack(stack)
    score = functools.partial(book_sharpe, flat, target, construction, trade, bars_per_session=bps)
    s_obs = score()
    return replicate_passes(
        s_obs,
        problem.shifts,
        lambda k: score(shift=k),
        problem.bmax,
        np.random.default_rng(seed),
        stop=None if stop is None else stop.is_set,
        stop_check_every=stop_check_every,
    )


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
    stop_check_every: int,
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
    manager = multiprocessing.Manager()
    stop = manager.Event()
    pool = pool_factory(workers)
    futures = []
    try:
        futures = [
            pool.submit(run_replicate, problem, seed + r, stop, stop_check_every)
            for r in range(replicates)
        ]
        decision = curtail(
            (record(f.result()) for f in as_completed(futures)),
            replicates=replicates,
            min_power=min_power,
        )
    finally:
        stop.set()
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True)
        manager.shutdown()
    return PowerRun(decision, tuple(outcomes), time.monotonic() - start)
