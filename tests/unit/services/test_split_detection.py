"""Plan 185-22 (D-21): splits inferred from overlapping D1 observations.

detect_overlap_splits pairs each new SMART TRADES observation of a fetch run with the latest
earlier one for the same date and reads the stored/fresh close ratio: a constant run is a
split IBKR re-scaled history for; sizeable non-constant differences are reported as
unexplained and never recorded as a split. Against a fake connection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from services.split_detection import DetectedSplit, detect_overlap_splits
from src.intelligence.bars.corporate_actions import SplitRatioRule

_KW = {
    "rel_tol": 0.002,
    "min_run": 5,
    "ratio_snap_tol": 0.01,
    "split_rule": SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002),
}
_RUN = "11111111-1111-1111-1111-111111111111"
_ANSWERED = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)


def _row(symbol, day, prev_close, new_close, *, new_id="n1", prev_id="p1", answered=_ANSWERED):
    return {
        "symbol": symbol,
        "bar_date": day,
        "prev_close": prev_close,
        "new_close": new_close,
        "new_request_id": new_id,
        "prev_request_id": prev_id,
        "answered_at": answered,
    }


def _days(n, start=date(2026, 9, 1)):
    return [start + timedelta(days=i) for i in range(n)]


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows


def _run(rows, **kw):
    conn = FakeConn(rows)
    return asyncio.run(detect_overlap_splits(conn, fetch_run_id=_RUN, **{**_KW, **kw})), conn


def test_a_three_for_one_split_over_the_overlap_is_one_split_with_its_evidence():
    rows = [
        _row("XYZ", d, 300.0 + i, (300.0 + i) / 3, new_id=f"n{i}") for i, d in enumerate(_days(20))
    ]
    splits, _ = _run(rows)
    (split,) = splits
    assert split.symbol == "XYZ" and split.unexplained is False
    assert split.factor == pytest.approx(3.0)
    assert split.effective_date == _days(20)[-1]
    assert {"n0", "n19", "p1"} <= set(split.request_ids)


def test_a_reverse_split_factor_is_below_one():
    rows = [_row("XYZ", d, 10.0, 80.0) for d in _days(10)]
    (split,), _ = _run(rows)
    assert split.factor == pytest.approx(0.125) and not split.unexplained


def test_equal_closes_give_no_split():
    rows = [_row("XYZ", d, 50.0 + i, 50.0 + i) for i, d in enumerate(_days(20))]
    assert _run(rows)[0] == []


def test_cent_revisions_inside_the_tolerance_are_ignored():
    rows = [_row("XYZ", d, 50.00, 50.05) for d in _days(20)]
    assert _run(rows)[0] == []


def test_noisy_non_constant_differences_are_unexplained_never_a_split():
    ratios = [1.00, 1.04, 0.96, 1.07, 0.93, 1.05, 0.95, 1.06, 0.94, 1.03]
    rows = [_row("XYZ", d, 100.0 * r, 100.0) for d, r in zip(_days(10), ratios, strict=True)]
    (item,), _ = _run(rows)
    assert item.unexplained is True and item.symbol == "XYZ"


def test_fewer_overlapping_days_than_min_run_cannot_be_judged():
    rows = [_row("XYZ", d, 300.0, 100.0) for d in _days(4)]
    assert _run(rows)[0] == []


def test_the_session_of_the_answer_date_is_excluded_as_possibly_forming():
    day = _ANSWERED.date()
    rows = [_row("XYZ", d, 300.0, 100.0) for d in _days(10)]
    rows.append(_row("XYZ", day, 5.0, 100.0))  # a forming bar must not extend or break a run
    (split,), _ = _run(rows)
    assert split.effective_date == _days(10)[-1]


def test_symbols_are_judged_independently():
    rows = [_row("AAA", d, 90.0, 30.0) for d in _days(10)] + [
        _row("BBB", d, 40.0, 40.0) for d in _days(10)
    ]
    splits, _ = _run(rows)
    assert [(s.symbol, round(s.factor, 6)) for s in splits] == [("AAA", 3.0)]


def test_the_query_is_scoped_to_the_run_and_excludes_test_callers():
    _, conn = _run([])
    sql, args = conn.calls[0]
    assert args == (_RUN,)
    assert "q.caller NOT LIKE 'test-%'" in sql
    assert "q.fetch_run_id <> $1" in sql and "q.route = 'SMART'" in sql


def test_a_non_positive_close_raises_loudly_with_the_symbol():
    rows = [_row("XYZ", d, 0.0, 10.0) for d in _days(10)]
    with pytest.raises(ValueError, match="XYZ"):
        _run(rows)


def test_detected_split_is_a_value_object():
    a = DetectedSplit("XYZ", date(2026, 9, 20), 3.0, ("n1",), False)
    assert a == DetectedSplit("XYZ", date(2026, 9, 20), 3.0, ("n1",), False)


# --- plan 185-51 (todo 515): only a recognised split ratio is a split ------------------------


def test_a_constant_rescale_that_is_no_split_ratio_is_an_unclassified_rescale():
    """CTVA 2026-10-08: IBKR restated every pre-spin-off bar by 39/7. The seam is constant and
    snaps to 39/7 (p, q <= 50), but 39/7 is no split ratio, so it is never a split."""
    rows = [_row("CTVA", d, 77.65 + i, (77.65 + i) * 7 / 39) for i, d in enumerate(_days(20))]
    (item,), _ = _run(rows)
    assert item.unclassified is True and item.unexplained is False
    assert item.factor == pytest.approx(39 / 7, rel=1e-6)  # the measured ratio, not a snap
    assert item.first_date == _days(20)[0] and item.effective_date == _days(20)[-1]


def test_a_one_for_three_reverse_split_is_recorded_at_the_exact_ratio():
    rows = [
        _row("ETHA", d, 20.31 + i * 0.01, (20.31 + i * 0.01) * 3) for i, d in enumerate(_days(8))
    ]
    (split,), _ = _run(rows)
    assert split.unclassified is False and split.unexplained is False
    assert split.factor == 1 / 3 and split.first_date == _days(8)[0]


def test_the_split_rule_is_required():
    with pytest.raises(TypeError):
        asyncio.run(
            detect_overlap_splits(
                FakeConn([]), fetch_run_id=_RUN, rel_tol=0.002, min_run=5, ratio_snap_tol=0.01
            )
        )
