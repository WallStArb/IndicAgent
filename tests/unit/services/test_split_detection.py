"""Plan 185-22 (D-21), moved to raw in plan 191-10: splits inferred from overlapping 1d answers.

detect_overlap_splits pairs each SMART TRADES answer of a fetch run (its ohlcv_raw row, or a
value of it ohlcv_revision holds) with the latest earlier answer of the same date, ordered by
ohlcv_request.answered_at, and reads the stored/fresh close ratio: a constant run is a split
IBKR re-scaled history for; sizeable non-constant differences are reported as unexplained and
never recorded as a split. Against a fake connection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from services.split_detection import (
    _ANSWERS_SQL,
    _CHANGED_SYMBOLS_SQL,
    _RUN_REQUESTS_SQL,
    DetectedSplit,
    detect_overlap_splits,
    pair_answers,
)
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
    """Serves the three reads from overlap-pair rows: each row becomes an earlier answer of
    another run (a day before the fresh one) and the run's own answer of that date."""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if sql == _RUN_REQUESTS_SQL:
            seen = {(r["symbol"], r["new_request_id"]): r for r in self.rows}
            return [
                {
                    "request_id": rid,
                    "symbol": sym,
                    "answered_at": r["answered_at"],
                    "lo": None,
                    "hi": r["answered_at"].date(),
                }
                for (sym, rid), r in seen.items()
            ]
        if sql == _CHANGED_SYMBOLS_SQL:
            return [{"symbol": sym} for sym in args[1]]
        assert sql == _ANSWERS_SQL
        out = []
        for r in self.rows:
            out.append(
                {
                    "symbol": r["symbol"],
                    "bar_date": r["bar_date"],
                    "close": r["prev_close"],
                    "request_id": r["prev_request_id"],
                    "answered_at": r["answered_at"] - timedelta(days=1),
                    "fetch_run_id": "other",
                }
            )
            out.append(
                {
                    "symbol": r["symbol"],
                    "bar_date": r["bar_date"],
                    "close": r["new_close"],
                    "request_id": r["new_request_id"],
                    "answered_at": r["answered_at"],
                    "fetch_run_id": _RUN,
                }
            )
        return out


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
    # New-scale requests only: d2-v2 counts a split's evidence as current, so the earlier
    # old-scale request must never be named (plan 185-51).
    assert {"n0", "n19"} <= set(split.request_ids) and "p1" not in split.request_ids


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


def test_the_reads_are_scoped_to_the_run_and_read_raw_and_revision_only():
    rows = [_row("XYZ", d, 300.0, 100.0) for d in _days(10)]
    _, conn = _run(rows)
    assert [c[0] for c in conn.calls] == [_RUN_REQUESTS_SQL, _CHANGED_SYMBOLS_SQL, _ANSWERS_SQL]
    assert conn.calls[0][1] == (_RUN,)
    for sql in (_RUN_REQUESTS_SQL, _ANSWERS_SQL):
        assert "q.caller NOT LIKE 'test-%'" in sql
    assert "q.fetch_run_id = $1" in _RUN_REQUESTS_SQL and "q.route = 'SMART'" in _RUN_REQUESTS_SQL
    for sql in (_CHANGED_SYMBOLS_SQL, _ANSWERS_SQL):
        assert "ohlcv_raw" in sql and "ohlcv_revision" in sql
        assert "ohlcv_observation" not in sql and "loaded_at" not in sql


class _NothingChanged(FakeConn):
    async def fetch(self, sql, *args):
        if sql == _CHANGED_SYMBOLS_SQL:
            self.calls.append((sql, args))
            return []
        return await super().fetch(sql, *args)


def test_a_run_that_changed_no_name_reads_no_answers():
    conn = _NothingChanged([_row("XYZ", d, 1.0, 1.0) for d in _days(3)])
    assert asyncio.run(detect_overlap_splits(conn, fetch_run_id=_RUN, **_KW)) == []
    assert [c[0] for c in conn.calls] == [_RUN_REQUESTS_SQL, _CHANGED_SYMBOLS_SQL]


def _req(rid, answered, lo=None, hi=date(2026, 10, 3)):
    return {"request_id": rid, "symbol": "XYZ", "answered_at": answered, "lo": lo, "hi": hi}


def _ans(day, close, rid, answered, run="other"):
    return {
        "symbol": "XYZ",
        "bar_date": day,
        "close": close,
        "request_id": rid,
        "answered_at": answered,
        "fetch_run_id": run,
    }


def test_an_unchanged_re_serve_pairs_with_the_earlier_answer_itself():
    day = date(2026, 9, 1)
    pairs = pair_answers(
        _RUN, [_req("n1", _ANSWERED)], [_ans(day, 10.0, "p1", _ANSWERED - timedelta(days=3))]
    )
    (row,) = pairs["XYZ"]
    assert (row["prev_close"], row["new_close"], row["new_request_id"]) == (10.0, 10.0, "n1")


def test_the_latest_earlier_answer_by_answered_at_is_the_partner():
    day = date(2026, 9, 1)
    answers = [
        _ans(day, 10.0, "old", _ANSWERED - timedelta(days=9)),
        _ans(day, 11.0, "mid", _ANSWERED - timedelta(days=2)),
        _ans(day, 12.0, "later", _ANSWERED + timedelta(days=1)),
        _ans(day, 33.0, "n1", _ANSWERED, run=_RUN),
    ]
    (row,) = pair_answers(_RUN, [_req("n1", _ANSWERED)], answers)["XYZ"]
    assert (row["prev_close"], row["prev_request_id"], row["new_close"]) == (11.0, "mid", 33.0)


def test_a_forming_earlier_answer_is_no_partner():
    day = date(2026, 9, 1)
    forming = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
    answers = [_ans(day, 9.0, "f", forming), _ans(day, 10.0, "n1", _ANSWERED, run=_RUN)]
    assert pair_answers(_RUN, [_req("n1", _ANSWERED)], answers) == {}


def test_a_date_outside_every_run_window_is_not_paired():
    day = date(2026, 9, 1)
    answers = [_ans(day, 10.0, "p1", _ANSWERED - timedelta(days=3))]
    reqs = [_req("n1", _ANSWERED, lo=date(2026, 9, 20))]
    assert pair_answers(_RUN, reqs, answers) == {}


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
