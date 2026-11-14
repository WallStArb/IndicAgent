"""Seam detection tests (D-24, D-21).

A seam is a maximal run of at least min_run days whose stored/fresh close ratio
is constant within rel_tol and differs from 1 beyond rel_tol: the audit's one
definition of "the stored corpus changed scale here". Known answers: synthetic
2:1, 1:8 and 20:1 scale changes land on the day before the change with the right
factor; MRNA- and ALMS-shaped single-day event series (fresh equals stored)
produce no seam; noise within rel_tol is one seam; a drifting ratio is none.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tests.unit.bars._builders import random_walk_closes

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "bars" / "seam_candidates_mrna_alms.csv"

# Study-shaped caller values; the audit itself reads these from APR (plans 15
# and 22 seed threshold.seam.*). Noise sigma below is sized so the synthetic
# bands stay well inside rel_tol, away from floating-point boundaries.
_REL_TOL = 0.01
_MIN_RUN = 5


def _sessions(n: int, start: date = date(2025, 1, 6)) -> list[date]:
    """n consecutive weekdays from a Monday start."""
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _rescaled(n: int, cut: int, factor: float, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    """stored series and a fresh series equal to stored / factor before day cut.

    ratio = stored / fresh is `factor` on [0, cut) and 1 from cut on, the shape
    an incremental nightly fetch leaves behind after a split IBKR re-scaled.
    """
    stored = random_walk_closes(n, 100.0, seed)
    fresh = stored.copy()
    fresh[:cut] = stored[:cut] / factor
    return stored, fresh


def _fixture_symbol(symbol: str) -> tuple[list[date], np.ndarray]:
    frame = pd.read_csv(_FIXTURE)
    frame = frame[frame["symbol"] == symbol].sort_values("timestamp")
    days = [pd.Timestamp(ts).date() for ts in frame["timestamp"]]
    return days, frame["close"].to_numpy(dtype=float)
