"""Vendor basis runs (plan 185-33): runs where the IBKR/Tradier close ratio leaves the basis
tolerance, and which vendor is continuous across each run boundary.

Known answers from tests/fixtures/bars/d2v2_known_cases.json: RJF (IBKR steps +52% at
2021-09-22 with no corporate action, Tradier continuous) and REX (Tradier steps 15.5 to 30.5 at
2025-09-09, IBKR continuous). Pure: no database.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from src.intelligence.bars.daily_rule import current_closes
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.vendor_basis import (
    VENDOR_IBKR,
    VENDOR_TRADIER,
    BasisRun,
    blocking,
    canonical_vendor,
    classify_run,
    find_basis_runs,
    ratio_pairs,
)

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "bars" / "d2v2_known_cases.json"
_TOL_BP = 10.0
_MIN = 5


def _case(symbol: str) -> tuple[dict[date, float], dict[date, float], list[SplitRecord]]:
    case = json.loads(_FIXTURE.read_text())["cases"][symbol]
    observations = [
        Observation(
            request_id=o["request_id"],
            route=o["route"],
            bar_date=date.fromisoformat(o["bar_date"]),
            open=o["open"],
            high=o["high"],
            low=o["low"],
            close=o["close"],
            volume=o["volume"],
            fetched_at=datetime.fromisoformat(o["fetched_at"]),
            legacy=o["route"] == "LEGACY_IMPORT",
            what_to_show=o["what_to_show"],
        )
        for o in case["observations"]
    ]
    splits = [
        SplitRecord(
            effective_date=date.fromisoformat(s["effective_date"]),
            recorded_at=datetime.fromisoformat(s["recorded_at"]),
            factor=s["factor"],
            evidence_request_ids=tuple(s.get("evidence_request_ids") or ()),
        )
        for s in case["splits"]
    ]
    tradier, ibkr = current_closes(observations, splits)
    return ibkr, tradier, splits


def _days(n: int, start: date = date(2024, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


# --- find_basis_runs ---------------------------------------------------------------------------


def test_rjf_one_run_ending_before_the_ibkr_step():
    ibkr, tradier, _ = _case("RJF")
    runs = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert len(runs) == 1
    (run,) = runs
    assert run.end == date(2021, 9, 21)
    assert run.median_ratio == pytest.approx(0.6667, abs=1e-3)
    assert run.n_sessions >= _MIN
    assert run.continuous_vendor is None  # classification is classify_run's job


def test_rex_finds_the_september_2025_run():
    ibkr, tradier, _ = _case("REX")
    runs = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert len(runs) == 1
    assert runs[0].end == date(2025, 9, 8)
    assert runs[0].median_ratio == pytest.approx(2.0, abs=1e-3)


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


def test_a_non_positive_tradier_close_measures_nothing_and_breaks_no_run():
    days = _days(6)
    pairs = [(d, 101.0, 100.0) for d in days]
    pairs[2] = (days[2], 101.0, 0.0)
    runs = find_basis_runs(pairs, tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert [(r.start, r.end, r.n_sessions) for r in runs] == [(days[0], days[5], 5)]


def test_ratio_pairs_are_the_common_dates_in_order():
    a, b, c = _days(3)
    assert ratio_pairs({c: 3.0, a: 1.0}, {a: 2.0, b: 5.0, c: 6.0}) == [(a, 1.0, 2.0), (c, 3.0, 6.0)]


# --- classify_run -------------------------------------------------------------------------------


def test_rjf_tradier_is_continuous():
    ibkr, tradier, splits = _case("RJF")
    (run,) = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert classify_run(run, ibkr, tradier, splits, tolerance_bp=_TOL_BP) == VENDOR_TRADIER


def test_rex_ibkr_is_continuous():
    ibkr, tradier, splits = _case("REX")
    (run,) = find_basis_runs(ratio_pairs(ibkr, tradier), tolerance_bp=_TOL_BP, min_sessions=_MIN)
    assert classify_run(run, ibkr, tradier, splits, tolerance_bp=_TOL_BP) == VENDOR_IBKR


def test_a_run_with_no_boundary_session_is_undecided():
    days = _days(5)
    ibkr = {d: 200.0 for d in days}
    tradier = {d: 100.0 for d in days}
    run = BasisRun(days[0], days[-1], 5, 2.0, None)
    assert classify_run(run, ibkr, tradier, [], tolerance_bp=_TOL_BP) is None


def test_a_drift_back_inside_tolerance_is_no_step():
    # The ratio sits 12 bp out for the run, then 8 bp out: a 4 bp move judges nothing.
    days = _days(7)
    tradier = {d: 100.0 for d in days}
    ibkr = {d: 100.12 for d in days[:6]} | {days[6]: 100.08}
    run = BasisRun(days[0], days[5], 6, 1.0012, None)
    assert classify_run(run, ibkr, tradier, [], tolerance_bp=_TOL_BP) is None


def test_both_vendors_moving_is_undecided():
    days = _days(7)
    tradier = {d: 100.0 for d in days[:6]} | {days[6]: 120.0}
    ibkr = {d: 200.0 for d in days[:6]} | {days[6]: 120.0}  # IBKR -40%, Tradier +20%
    run = BasisRun(days[0], days[5], 6, 2.0, None)
    assert classify_run(run, ibkr, tradier, [], tolerance_bp=_TOL_BP) is None


def test_boundaries_that_disagree_are_undecided():
    days = _days(9)
    # Entry: IBKR steps (Tradier continuous); exit: Tradier steps (IBKR continuous).
    tradier = {days[0]: 100.0} | {d: 100.0 for d in days[1:8]} | {days[8]: 200.0}
    ibkr = {days[0]: 100.0} | {d: 200.0 for d in days[1:8]} | {days[8]: 200.0}
    run = BasisRun(days[1], days[7], 7, 2.0, None)
    assert classify_run(run, ibkr, tradier, [], tolerance_bp=_TOL_BP) is None


def test_a_boundary_on_a_recorded_split_is_not_judged():
    days = _days(7)
    tradier = {d: 100.0 for d in days}
    ibkr = {d: 200.0 for d in days[:6]} | {days[6]: 100.0}
    run = BasisRun(days[0], days[5], 6, 2.0, None)
    split = SplitRecord(
        effective_date=days[5],
        recorded_at=datetime(2024, 2, 1),
        factor=0.5,
        evidence_request_ids=(),
    )
    assert classify_run(run, ibkr, tradier, [], tolerance_bp=_TOL_BP) == VENDOR_TRADIER
    assert classify_run(run, ibkr, tradier, [split], tolerance_bp=_TOL_BP) is None


# --- canonical side -----------------------------------------------------------------------------


def test_canonical_vendor_maps_sources():
    assert canonical_vendor("tradier") == VENDOR_TRADIER
    for source in ("ibkr_named", "ibkr_fallback", "ibkr_venue"):
        assert canonical_vendor(source) == VENDOR_IBKR
    assert canonical_vendor("synthetic_fill") is None


def test_blocking_only_when_the_canonical_side_is_discontinuous():
    run = BasisRun(date(2024, 1, 1), date(2024, 1, 9), 7, 2.0, VENDOR_TRADIER)
    assert not blocking(run, {VENDOR_TRADIER})
    assert blocking(run, {VENDOR_IBKR})
    assert blocking(run, {VENDOR_TRADIER, VENDOR_IBKR})
    assert not blocking(run, set())
    undecided = BasisRun(date(2024, 1, 1), date(2024, 1, 9), 7, 2.0, None)
    assert not blocking(undecided, {VENDOR_IBKR})
