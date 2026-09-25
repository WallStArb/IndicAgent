"""Helpers shared by family members: the centred cross-sectional rank, declared memory in
rows, and the panel adapter the S3 guards use.

Member contract (the runner calls every member this way, spec params as keywords):
`member(resid_bar_returns, *, bars_per_session, coverage_floor, **params) -> alpha [n, m]`,
NaN where there is no position. Members read S1 residual bar returns, never prices: the
runner computes S1 once and hands every member the same array (research pattern 3).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from src.intelligence.research.factors import VINTAGE_1, FactorSpec, residual_returns
from src.intelligence.research.panel import Panel, bar_returns
from src.intelligence.research.portfolio import average_ranks


def centred_rank(alpha: np.ndarray, *, coverage_floor: int) -> np.ndarray:
    """Per row, 0-based average rank over finite values scaled to rank / (n_valid - 1) - 0.5
    (family 1 prereg section 3); a row with fewer than coverage_floor finite values is NaN."""
    out = np.full(alpha.shape, np.nan)
    n_valid = np.isfinite(alpha).sum(axis=1)
    rows = np.flatnonzero(n_valid >= max(coverage_floor, 2))
    if rows.size:
        out[rows] = average_ranks(alpha[rows].astype(float)) / (n_valid[rows, None] - 1) - 0.5
    return out


def declared_memory_rows(
    slot_history_sessions: int, bars_per_session: int, factor_spec: FactorSpec = VINTAGE_1
) -> int:
    """Rows alpha[t] can read before t: the member's slot history plus S1's loading reach
    (its trailing window and one refit block), in whole sessions (prereg section 3)."""
    return (
        slot_history_sessions + factor_spec.window_sessions + factor_spec.refit_sessions
    ) * bars_per_session


def member_on_panel(
    panel: Panel,
    *,
    member: Callable[..., np.ndarray],
    factor_spec: FactorSpec,
    coverage_floor: int,
    params: dict,
) -> np.ndarray:
    """A member computed end to end from prices (S1 inside), for the panel-level S3 guards.
    Module-level, so functools.partial over it pickles."""
    resid = residual_returns(
        bar_returns(panel), bars_per_session=panel.bars_per_session, spec=factor_spec
    ).residual
    return member(
        resid, bars_per_session=panel.bars_per_session, coverage_floor=coverage_floor, **params
    )
