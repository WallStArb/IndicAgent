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
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Iterable
from fractions import Fraction

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
