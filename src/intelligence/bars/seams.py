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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass(frozen=True)
class Seam:
    """One maximal constant-ratio run.

    start/end bound the run in calendar days, factor is its median stored/fresh
    ratio, n_days its length and max_rel_dev the largest relative deviation of
    any day's ratio from the reported factor.
    """

    start: date
    end: date
    factor: float
    n_days: int
    max_rel_dev: float


def find_seams(
    days: Sequence[date],
    stored_close: np.ndarray,
    fresh_close: np.ndarray,
    *,
    rel_tol: float,
    min_run: int,
) -> list[Seam]:
    """Seams in a stored-vs-fresh daily close series (pure).

    Raises ValueError on a length mismatch between days and either close array,
    on a non-positive rel_tol or min_run below 1, or on any non-finite or
    non-positive close: a zero or NaN price would make the ratio silently
    inf/NaN and either invent a seam or hide one.
    """
    day_list = list(days)
    stored = np.asarray(stored_close, dtype=float)
    fresh = np.asarray(fresh_close, dtype=float)
    if len(day_list) != stored.size or len(day_list) != fresh.size:
        raise ValueError(
            f"length mismatch: {len(day_list)} days, {stored.size} stored, {fresh.size} fresh"
        )
    if not (rel_tol > 0.0) or min_run < 1:
        raise ValueError(
            f"rel_tol must be positive and min_run at least 1, got {rel_tol}, {min_run}"
        )
    for name, arr in (("stored", stored), ("fresh", fresh)):
        if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
            raise ValueError(f"non-finite or non-positive close in the {name} series")

    ratios = (stored / fresh).tolist()
    seams: list[Seam] = []
    n = len(ratios)

    def close_run(start: int, end_exclusive: int) -> None:
        if end_exclusive - start < min_run:
            return
        segment = np.asarray(ratios[start:end_exclusive])
        factor = float(np.median(segment))
        seams.append(
            Seam(
                start=day_list[start],
                end=day_list[end_exclusive - 1],
                factor=factor,
                n_days=end_exclusive - start,
                max_rel_dev=float(np.max(np.abs(segment / factor - 1.0))),
            )
        )

    start = 0
    run_min: float | None = None
    run_max: float | None = None
    for j, ratio in enumerate(ratios):
        near_one = (1.0 - rel_tol) <= ratio <= (1.0 + rel_tol)
        if near_one:
            close_run(start, j)
            start = j + 1
            run_min = run_max = None
            continue
        if run_min is None:
            start = j
            run_min = run_max = ratio
        elif max(run_max, ratio) / min(run_min, ratio) - 1.0 <= rel_tol:
            run_min = min(run_min, ratio)
            run_max = max(run_max, ratio)
        else:
            close_run(start, j)
            start = j
            run_min = run_max = ratio
    close_run(start, n)
    return seams
