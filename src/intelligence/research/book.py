"""S8: the book test, as a construction handed to the unchanged evaluate() (D-11).

The book is every registered member of the admitted families, combined by the S7 walk-forward
ridge and constructed with R1, scored per session (R2). Its null shifts the stacked member
panel jointly by whole sessions and reruns S7 on each shifted stack (the owner's decision:
the null refits the combiner), so the fit's own capacity is inside the null. Shifting the
combined alpha after one fit would leave it out.

- One statistics path: evaluate() rolls a 2-D alpha with the shared shift_panel primitive and
  calls the construction once per shift with the unshifted target. The stack [n, m, K] travels
  flattened to [n, m*K]: a row roll of the C-order flattened array is exactly the joint roll
  of the stack, and the construction unflattens it (a view) before refitting.
- Shift memory is the largest member memory plus the forward span (book_memory_rows): the
  ridge's training window lies behind each prediction row and adds no read-ahead of its own.
- R1 sizes by the names' own trailing volatility, a property of the names, not of the signal,
  so `vol` is never shifted.
- The 600-shift and 50% power refusals and the budget charge belong to the runner (book
  mode), not here. Compute-only numpy (D-17); a worker pool comes in through pool_factory.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence

import numpy as np

from src.intelligence.research import combiner
from src.intelligence.research.combiner import RidgeSpec
from src.intelligence.research.evaluate import (
    SESSIONS_PER_YEAR,
    EvaluationConfig,
    EvaluationResult,
    PoolFactory,
    evaluate,
    scored_sharpe,
)
from src.intelligence.research.panel import fwd_span
from src.intelligence.research.portfolio import (
    CovariancePlan,
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
)
from src.intelligence.statistics.panel_null import shift_panel

BOOK_ARM = "book"


def flatten_stack(stack: np.ndarray) -> np.ndarray:
    """[n, m, K] -> [n, m*K], C order (a view when the stack is contiguous)."""
    n, m, k = stack.shape
    return stack.reshape(n, m * k)


def _combined(
    alpha_flat: np.ndarray, fwd_ret: np.ndarray, n_members: int, ridge: RidgeSpec
) -> np.ndarray:
    n, width = alpha_flat.shape
    stack = alpha_flat.reshape(n, width // n_members, n_members)
    return combiner.walk_forward_ridge(stack, fwd_ret, ridge)


def book_returns(
    alpha_flat: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan | None,
    *,
    n_members: int,
    ridge: RidgeSpec,
    vol: np.ndarray,
    direction: float,
    coverage_floor: int,
) -> dict[str, np.ndarray]:
    """The book's per-row return: refit S7 on this (possibly shifted) stack, then R1.
    `plan` is ignored; the argument keeps evaluate()'s construction signature."""
    combined = _combined(alpha_flat, fwd_ret, n_members, ridge)
    r = rank_vol_neutral_returns(
        combined, fwd_ret, None, vol=vol, direction=direction, coverage_floor=coverage_floor
    )
    return {BOOK_ARM: next(iter(r.values()))}


def book_weights(
    alpha_flat: np.ndarray,
    fwd_ret: np.ndarray,
    *,
    n_members: int,
    ridge: RidgeSpec,
    vol: np.ndarray,
    direction: float,
    coverage_floor: int,
) -> tuple[np.ndarray, np.ndarray]:
    """The observed book's R1 weights and has_position, for turnover diagnostics."""
    combined = _combined(alpha_flat, fwd_ret, n_members, ridge)
    return rank_vol_neutral_weights(
        combined, vol=vol, direction=direction, coverage_floor=coverage_floor
    )


def book_memory_rows(member_memory_rows: Sequence[int], horizon: int) -> int:
    return max(member_memory_rows) + fwd_span(horizon)


def book_sharpe(
    alpha_flat: np.ndarray,
    fwd_ret: np.ndarray,
    construction,
    trade: np.ndarray,
    *,
    bars_per_session: int,
    shift: int = 0,
) -> float:
    """The book's session-scored Sharpe at one shift: the statistic evaluate() computes per
    shift, exposed so the power check scores replicates through the same path. shift 0 is the
    observed book."""
    alpha = shift_panel(alpha_flat, shift) if shift else alpha_flat
    out = construction(alpha, fwd_ret, None)[BOOK_ARM]
    return scored_sharpe(
        out,
        trade,
        periods_per_year=SESSIONS_PER_YEAR * bars_per_session,
        bars_per_session=bars_per_session,
        session_scoring=True,
    )


def book_construction(
    *, n_members: int, ridge: RidgeSpec, vol: np.ndarray, direction: float, coverage_floor: int
):
    """The picklable construction evaluate() calls per shift."""
    return functools.partial(
        book_returns,
        n_members=n_members,
        ridge=ridge,
        vol=vol,
        direction=direction,
        coverage_floor=coverage_floor,
    )


def evaluate_book(
    stack: np.ndarray,
    fwd_resid: np.ndarray,
    closes: np.ndarray,
    dates: np.ndarray,
    valid: np.ndarray | None,
    cfg: EvaluationConfig,
    *,
    ridge: RidgeSpec,
    vol: np.ndarray,
    direction: float,
    coverage_floor: int,
    memory: int,
    bars_per_session: int,
    workers: int,
    pool_factory: PoolFactory | None,
    mv_condition_max: float,
    ic_shrinkage_k: float,
    shifts: np.ndarray | None = None,
) -> EvaluationResult:
    construction = book_construction(
        n_members=stack.shape[2],
        ridge=ridge,
        vol=vol,
        direction=direction,
        coverage_floor=coverage_floor,
    )
    return evaluate(
        flatten_stack(stack),
        fwd_resid,
        closes,
        dates,
        cfg,
        construction=construction,
        memory=memory,
        embargo=ridge.embargo,
        bars_per_session=bars_per_session,
        valid=valid,
        session_scoring=True,
        workers=workers,
        pool_factory=pool_factory,
        mv_condition_max=mv_condition_max,
        ic_shrinkage_k=ic_shrinkage_k,
        shifts=shifts,
    )
