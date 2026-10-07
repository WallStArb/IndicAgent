"""Vendor basis runs (phase 185 plan 33; data layer integrity design section 6).

A basis run is a stretch of consecutive common sessions where the IBKR/Tradier close ratio sits
outside the basis tolerance. When the two vendors disagree for a run, one of them is continuous
across the run's boundaries (its own series moves as an ordinary day) and the other steps; the
canonical series is wrong only when it is built from the stepping vendor. classify_run decides
which vendor is continuous from the run's boundary sessions alone, relative to each vendor's own
move history, so no extra threshold exists beyond the basis tolerance.

Pure: no database, no APR reads (thresholds are parameters).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from src.intelligence.bars.derivation import SplitRecord
from src.intelligence.bars.sources import CANONICAL_1D_SOURCES

VENDOR_IBKR = "ibkr"
VENDOR_TRADIER = "tradier"

_BP = 1e4


@dataclass(frozen=True)
class BasisRun:
    """Consecutive common sessions [start, end] whose IBKR/Tradier ratio is out of tolerance."""

    start: date
    end: date
    n_sessions: int
    median_ratio: float
    continuous_vendor: str | None


def ratio_pairs(
    ibkr: Mapping[date, float], tradier: Mapping[date, float]
) -> list[tuple[date, float, float]]:
    """(session, ibkr_close, tradier_close) on the dates both vendors answered, in order."""
    return [(d, ibkr[d], tradier[d]) for d in sorted(ibkr.keys() & tradier.keys())]


def find_basis_runs(
    pairs: Sequence[tuple[date, float, float]], *, tolerance_bp: float, min_sessions: int
) -> list[BasisRun]:
    """Runs of at least min_sessions out-of-tolerance sessions, unclassified.

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
                    continuous_vendor=None,
                )
            )
        current.clear()

    for session, ibkr_close, tradier_close in pairs:
        if ibkr_close <= 0 or tradier_close <= 0:
            continue
        ratio = ibkr_close / tradier_close
        if abs(ratio - 1.0) * _BP > tolerance_bp:
            current.append((session, ratio))
        else:
            close_run()
    close_run()
    return runs


def _log_moves(closes: Mapping[date, float], sessions: Sequence[date]) -> dict[date, float]:
    """|ln(close[t] / close[t-1])| keyed by t, over consecutive entries of sessions."""
    return {
        cur: abs(math.log(closes[cur] / closes[prev]))
        for prev, cur in zip(sessions, sessions[1:], strict=False)
    }


def classify_run(
    run: BasisRun,
    ibkr_closes: Mapping[date, float],
    tradier_closes: Mapping[date, float],
    splits: Sequence[SplitRecord],
    *,
    tolerance_bp: float,
) -> str | None:
    """The vendor whose own series is continuous across the run's boundaries, or None.

    At each boundary (the last common session before the run and the run's start; the run's end
    and the next common session) the ratio of the two vendors' moves is the step in the basis. A
    step within the tolerance judges nothing, and neither does a boundary a recorded split touches.
    On a judged boundary the vendor whose move exceeds everything in its own history away from the
    run's boundaries is the one that stepped; exactly one must have stepped. The run is classified
    only when every judged boundary names the same continuous vendor.
    """
    sessions = sorted(
        d
        for d in ibkr_closes.keys() & tradier_closes.keys()
        if ibkr_closes[d] > 0 and tradier_closes[d] > 0
    )
    if not sessions:
        return None
    ibkr_move = _log_moves(ibkr_closes, sessions)
    tradier_move = _log_moves(tradier_closes, sessions)
    tolerance_ln = tolerance_bp / _BP

    boundaries: list[tuple[date, date]] = []
    before = [d for d in sessions if d < run.start]
    if before:
        boundaries.append((before[-1], run.start))
    after = [d for d in sessions if d > run.end]
    if after:
        boundaries.append((run.end, after[0]))

    boundary_days = {cur for _, cur in boundaries}
    history_ibkr = max((m for d, m in ibkr_move.items() if d not in boundary_days), default=0.0)
    history_tradier = max(
        (m for d, m in tradier_move.items() if d not in boundary_days), default=0.0
    )
    ibkr_ceiling = max(history_ibkr, tolerance_ln)
    tradier_ceiling = max(history_tradier, tolerance_ln)

    verdicts: list[str | None] = []
    for prev, cur in boundaries:
        if any(prev <= s.effective_date <= cur for s in splits):
            continue
        step = abs(
            math.log(
                (ibkr_closes[cur] / ibkr_closes[prev])
                / (tradier_closes[cur] / tradier_closes[prev])
            )
        )
        if step * _BP <= tolerance_bp:
            continue
        ibkr_stepped = ibkr_move[cur] > ibkr_ceiling
        tradier_stepped = tradier_move[cur] > tradier_ceiling
        if ibkr_stepped == tradier_stepped:
            return None
        verdicts.append(VENDOR_TRADIER if ibkr_stepped else VENDOR_IBKR)
    if not verdicts or len(set(verdicts)) != 1:
        return None
    return verdicts[0]


def canonical_vendor(source: str) -> str | None:
    """The vendor behind a canonical 1d source label, or None for a non-canonical source."""
    if source not in CANONICAL_1D_SOURCES:
        return None
    return VENDOR_TRADIER if source == "tradier" else VENDOR_IBKR


def blocking(run: BasisRun, canonical_vendors: set[str]) -> bool:
    """A decided run blocks when the stored bars of its dates are not all from the continuous vendor."""
    if run.continuous_vendor is None or not canonical_vendors:
        return False
    return canonical_vendors != {run.continuous_vendor}
