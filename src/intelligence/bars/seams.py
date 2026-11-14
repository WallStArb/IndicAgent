"""Split-seam detection over two close series (D-24, D-21).

The seam audit compares stored daily closes with a fresh TRADES fetch of the
same span. IBKR re-scales history when a split happens, so a corpus stored
incrementally across a split keeps old days on the old scale while the fresh
fetch is on one scale: the stored/fresh ratio is the split factor on every
stored-old day and 1 afterwards. That ratio shape is a seam; a large one-day
price move (MRNA 2026-08-19, ALMS 2026-09-01) is not, because the ratio stays 1
through it. Volume never enters the decision: news events move volume too, the
ratio does not care.

A seam is a maximal run of at least min_run days whose ratio is constant within
rel_tol and differs from 1 by more than rel_tol. The run's end date is the
corporate-action date (the last day on the old scale) and its factor the run's
median ratio (2.0 = 2-for-1, 0.125 = 1-for-8). Runs are grown greedily left to
right: each day must keep the run's max/min ratio spread within rel_tol, so a
slow drift (each step small, the total unbounded) can never accumulate into a
"constant" run the way an adjacent-days-only test would let it.

Thresholds are keyword arguments supplied by callers from APR (plans 15 and 22
seed threshold.seam.rel_tol, threshold.seam.min_run,
threshold.seam.ratio_snap_tol); there are no defaults here.

Pure: arrays in, seams out; no database, no config service, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Seam:
    """One maximal constant-ratio run.

    start/end bound the run in calendar days, factor is its median stored/fresh
    ratio and n_days its length.
    """

    start: date
    end: date
    factor: float
    n_days: int
