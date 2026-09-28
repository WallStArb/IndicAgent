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
import pytest

from src.intelligence.bars.seams import find_seams
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


def test_two_for_one_split_found_ending_day_before_scale_change() -> None:
    days = _sessions(250)
    stored, fresh = _rescaled(250, 180, 2.0)
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert len(seams) == 1
    seam = seams[0]
    assert seam.start == days[0]
    assert seam.end == days[179]
    assert seam.factor == pytest.approx(2.0)
    assert seam.n_days == 180
    assert seam.max_rel_dev <= _REL_TOL


def test_one_for_eight_reverse_split_found() -> None:
    days = _sessions(250)
    stored, fresh = _rescaled(250, 180, 0.125, seed=12)
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert len(seams) == 1
    assert seams[0].end == days[179]
    assert seams[0].factor == pytest.approx(0.125)
    assert seams[0].n_days == 180


def test_twenty_for_one_split_found() -> None:
    days = _sessions(250)
    stored, fresh = _rescaled(250, 180, 20.0, seed=13)
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert len(seams) == 1
    assert seams[0].factor == pytest.approx(20.0)


def test_mrna_and_alms_event_series_have_no_seam() -> None:
    for symbol in ("MRNA", "ALMS"):
        days, closes = _fixture_symbol(symbol)
        assert len(days) > 50
        seams = find_seams(days, closes, closes.copy(), rel_tol=_REL_TOL, min_run=_MIN_RUN)
        assert seams == []


def test_noise_within_rel_tol_is_still_one_seam() -> None:
    days = _sessions(250)
    stored = random_walk_closes(250, 200.0, seed=21)
    rng = np.random.default_rng(22)
    noise = rng.uniform(-0.003, 0.003, 250)
    fresh = stored / (2.0 * (1.0 + noise))
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert len(seams) == 1
    assert seams[0].end == days[249]
    assert seams[0].factor == pytest.approx(2.0, rel=0.01)


def test_drifting_ratio_produces_no_seam() -> None:
    days = _sessions(250)
    stored = random_walk_closes(250, 100.0, seed=31)
    fresh = stored / (1.003 ** np.arange(250))
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert seams == []


def test_two_seams_in_one_series_are_both_found() -> None:
    days = _sessions(250)
    stored = random_walk_closes(250, 100.0, seed=41)
    fresh = stored.copy()
    fresh[:100] = stored[:100] / 2.0
    fresh[150:] = stored[150:] / 0.5
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert len(seams) == 2
    first, second = seams
    assert (first.start, first.end) == (days[0], days[99])
    assert first.factor == pytest.approx(2.0)
    assert (second.start, second.end) == (days[150], days[249])
    assert second.factor == pytest.approx(0.5)


def test_run_shorter_than_min_run_is_not_a_seam() -> None:
    days = _sessions(40)
    stored, fresh = _rescaled(40, 3, 2.0, seed=51)
    seams = find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
    assert seams == []


def test_length_mismatch_raises() -> None:
    days = _sessions(10)
    stored = random_walk_closes(10, 100.0, seed=61)
    fresh = random_walk_closes(9, 100.0, seed=62)
    with pytest.raises(ValueError, match="length"):
        find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)


def test_non_positive_close_raises() -> None:
    days = _sessions(10)
    stored = random_walk_closes(10, 100.0, seed=71)
    fresh = stored.copy()
    fresh[4] = 0.0
    with pytest.raises(ValueError, match="positive"):
        find_seams(days, stored, fresh, rel_tol=_REL_TOL, min_run=_MIN_RUN)
