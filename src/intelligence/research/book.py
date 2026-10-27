"""S8, the book test (methodology-change-ledger E16, E17).

The book is every registered member of its families, combined once by its S7 combiner (a fixed
pre-registration-signed equal weight by default, or the walk-forward ridge) and constructed with
R1. Its statistic is the E17 timing test (timing.timing_test) on the book's final weights: the
one-sided HAC t of its P&L against returns net of the memory-lagged cell mean, at the vintage
bar, with the book's memory the largest slot history over its members. Neither combiner reads
a target at or after the row it predicts, so the combined alpha's out-of-sample P&L has zero
mean under H0 and no refit per shifted copy is needed; the shift null is kept as a diagnostic
readout computed on the combined alpha.

book_timing is the one path the observed book and every synthetic power replicate go through,
so the power check is a statement about exactly the statistic the test computes.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np

from src.intelligence.research.combiner import Combiner
from src.intelligence.research.construction import ConstructionRule
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.panel import fwd_span
from src.intelligence.research.timing import TimingResult, e17_memory, timing_test


@dataclasses.dataclass(frozen=True)
class BookResult:
    timing: TimingResult
    combined: np.ndarray  # [n, m] walk-forward combined alpha
    weights: np.ndarray  # [n, m] the construction rule's weights of the combined alpha
    has_position: np.ndarray  # [n]


def book_timing(
    stack: np.ndarray,
    fwd: np.ndarray,
    vol: np.ndarray,
    trade: np.ndarray,
    *,
    combiner: Combiner,
    rule: ConstructionRule,
    bars_per_session: int,
    warmup_sessions: int,
    memory_sessions: int,
    horizon_rule: HorizonRule = HorizonRule(),
    tradable: np.ndarray | None = None,
) -> BookResult:
    """Combine, construct, smooth (the horizon rule; the identity by default), then the E17
    test on the smoothed book. `tradable` (the panel's valid rows) is where the rule may
    trade; `memory_sessions` must come from book_memory() with the same rule."""
    combined = combiner.combine(stack, fwd)
    weights, has_position = rule.weights(combined, vol=vol, fwd=fwd, plan=None)
    weights, has_position = horizon_rule.apply(weights, has_position, tradable)
    timing = timing_test(
        weights,
        fwd,
        has_position,
        trade,
        bars_per_session=bars_per_session,
        warmup_sessions=warmup_sessions,
        memory_sessions=memory_sessions,
    )
    return BookResult(timing, combined, weights, has_position)


@dataclasses.dataclass(frozen=True)
class BookMemory:
    """A book's E17 memory (design 4.5): the timing statistic's L in sessions, and the shift
    diagnostic's reach in rows. Each is member memory (with a daily target's reach, see
    timing.e17_memory) + combiner training reach + horizon-rule reach; the two fitted reaches are
    summed in rows and rounded up to sessions once, so L and `rows` agree."""

    member: int  # sessions, the largest slot history over the members, with the target's reach
    combiner_rows: int
    horizon_rows: int
    bars_per_session: int
    rows: int

    @property
    def sessions(self) -> int:
        fitted = self.combiner_rows + self.horizon_rows
        return self.member + math.ceil(fitted / self.bars_per_session)


def book_memory(
    member_sessions: Sequence[int],
    member_rows: Sequence[int],
    horizon: int,
    combiner: Combiner,
    horizon_rule: HorizonRule,
    bars_per_session: int,
) -> BookMemory:
    """The one source of a book's L; no caller computes it by hand."""
    reach = horizon_rule.reach_rows
    return BookMemory(
        member=e17_memory(max(member_sessions), horizon, bars_per_session),
        combiner_rows=combiner.training_rows,
        horizon_rows=reach,
        bars_per_session=bars_per_session,
        rows=book_memory_rows(member_rows, horizon, combiner) + reach,
    )


def book_memory_rows(member_memory_rows: Sequence[int], horizon: int, combiner: Combiner) -> int:
    """Rows the combined alpha at t can read before t, plus the forward span: the members'
    memory and the combiner's training reach (0 for equal weight). Sets the diagnostic shift
    set."""
    return max(member_memory_rows) + combiner.training_rows + fwd_span(horizon)
