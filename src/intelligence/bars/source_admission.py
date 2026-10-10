"""Tradier admission on evidence (phase 185 plan 38 Task 0).

Tradier is a name's primary 1d source only when its closes agree with IBKR SMART TRADES over the
common sessions: at least min_overlap common sessions, at least min_agree_share of them with an
IBKR/Tradier close ratio within tolerance_bp of 1. No common session is no evidence and fails.

The recent-window variant re-tests the most recent min_overlap common sessions alone. A
Tradier-incumbent name that fails over its whole history but agrees now has a past basis run
(RJF-like, where IBKR is the wrong side); that is 185-37's basis question, not an exception row.

Pure: no database, no APR reads (thresholds are parameters), deterministic under input order.
The closes come from daily_rule.current_closes, the same current-scale choice d2-v2 makes.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.intelligence.bars.daily_rule import current_closes
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.vendor_basis import BP


@dataclass(frozen=True)
class Admission:
    """The evidence for one name: whole history and the recent window."""

    admitted: bool
    admitted_recent: bool
    n_common: int
    agree_share: float | None
    median_ratio: float | None
    recent_agree_share: float | None
    recent_window: tuple[date, date] | None
    # Evidence that Tradier disagrees with IBKR now: a full recent window below the share.
    # Too few common sessions is no evidence either way (admitted_recent is then also False).
    recent_disagrees: bool = False


def common_session_closes(
    observations: Sequence[Observation], splits: Sequence[SplitRecord]
) -> list[tuple[date, float, float]]:
    """(date, Tradier close, IBKR SMART close) per common session, sorted by date.

    A non-positive Tradier close is a provider defect and measures no basis.
    """
    tradier, ibkr = current_closes(observations, splits)
    return [(d, tradier[d], ibkr[d]) for d in sorted(set(tradier) & set(ibkr)) if tradier[d] > 0]


def _share(pairs: Sequence[tuple[date, float, float]], tolerance_bp: float) -> float | None:
    if not pairs:
        return None
    agree = sum(1 for _d, t, i in pairs if abs(i / t - 1.0) * BP <= tolerance_bp + 1e-9)
    return agree / len(pairs)


def tradier_admission(
    pairs: Sequence[tuple[date, float, float]],
    *,
    min_overlap: int,
    min_agree_share: float,
    tolerance_bp: float,
) -> Admission:
    """Admit Tradier on the common-session closes (module docstring)."""
    if min_overlap < 1:
        raise ValueError("min_overlap must be at least 1")
    ordered = sorted(pairs)
    share = _share(ordered, tolerance_bp)
    recent = ordered[-min_overlap:]
    recent_share = _share(recent, tolerance_bp)
    enough = len(ordered) >= min_overlap
    return Admission(
        admitted=enough and share is not None and share >= min_agree_share,
        admitted_recent=enough and recent_share is not None and recent_share >= min_agree_share,
        n_common=len(ordered),
        agree_share=share,
        median_ratio=statistics.median(i / t for _d, t, i in ordered) if ordered else None,
        recent_agree_share=recent_share,
        recent_window=(recent[0][0], recent[-1][0]) if recent else None,
        recent_disagrees=enough and recent_share is not None and recent_share < min_agree_share,
    )
