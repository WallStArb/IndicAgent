"""S8, the book test (methodology-change-ledger E16).

The book is every registered member of its families, combined once by the S7 walk-forward
ridge and constructed with R1. Its statistic is the E16 timing test (timing.timing_test) on the
book's final weights, the one-sided HAC t of its P&L against returns net of the memory-lagged
cell mean (E17), at the vintage bar. Its memory is the largest slot history over its members. The ridge's walk-forward fit uses only past data, so its out-of-sample P&L
already has zero mean under H0 and no refit per shifted copy is needed; the shift null that
refit served is kept as a diagnostic readout computed on the fitted combined alpha.

book_timing is the one path the observed book and every synthetic power replicate go through,
so the power check is a statement about exactly the statistic the test computes.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import numpy as np

from src.intelligence.research.combiner import RidgeSpec, walk_forward_ridge
from src.intelligence.research.panel import fwd_span
from src.intelligence.research.portfolio import rank_vol_neutral_weights
from src.intelligence.research.timing import TimingResult, timing_test


@dataclasses.dataclass(frozen=True)
class BookResult:
    timing: TimingResult
    combined: np.ndarray  # [n, m] walk-forward combined alpha
    weights: np.ndarray  # [n, m] R1 weights of the combined alpha
    has_position: np.ndarray  # [n]


def book_timing(
    stack: np.ndarray,
    fwd: np.ndarray,
    vol: np.ndarray,
    trade: np.ndarray,
    *,
    ridge: RidgeSpec,
    direction: float,
    coverage_floor: int,
    bars_per_session: int,
    warmup_sessions: int,
    memory_sessions: int,
) -> BookResult:
    combined = walk_forward_ridge(stack, fwd, ridge)
    weights, has_position = rank_vol_neutral_weights(
        combined, vol=vol, direction=direction, coverage_floor=coverage_floor
    )
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


def book_memory_rows(member_memory_rows: Sequence[int], horizon: int, ridge: RidgeSpec) -> int:
    """Rows the fitted combined alpha at t can read before t, plus the forward span: the
    members' memory, the ridge's training window and embargo. Sets the diagnostic shift set."""
    return max(member_memory_rows) + ridge.window_rows + ridge.embargo + fwd_span(horizon)
