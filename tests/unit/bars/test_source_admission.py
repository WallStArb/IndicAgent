"""Tradier admission on evidence (plan 185-38 Task 0): pure tests, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.source_admission import common_session_closes, tradier_admission

_TOL = 10.0
_MIN_OVERLAP = 60
_SHARE = 0.9


def _pairs(n: int, ratio: float = 1.0, start: date = date(2020, 1, 1)):
    return [(start + timedelta(days=i), 100.0, 100.0 * ratio) for i in range(n)]


def _admit(pairs):
    return tradier_admission(
        pairs, min_overlap=_MIN_OVERLAP, min_agree_share=_SHARE, tolerance_bp=_TOL
    )


def test_agreeing_history_is_admitted():
    result = _admit(_pairs(300))
    assert result.admitted and result.admitted_recent
    assert result.n_common == 300 and result.agree_share == 1.0
    assert result.median_ratio == pytest.approx(1.0)


def test_a_constant_basis_gap_is_refused():
    result = _admit(_pairs(300, ratio=6.7))  # CTVA-like
    assert not result.admitted and not result.admitted_recent
    assert result.agree_share == 0.0 and result.median_ratio == pytest.approx(6.7)


def test_no_common_session_is_refused():
    result = _admit([])
    assert not result.admitted and result.n_common == 0
    assert result.agree_share is None and result.median_ratio is None


def test_fewer_than_min_overlap_is_refused_even_when_agreeing():
    assert not _admit(_pairs(_MIN_OVERLAP - 1)).admitted
    assert _admit(_pairs(_MIN_OVERLAP)).admitted


def test_agreement_just_below_the_share_is_refused():
    good = _pairs(89)
    bad = _pairs(11, ratio=1.01, start=date(2021, 1, 1))
    result = _admit(good + bad)  # 89 of 100 agree
    assert result.agree_share == pytest.approx(0.89) and not result.admitted
    assert _admit(_pairs(90) + _pairs(10, ratio=1.01, start=date(2021, 1, 1))).admitted


def test_the_tolerance_is_inclusive_and_measured_in_basis_points():
    assert _admit(_pairs(100, ratio=1.001)).admitted  # exactly 10 bp
    assert not _admit(_pairs(100, ratio=1.0011)).admitted


def test_whole_history_failure_with_recent_agreement_is_admitted_recent():
    old = _pairs(200, ratio=1.5)  # RJF-like basis run in the past
    recent = _pairs(100, start=date(2021, 1, 1))
    result = _admit(list(reversed(old + recent)))  # order must not matter
    assert not result.admitted and result.admitted_recent
    assert result.recent_window == (recent[-_MIN_OVERLAP][0], recent[-1][0])


def test_recent_disagreement_fails_both():
    result = _admit(_pairs(200) + _pairs(100, ratio=0.6, start=date(2021, 1, 1)))
    assert not result.admitted and not result.admitted_recent


def _obs(route, day, close, fetched_at, request_id, legacy=False):
    return Observation(
        request_id=request_id,
        route=route,
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1,
        fetched_at=fetched_at,
        legacy=legacy,
        what_to_show="TRADES",
    )


def test_common_session_closes_use_latest_current_scale_smart_and_tradier_only():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(days=1)
    d1, d2, d3 = date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)
    split = SplitRecord(effective_date=date(2025, 1, 6), recorded_at=t1, factor=2.0)
    observations = [
        _obs("TRADIER", d1, 50.0, t1, "t1"),
        _obs("TRADIER", d1, 49.0, t0, "t0"),  # older answer, ignored
        _obs("SMART", d1, 50.5, t1, "s1"),
        _obs("SMART", d2, 70.0, t0, "s0"),  # stale scale: fetched before the split recorded
        _obs("TRADIER", d2, 35.0, t1, "t2"),
        _obs("LEGACY_IMPORT", d3, 60.0, t0, "l0", legacy=True),  # never a SMART close
        _obs("TRADIER", d3, 60.0, t1, "t3"),
        _obs("TRADIER", date(2025, 1, 7), 0.0, t1, "t4"),  # non-positive close measures nothing
        _obs("SMART", date(2025, 1, 7), 61.0, t1, "s4"),
    ]
    assert common_session_closes(observations, [split]) == [(d1, 50.0, 50.5)]
