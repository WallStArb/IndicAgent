"""Vendor basis runs (phase 185 plan 33; data layer integrity design section 6).

A basis run is a stretch of consecutive common sessions where the close ratio of two vendors
(IBKR over the other, today Alpaca; see integrity_checks.alpaca_basis_runs) sits outside the
basis tolerance. The Tradier-specific classification of which side was continuous went with the
Tradier code deletion (phase 191 plan 22).

Pure: no database, no APR reads (thresholds are parameters).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

BP = 1e4  # the basis tolerance unit; the single definition (todo 527)


@dataclass(frozen=True)
class BasisRun:
    """Consecutive common sessions [start, end] whose close ratio is out of tolerance."""

    start: date
    end: date
    n_sessions: int
    median_ratio: float


def find_basis_runs(
    pairs: Sequence[tuple[date, float, float]], *, tolerance_bp: float, min_sessions: int
) -> list[BasisRun]:
    """Runs of at least min_sessions out-of-tolerance sessions.

    A pair with a non-positive close on either side measures no basis and is skipped: it neither
    starts, extends nor breaks a run.
    """
    runs: list[BasisRun] = []
    current: list[tuple[date, float]] = []

    def close_run() -> None:
        if len(current) >= min_sessions:
            runs.append(
                BasisRun(
                    start=current[0][0],
                    end=current[-1][0],
                    n_sessions=len(current),
                    median_ratio=statistics.median(r for _, r in current),
                )
            )
        current.clear()

    for session, ibkr_close, other_close in pairs:
        if ibkr_close <= 0 or other_close <= 0:
            continue
        ratio = ibkr_close / other_close
        if abs(ratio - 1.0) * BP > tolerance_bp:
            current.append((session, ratio))
        else:
            close_run()
    close_run()
    return runs
