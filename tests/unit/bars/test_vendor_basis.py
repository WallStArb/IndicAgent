"""Vendor basis runs (plan 185-33): runs where a vendor close ratio leaves the basis tolerance.

The Tradier-specific cases (RJF and REX known answers, run classification, the canonical side)
went with the Tradier code deletion (phase 191 plan 22). Pure: no database.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.intelligence.bars.vendor_basis import find_basis_runs

_TOL_BP = 10.0
_MIN = 5


def _days(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


# --- find_basis_runs ---------------------------------------------------------------------------


def test_runs_shorter_than_min_sessions_are_not_reported():
    days = _days(10)
    pairs = [(d, 100.0, 100.0) for d in days]
    for i in (3, 4, 5, 6):  # four sessions out of tolerance
        pairs[i] = (days[i], 101.0, 100.0)
    assert find_basis_runs(pairs, tolerance_bp=_TOL_BP, min_sessions=_MIN) == []
    pairs[7] = (days[7], 101.0, 100.0)  # now five
    runs = find_basis_runs(pairs, tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert [(r.start, r.end, r.n_sessions) for r in runs] == [(days[3], days[7], 5)]


def test_ratios_within_tolerance_never_start_a_run():
    days = _days(30)
    # 9 bp off every session: inside the 10 bp tolerance.
    pairs = [(d, 100.09, 100.0) for d in days]
    assert find_basis_runs(pairs, tolerance_bp=_TOL_BP, min_sessions=_MIN) == []


def test_a_non_positive_close_measures_nothing_and_breaks_no_run():
    days = _days(6)
    pairs = [(d, 101.0, 100.0) for d in days]
    pairs[2] = (days[2], 101.0, 0.0)
    runs = find_basis_runs(pairs, tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert [(r.start, r.end, r.n_sessions) for r in runs] == [(days[0], days[5], 5)]
