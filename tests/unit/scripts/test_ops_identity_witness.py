"""The identity witness for gap-list spans (design 8c): pure tests, no database."""

from __future__ import annotations

import gzip
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.ops.bars.ops_identity_witness import (
    _IBKR_SQL,
    _ISSUER_OVERVIEW_SQL,
    ACTIVE_SOURCE,
    ADMISSIBLE,
    AGREES,
    AMBIGUOUS,
    CORROBORATION_CONFLICT,
    DISAGREES,
    EVIDENCE_FIGI_ABSENT,
    EVIDENCE_FIGI_SAME,
    EVIDENCE_OWN_PRE_EVENT,
    IDENTITY_NO_REFERENCE,
    IDENTITY_OTHER_ISSUER,
    IDENTITY_REUSE_UNDATED,
    LEVEL_UNEXPLAINED,
    MARKER,
    MISSING,
    NO_FILE_COVERAGE,
    NON_EQUITY_SECURITY,
    PLACED,
    PREDECESSOR,
    RETURNS_DISAGREE,
    TENURE_UNCAPTURED,
    THIN,
    UNCLEAR,
    IssuerRecord,
    References,
    Span,
    candidate_tickers,
    contested_sessions,
    continuity,
    corroboration_label,
    documentary_tenure,
    evaluate_documentary,
    issuer_match,
    judge,
    own_run_evidence,
    place_span,
    placement_runs,
    read_day_files,
    read_issuer_records,
    settle_sessions,
    shell_delisting,
    span_decision,
    tape_verdict,
)

DAYS = [date(2005, 1, 3) + timedelta(days=i) for i in range(300)]


def _walk(seed: int) -> dict[date, float]:
    price, out = 50.0, {}
    for i, day in enumerate(DAYS):
        price *= math.exp(0.01 * math.sin(seed * 7.1 + i * 1.3))
        out[day] = round(price, 2)
    return out


def test_the_same_tape_places_and_a_split_is_rescaled_first():
    ibkr = _walk(1)
    split_day = DAYS[150]
    massive = {d: c * (2.0 if d <= split_day else 1.0) for d, c in ibkr.items()}  # raw, unadjusted
    scales = {d: 2.0 if d <= split_day else 1.0 for d in massive}
    matched, pairs, agreeing, corr, median, iqr, decision = judge(massive, ibkr, scales)
    assert (matched, pairs, agreeing) == (300, 299, 299)
    assert corr > 0.999 and abs(median) < 1e-9 and decision == PLACED


def test_another_tape_disagrees_and_a_short_one_is_thin():
    assert judge(_walk(2), _walk(1), {})[-1] == RETURNS_DISAGREE
    short = dict(list(_walk(1).items())[:20])
    assert judge(short, short, {})[-1] == THIN  # 19 returns, under the 8a minimum of 20


def test_a_close_definition_difference_still_places_on_correlation():
    """The first calibration's failure: the same security, closes off by a few cents on many
    days (last trade against official close), fails 99 percent agreement but correlates."""
    ibkr = _walk(1)
    massive = {d: c + (0.03 if i % 3 == 0 else 0.0) for i, (d, c) in enumerate(ibkr.items())}
    matched, pairs, agreeing, corr, *_rest, decision = judge(massive, ibkr, {})
    assert agreeing < 0.99 * pairs and corr >= 0.9 and decision == PLACED


def test_split_sized_returns_leave_the_identity_correlation():
    from scripts.ops.bars.ops_identity_witness import identity_correlation, split_sized

    assert split_sized(math.log(4 / 3)) and split_sized(-math.log(2)) and not split_sized(0.2)
    base = [0.01 * math.sin(i) for i in range(40)]
    shocked = [*base[:20], -math.log(4 / 3), *base[21:]]
    assert identity_correlation(shocked, base) > 0.99


def test_a_stable_unexplained_offset_does_not_place():
    ibkr = _walk(1)
    massive = {d: c * 1.05 for d, c in ibkr.items()}  # a 5 percent level no split explains
    assert judge(massive, ibkr, {})[-1] == LEVEL_UNEXPLAINED


def test_continuity_reads_listing_then_markers():
    refs = References(
        list_date={"OLD": date(1990, 1, 1), "SPAC": date(2021, 6, 1), "REUSE": date(1990, 1, 1)},
        figi={"OLD": "F1", "REUSE": "F3"},
        events={"OLD": [(date(2003, 9, 10), "OLD")]},
        delisted={"REUSE": [("F9", date(2008, 1, 2))], "OLD": [("F1", date(2001, 1, 2))]},
    )
    span = (date(2003, 9, 10), date(2012, 1, 3))
    assert continuity(refs, "OLD", "before_first_event", *span, "OLD") is None
    assert continuity(refs, "SPAC", "before_first_event", *span, "SPAC") == PREDECESSOR
    assert continuity(refs, "NONE", "before_first_event", *span, "NONE") == MISSING
    assert continuity(refs, "REUSE", "before_first_event", *span, "REUSE") == MARKER
    assert continuity(refs, "OLD", "ticker_claimed_by_other_security", *span, "OLD") == MARKER


def test_a_span_places_on_exactly_one_candidate():
    assert span_decision([PLACED, THIN]) == PLACED
    assert span_decision([PLACED, PLACED]) == AMBIGUOUS
    assert span_decision([THIN, PREDECESSOR, RETURNS_DISAGREE]) == PREDECESSOR
    assert span_decision([]) == THIN


# ---- documentary rule (8c amendment 2026-11-14) ----


def _rec(ticker, cik="C1", scf="", kind="CS", gone=None, source="delisted"):
    return IssuerRecord(ticker, cik, scf, kind, gone, source)


def _current(ticker, cik="C1", scf="S1", kind="CS"):
    return _rec(ticker, cik, scf, kind, None, ACTIVE_SOURCE)


def _refs(*records, listed=None):
    by_ticker: dict[str, list] = {}
    for r in records:
        by_ticker.setdefault(r.ticker, []).append(r)
    return References(list_date=listed or {}, figi={}, events={}, delisted={}, issuers=by_ticker)


def _place(refs, span, sessions, agrees=None):
    cands, claims = place_span(refs, span, sessions)
    return (cands, *settle_sessions(claims, agrees or {}))


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def test_issuer_match_needs_the_cik_and_never_passes_another_issuer():
    cur = _current("LUMN", "C1", "S1")
    assert issuer_match(cur, _rec("CTL", "C1", "S1")) == EVIDENCE_FIGI_SAME
    assert issuer_match(cur, _rec("QQQQ", "C1", "")) == EVIDENCE_FIGI_ABSENT  # missing FIGI
    assert issuer_match(cur, _rec("X", "C1", "S2")) is None  # another share class
    assert issuer_match(cur, _rec("BWC", "C2", "")) is None  # another issuer
    assert issuer_match(cur, _rec("SGH", "", "")) is None  # no CIK never passes
    assert issuer_match(cur, _rec("ETF", "C1", "", kind="ETF")) is None  # another security type


def test_a_rename_splits_the_span_at_the_first_and_last_file_day_of_each_ticker():
    refs = _refs(
        _current("LUMN", "C1", "S1"),
        _rec("CTL", "C1", "S1", gone=date(2020, 9, 18)),
        listed={"LUMN": date(1978, 10, 24)},
    )
    span = Span("LUMN", "before_first_event", date(2003, 9, 10), date(2020, 9, 25), ("LUMN",))
    ctl = _days(date(2003, 9, 10), date(2020, 9, 17))
    sessions = {"CTL": ctl, "LUMN": _days(date(2020, 9, 18), date(2020, 9, 24))}
    cands, assigned, dropped, _ = _place(refs, span, sessions)
    assert dropped == {}
    assert placement_runs(assigned, dropped) == [
        ("CTL", date(2003, 9, 10), date(2020, 9, 18), len(ctl)),
        ("LUMN", date(2020, 9, 18), date(2020, 9, 25), 7),
    ]
    assert {c.ticker: c.evidence for c in cands} == {
        "CTL": EVIDENCE_FIGI_SAME,
        "LUMN": "own_record",
    }


def test_the_predecessor_is_a_candidate_though_no_map_row_or_gap_detail_names_it():
    refs = _refs(
        _current("LUMN"),
        _rec("CTL", "C1", "S1", gone=date(2020, 9, 18)),
        listed={"LUMN": date(1978, 10, 24)},
    )
    span = Span("LUMN", "before_first_event", date(2020, 9, 1), date(2020, 9, 18), ("LUMN",))
    cands, assigned, *_ = _place(refs, span, {"CTL": _days(date(2020, 9, 1), date(2020, 9, 17))})
    assert "CTL" in {c.ticker for c in cands} and list(assigned) == ["CTL"]


def test_qqq_history_in_the_gap_is_placed_on_qqqq_with_a_missing_figi():
    refs = _refs(
        _current("QQQ", "C9", "S9", "ETF"),
        _rec("QQQQ", "C9", "", kind="", gone=date(2011, 3, 23)),
        listed={"QQQ": date(1999, 3, 10)},
    )
    span = Span("QQQ", "before_first_event", date(2004, 12, 1), date(2011, 3, 23), ("QQQ",))
    sessions = {
        "QQQQ": [date(2004, 12, 1), date(2004, 12, 2), date(2011, 3, 21), date(2011, 3, 22)],
        "QQQ": [date(2004, 11, 30), date(2011, 3, 23), date(2011, 3, 24)],
    }
    cands, assigned, dropped, _ = _place(refs, span, sessions)
    assert placement_runs(assigned, dropped) == [("QQQQ", date(2004, 12, 1), date(2011, 3, 23), 4)]
    assert {c.ticker: (c.decision, c.evidence) for c in cands} == {
        "QQQ": (NO_FILE_COVERAGE, "own_record"),
        "QQQQ": (ADMISSIBLE, EVIDENCE_FIGI_ABSENT),
    }


def test_a_reused_ticker_that_the_witness_rejects_loses_the_contested_sessions():
    refs = _refs(
        _current("SSB", "C3", "S3"),
        _rec("SCBT", "C3", "", gone=date(2014, 6, 30)),
        listed={"SSB": date(1990, 1, 1)},
    )
    span = Span("SSB", "before_first_event", date(2004, 3, 9), date(2014, 6, 30), ("SSB",))
    scbt = _days(date(2004, 3, 9), date(2004, 3, 20)) + _days(date(2014, 6, 20), date(2014, 6, 27))
    scbt.remove(date(2004, 3, 12))  # SCBT has no bar that day: the other issuer's SSB bar stays out
    sessions = {"SCBT": scbt, "SSB": [date(2004, 3, 12), date(2004, 3, 15), date(2014, 6, 30)]}
    cands, claims = place_span(refs, span, sessions)
    assert contested_sessions(claims) == {date(2004, 3, 15): ("SCBT", "SSB")}
    _, assigned, dropped, lost = _place(refs, span, sessions, {"SCBT": AGREES, "SSB": DISAGREES})
    assert placement_runs(assigned, dropped)[0][:2] == ("SCBT", date(2004, 3, 9))
    assert lost == {"SSB"} and "SSB" not in assigned and len(dropped["SSB"]) == 2
    assert date(2004, 3, 15) in assigned["SCBT"]
    # no corroboration, or both corroborated: the contested session goes to no one
    for agrees in ({}, {"SCBT": AGREES, "SSB": AGREES}):
        _, assigned, dropped, lost = _place(refs, span, sessions, agrees)
        assert lost == set() and date(2004, 3, 15) in dropped["SCBT"]
        assert date(2004, 3, 12) in assigned["SSB"] and date(2004, 3, 15) not in assigned["SCBT"]


def test_another_issuer_or_no_record_rejects_whatever_the_names_resemble():
    cur = _current("BWXT", "C1", "S1")
    other = documentary_tenure(cur, [_rec("BWC", "C2", "", gone=date(2023, 8, 7))])
    assert other.reject == IDENTITY_OTHER_ISSUER
    assert documentary_tenure(cur, []).reject == IDENTITY_NO_REFERENCE
    undated_other = [_rec("EXP", "C1", "S1", gone=date(2010, 1, 1)), _rec("EXP", "C7", "")]
    assert documentary_tenure(cur, undated_other).reject == IDENTITY_REUSE_UNDATED
    dated_other = [
        _rec("EXP", "C1", "S1", source=ACTIVE_SOURCE),
        _rec("EXP", "C7", "", gone=date(2006, 1, 2)),
    ]
    assert documentary_tenure(cur, dated_other).lower == date(2006, 1, 2)


def test_a_boundary_follows_the_first_file_day_not_the_event_date():
    # the ticker_change event is dated 2015-10-27 and AROC's first file day is 2015-11-04: the
    # old gate called an event inside the span a predecessor marker; the span is EXH's tape
    refs = References(
        list_date={"AROC": date(2013, 1, 1)},
        figi={"AROC": "F"},
        events={"AROC": [(date(2015, 10, 27), "AROC")]},
        delisted={},
        issuers={
            "AROC": [_current("AROC")],
            "EXH": [_rec("EXH", "C1", "", gone=date(2015, 11, 4))],
        },
    )
    span = Span("AROC", "before_first_event", date(2015, 10, 23), date(2015, 11, 4), ("AROC",))
    assert continuity(refs, "AROC", span.reason, span.start, span.end, "AROC") == MARKER
    sessions = {"EXH": _days(date(2015, 10, 23), date(2015, 11, 3)), "AROC": [date(2015, 11, 4)]}
    _, assigned, dropped, _ = _place(refs, span, sessions)
    assert placement_runs(assigned, dropped) == [("EXH", date(2015, 10, 23), date(2015, 11, 4), 12)]


def test_the_own_ticker_before_the_listing_date_or_under_mixed_identity_is_not_placed():
    refs = _refs(_current("TKO"), listed={"TKO": date(2023, 9, 12)})
    span = Span("TKO", "before_first_event", date(2003, 9, 10), date(2023, 10, 1), ("TKO",))
    sessions = {"TKO": [date(2005, 1, 3), date(2023, 9, 11), date(2023, 9, 12), date(2023, 9, 13)]}
    _, assigned, *_ = _place(refs, span, sessions)
    assert assigned == {"TKO": (date(2023, 9, 12), date(2023, 9, 13))}
    mixed = Span("TKO", "ticker_claimed_by_other_security", span.start, span.end, ("TKO",))
    cands, assigned, *_ = _place(refs, mixed, sessions)
    assert assigned == {} and cands[0].decision == MARKER
    assert _place(_refs(), span, sessions)[0][0].decision == MISSING


def test_a_session_claimed_by_two_tickers_goes_to_neither_and_breaks_the_runs():
    d = _days(date(2020, 1, 1), date(2020, 1, 6))
    claims = {"A": d[:4], "B": d[3:]}
    assert contested_sessions(claims) == {d[3]: ("A", "B")}
    assigned, dropped, lost = settle_sessions(claims, {})
    assert assigned == {"A": tuple(d[:3]), "B": tuple(d[4:])} and lost == set()
    assert dropped == {"A": (d[3],), "B": (d[3],)}
    assert placement_runs(assigned, dropped) == [
        ("A", d[0], d[2] + timedelta(days=1), 3),
        ("B", d[4], d[5] + timedelta(days=1), 2),
    ]


def test_a_contested_tape_is_judged_on_correlation_and_a_stable_level_not_on_the_offset():
    nan = math.nan
    assert tape_verdict((347, 230, 128, 0.93, 0.0488, 0.0002, LEVEL_UNEXPLAINED)) == AGREES
    assert tape_verdict((293, 292, 83, 0.9666, 0.0334, 0.0208, LEVEL_UNEXPLAINED)) == UNCLEAR
    assert tape_verdict((347, 230, 7, -0.07, -1.25, 0.1062, RETURNS_DISAGREE)) == DISAGREES
    assert tape_verdict((4, 0, 0, nan, nan, nan, THIN)) == UNCLEAR


def test_a_contradicted_claimant_is_out_and_the_one_left_takes_the_session():
    d = _days(date(2020, 1, 1), date(2020, 1, 4))
    claims = {"CAL": d, "BWS": d}
    assigned, dropped, lost = settle_sessions(claims, {"CAL": DISAGREES, "BWS": UNCLEAR})
    assert assigned == {"BWS": tuple(d)} and lost == {"CAL"}  # not corroborated, but alone
    assigned, _, lost = settle_sessions(claims, {"CAL": UNCLEAR, "BWS": AGREES})
    assert assigned == {"BWS": tuple(d)} and lost == {"CAL"}
    assigned, dropped, lost = settle_sessions(claims, {"CAL": UNCLEAR, "BWS": UNCLEAR})
    assert assigned == {} and lost == set() and dropped["CAL"] == tuple(d)
    assigned, *_ = settle_sessions(claims, {"CAL": DISAGREES, "BWS": DISAGREES})
    assert assigned == {}


def test_an_undated_own_row_cannot_be_ordered_against_a_dated_other_issuer():
    cur = _current("AAA", "C1", "S1")
    other = _rec("OLD", "C7", "", gone=date(2006, 1, 2))
    undated_row = _rec("OLD", "C1", "", gone=None)  # a delisted row without a date
    assert documentary_tenure(cur, [undated_row, other]).reject == IDENTITY_REUSE_UNDATED
    assert documentary_tenure(cur, [undated_row]).reject is None  # nothing to order it against
    active = _rec("OLD", "C1", "S1", None, source=ACTIVE_SOURCE)  # the latest holder
    assert documentary_tenure(cur, [active, other]).lower == date(2006, 1, 2)


def test_candidates_are_the_symbol_named_tickers_and_every_documentary_pass():
    cur = _current("LUMN", "C1", "S1")
    issuers = {
        "LUMN": [cur],
        "CTL": [_rec("CTL", "C1", "S1", gone=date(2020, 9, 18))],
        "BWC": [_rec("BWC", "C2", "")],
    }
    assert candidate_tickers("LUMN", cur, ["NAMED"], issuers) == ("CTL", "LUMN", "NAMED")
    assert candidate_tickers("LUMN", None, [], issuers) == ("LUMN",)


def test_a_name_with_no_overview_answer_is_missing_not_placed():
    refs = _refs(listed={"X": date(1990, 1, 1)})
    span = Span("X", "before_first_event", date(2005, 1, 3), date(2005, 2, 1), ("X",))
    cands, claims = place_span(refs, span, {"X": [date(2005, 1, 4)]})
    assert claims == {} and [c.decision for c in cands] == [MISSING]


def test_a_ticker_that_loses_a_contest_is_placed_nowhere_in_the_span():
    d = _days(date(2020, 1, 1), date(2020, 1, 10))
    claims = {"A": d[:6], "B": d[4:]}  # B alone on d[6:], contested on d[4:6]
    assigned, dropped, lost = settle_sessions(claims, {"A": AGREES, "B": DISAGREES})
    assert lost == {"B"} and assigned == {"A": tuple(d[:6])} and dropped == {"B": tuple(d[4:])}
    assert settle_sessions(claims, {"A": AGREES, "B": AGREES})[0]["B"] == tuple(d[6:])


def test_a_run_before_the_event_that_gave_the_name_its_ticker_is_labelled():
    refs = References(
        {}, {}, {"HON": [(date(2026, 6, 29), "HON"), (date(2026, 6, 15), "HONI")]}, {}
    )
    assert own_run_evidence(refs, "HON", date(2026, 6, 15), "own_record") == EVIDENCE_OWN_PRE_EVENT
    assert own_run_evidence(refs, "HON", date(2026, 6, 29), "own_record") == "own_record"
    assert own_run_evidence(refs, "NONE", date(2026, 6, 15), "own_record") == "own_record"
    assert corroboration_label(PLACED, 0.0) == "agrees"
    assert corroboration_label(THIN, -0.54) == "thin_level_offset"
    assert corroboration_label(THIN, 0.0) == THIN
    assert corroboration_label(THIN, math.nan) == THIN
    assert corroboration_label(LEVEL_UNEXPLAINED, 0.3) == LEVEL_UNEXPLAINED


class _Cursor:
    """The IBKR series and no splits: what evaluate_documentary reads."""

    def __init__(self, ibkr):
        self.ibkr, self._last = ibkr, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._last = sql

    def fetchall(self):
        return list(self.ibkr.items()) if self._last == _IBKR_SQL else []


class _Conn:
    def __init__(self, ibkr):
        self.ibkr = ibkr

    def cursor(self):
        return _Cursor(self.ibkr)


def _documentary_run(ibkr):
    refs = _refs(
        _current("AAA", "C1", "S1"),
        _rec("OLD", "C1", "S1", gone=DAYS[-1] + timedelta(days=1)),
        listed={"AAA": date(1990, 1, 1)},
    )
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[-1] + timedelta(days=1), ("AAA",))
    closes = {"OLD": {d: c for d, c in _walk(1).items()}}
    return evaluate_documentary(
        _Conn(ibkr), [span], refs, closes, datetime(2026, 11, 13, tzinfo=UTC)
    )


def test_evaluate_documentary_places_on_the_documentary_pass_and_reports_corroboration():
    placements, spans, cands = _documentary_run(_walk(1))
    assert [(r["file_ticker"], r["sessions"], r["corroboration"]) for r in placements] == [
        ("OLD", len(DAYS), "agrees")
    ]
    assert spans[0]["decision"] == PLACED and spans[0]["unplaced_file_sessions"] == 0
    assert {c["candidate"]: c["decision"] for c in cands} == {
        "AAA": NO_FILE_COVERAGE,
        "OLD": PLACED,
    }


def test_evaluate_documentary_holds_a_placement_the_witness_measures_as_another_tape():
    placements, spans, cands = _documentary_run(_walk(2))
    assert placements == []
    assert spans[0]["decision"] == CORROBORATION_CONFLICT
    assert spans[0]["unplaced_file_sessions"] == len(DAYS)
    assert {c["candidate"]: c["decision"] for c in cands}["OLD"] == CORROBORATION_CONFLICT


def test_the_day_reader_takes_the_close_by_header_and_refuses_another_layout(tmp_path):
    day = date(2005, 1, 3)
    path = tmp_path / f"{day:%Y/%m/%Y-%m-%d}.csv.gz"
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt") as handle:
        handle.write("ticker,volume,open,close\nAAA,5,1.0,2.5\nBBB,5,1.0,0\nCCC,5,1.0,3.0\n")
    got = read_day_files(tmp_path, {"AAA", "BBB"}, day, day + timedelta(days=1))
    assert got == {"AAA": {day: 2.5}}  # a zero close is no bar; CCC was not asked for
    with gzip.open(path, "wt") as handle:
        handle.write("volume,ticker,open,close\n5,AAA,1.0,2.5\n")
    with pytest.raises(ValueError, match="not 'ticker'"):
        read_day_files(tmp_path, {"AAA"}, day, day + timedelta(days=1))


class _Rows:
    def __init__(self, overview, delisted):
        self.overview, self.delisted = overview, delisted

    def execute(self, sql):
        self.rows = self.overview if sql == _ISSUER_OVERVIEW_SQL else self.delisted
        return self

    def fetchall(self):
        return self.rows


def test_issuer_records_read_dated_tails_and_skip_an_empty_answer():
    conn = _Rows(
        [
            ("LUMN", "active", "C1", "S1", "CS"),
            ("CTL", "2020-09-18", "C1", "S1", "CS"),
            ("SGH", "active", None, None, None),  # an empty answer: no record
        ],
        [("QQQQ", "C9", None, None, "2011-03-23T04:00:00Z"), ("SGH", "C5", None, "CS", None)],
    )
    got = read_issuer_records(conn)
    assert got["LUMN"][0].source == ACTIVE_SOURCE and got["LUMN"][0].gone is None
    assert got["CTL"][0].gone == date(2020, 9, 18)
    assert got["QQQQ"][0].gone == date(2011, 3, 23) and got["QQQQ"][0].share_class_figi == ""
    assert [r.cik for r in got["SGH"]] == ["C5"]


def test_a_shell_ticker_of_the_same_cik_is_not_placed_before_the_name_listed():
    # the blank-check shell OAC became HIMS: same CIK and FIGI, but the 8c listing guard keeps its
    # pre-merger tape (the 34 predecessor_history names of the calibration) out of the name
    refs = _refs(
        _current("HIMS", "C1", "S1"),
        _rec("OAC", "C1", "", gone=date(2021, 1, 21)),
        listed={"HIMS": date(2021, 1, 21)},
    )
    span = Span("HIMS", "predecessor_check", date(2019, 9, 13), date(2021, 1, 21), ("HIMS",))
    cands, claims = place_span(refs, span, {"OAC": _days(date(2019, 9, 13), date(2021, 1, 20))})
    assert claims == {} and {c.ticker: c.decision for c in cands}["OAC"] == NO_FILE_COVERAGE


def test_an_uncorroborated_own_run_before_its_event_is_flagged_for_the_lead_read():
    refs = _refs(_current("HON"), listed={"HON": date(1929, 9, 19)})
    refs = References(
        refs.list_date, {}, {"HON": [(DAYS[10], "HON")]}, {}, refs.issuers
    )  # the event giving the name HON falls after the first sessions
    span = Span("HON", "before_first_event", DAYS[0], DAYS[5], ("HON",))
    closes = {"HON": {d: 50.0 for d in DAYS[:5]}}
    placements, spans, _ = evaluate_documentary(
        _Conn({}), [span], refs, closes, datetime(2026, 11, 13, tzinfo=UTC)
    )
    assert placements[0]["documentary_identity"] == EVIDENCE_OWN_PRE_EVENT
    assert placements[0]["corroboration"] == THIN
    assert placements[0]["lead_read"] == "pre_event_not_corroborated"
    assert spans[0]["decision"] == PLACED


def test_a_sibling_class_with_no_figi_never_takes_a_session_it_shares_with_the_name():
    # CMCSK-like: same CIK, no share-class FIGI, trades on the same sessions as the name
    refs = _refs(
        _current("AAA", "C1", "S1"),
        _rec("AAAK", "C1", "", gone=date(2012, 12, 14)),
        listed={"AAA": date(1973, 1, 2)},
    )
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[20], ("AAA", "AAAK"))
    both = {"AAA": DAYS[:10], "AAAK": DAYS[:10]}
    _, claims = place_span(refs, span, both)
    assert set(claims) == {"AAA", "AAAK"}  # the contest decides, not a pass
    # the sibling agrees and the name is unclear: the sibling still wins nothing
    assigned, dropped, lost = settle_sessions(claims, {"AAAK": AGREES}, no_win={"AAAK"})
    assert assigned == {} and set(dropped) == {"AAA", "AAAK"} and lost == set()
    # the name agrees: it takes them and the sibling is lost
    assigned, _, lost = settle_sessions(claims, {"AAA": AGREES}, no_win={"AAAK"})
    assert list(assigned) == ["AAA"] and lost == {"AAAK"}


def test_a_predecessor_with_no_figi_places_dated_or_not_with_or_without_a_gap_to_the_new_ticker():
    for gone in (date(2005, 3, 1), None):  # an undated delisted row still places: no shared tape
        refs = _refs(
            _current("VIAV", "C1", "S1"),
            _rec("JDSU", "C1", "", gone=gone),
            listed={"VIAV": date(1993, 11, 1)},
        )
        span = Span("VIAV", "before_first_event", DAYS[0], DAYS[40], ("VIAV", "JDSU"))
        for new_first in (DAYS[10], DAYS[30]):  # abutting, and a gap before the new ticker
            sessions = {"JDSU": DAYS[:10], "VIAV": [d for d in DAYS[:40] if d >= new_first]}
            cands, claims = place_span(refs, span, sessions)
            assert claims["JDSU"] == tuple(DAYS[:10])
            assert {c.ticker: c.evidence for c in cands}["JDSU"] == EVIDENCE_FIGI_ABSENT
            assigned, dropped, _ = settle_sessions(claims, {}, no_win={"JDSU"})
            assert assigned["JDSU"] == tuple(DAYS[:10]) and dropped == {}


def test_a_unit_warrant_or_right_ticker_never_places_whatever_its_cik_and_figi():
    for kind in ("UNIT", "WARRANT", "RIGHT"):
        refs = _refs(
            _current("AAA", "C1", "S1"),
            _rec("AAAX", "C1", "S1", kind=kind, gone=date(2005, 3, 1)),
            listed={"AAA": date(1990, 1, 1)},
        )
        span = Span("AAA", "before_first_event", DAYS[0], DAYS[20], ("AAA", "AAAX"))
        cands, claims = place_span(refs, span, {"AAAX": DAYS[:5]})
        assert claims == {}
        assert {c.ticker: c.decision for c in cands}["AAAX"] == NON_EQUITY_SECURITY


def _spce_like():
    """A name whose list_date is its blank-check shell's IPO: IPOA (CS), units and warrants of one
    CIK, the shell delisted on the combination day."""
    gone = DAYS[100]
    refs = _refs(
        _current("SPCE", "C1", "S1"),
        _rec("IPOA", "C1", "", kind="CS", gone=gone),
        _rec("IPOA.U", "C1", "", kind="UNIT", gone=gone),
        _rec("IPOA.WS", "C1", "", kind="WARRANT", gone=gone),
        listed={"SPCE": DAYS[0]},  # the shell's IPO
    )
    return refs, gone


def test_the_shell_delisting_day_not_list_date_bounds_the_name_s_tape():
    refs, gone = _spce_like()
    assert shell_delisting("SPCE", refs.issuers["SPCE"][0], refs.issuers) == gone
    span = Span("SPCE", "before_first_event", DAYS[90], DAYS[110], ("SPCE", "IPOA"))
    sessions = {"IPOA": DAYS[90:101], "SPCE": DAYS[95:110]}  # SPCE's file also carries shell days
    cands, claims = place_span(refs, span, sessions)
    assert claims["SPCE"] == tuple(DAYS[101:110])  # strictly after the shell's last day
    assert "IPOA" not in claims  # the shell's own tape ends at its delisting: nothing after it
    assert {c.ticker: c.decision for c in cands}["IPOA"] == NO_FILE_COVERAGE


def test_without_a_unit_warrant_or_right_the_list_date_stands():
    refs = _refs(
        _current("SPCE", "C1", "S1"),
        _rec("IPOA", "C1", "", kind="CS", gone=DAYS[100]),
        listed={"SPCE": DAYS[0]},
    )
    assert shell_delisting("SPCE", refs.issuers["SPCE"][0], refs.issuers) is None


def test_a_window_starts_strictly_after_the_other_issuers_last_day():
    refs = _refs(
        _current("AAA", "C1", "S1"),
        _rec("AAA", "C7", "", gone=DAYS[5]),
        listed={"AAA": date(1990, 1, 1)},
    )
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[20], ("AAA",))
    _, claims = place_span(refs, span, {"AAA": DAYS[:15]})
    assert claims["AAA"] == tuple(DAYS[6:15])


def test_a_reused_ticker_with_no_captured_other_issuer_end_is_flagged_not_silent():
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[60], ("AAA",))
    listed = {"AAA": date(1990, 1, 1)}
    refs = _refs(_current("AAA", "C1", "S1"), listed=listed)
    gap = DAYS[:5] + DAYS[30:35]  # absent for weeks inside the tenure
    cands, _ = place_span(refs, span, {"AAA": gap})
    assert cands[0].lead_read == TENURE_UNCAPTURED
    cands, _ = place_span(refs, span, {"AAA": DAYS[:10]})
    assert cands[0].lead_read == ""
    bounded = _refs(_current("AAA", "C1", "S1"), _rec("AAA", "C7", "", gone=DAYS[2]), listed=listed)
    cands, _ = place_span(bounded, span, {"AAA": DAYS[:10]})
    assert cands[0].lead_read == ""  # the other issuer's end is captured


def test_the_tenure_flag_reaches_the_placement_row():
    refs = _refs(_current("AAA", "C1", "S1"), listed={"AAA": date(1990, 1, 1)})
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[60], ("AAA",))
    closes = {"AAA": {d: 50.0 for d in DAYS[:5] + DAYS[30:35]}}
    placements, _, _ = evaluate_documentary(
        _Conn({}), [span], refs, closes, datetime(2026, 11, 13, tzinfo=UTC)
    )
    assert placements and all(TENURE_UNCAPTURED in r["lead_read"] for r in placements)


def test_a_sibling_wins_only_when_the_witness_contradicts_the_name_s_own_tape():
    # SSB-like: the own ticker's file tape is another issuer's and the witness says so
    d = _days(date(2020, 1, 1), date(2020, 1, 5))
    claims = {"AAA": d, "AAAK": d}
    assigned, _, lost = settle_sessions(claims, {"AAA": DISAGREES, "AAAK": AGREES}, {"AAAK"})
    assert assigned == {"AAAK": tuple(d)} and lost == {"AAA"}
    assigned, _, lost = settle_sessions(claims, {"AAA": DISAGREES}, {"AAAK"})  # sole one left
    assert assigned == {"AAAK": tuple(d)}
    # both agree: the name takes the sessions, never the sibling
    assigned, _, lost = settle_sessions(claims, {"AAA": AGREES, "AAAK": AGREES}, {"AAAK"})
    assert assigned == {"AAA": tuple(d)} and lost == {"AAAK"}


def test_evaluate_documentary_bars_a_no_figi_ticker_from_sessions_the_name_carries():
    refs = _refs(
        _current("AAA", "C1", "S1"),
        _rec("AAAK", "C1", "", gone=date(2012, 12, 14)),
        listed={"AAA": date(1973, 1, 2)},
    )
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[20], ("AAA", "AAAK"))
    closes = {t: {d: 50.0 for d in DAYS[:10]} for t in ("AAA", "AAAK")}
    placements, spans, _ = evaluate_documentary(
        _Conn({}), [span], refs, closes, datetime(2026, 11, 13, tzinfo=UTC)
    )
    assert all(r["file_ticker"] != "AAAK" for r in placements)  # nothing agrees: nobody places
    assert spans[0]["placed_sessions"] == 0


def test_a_renamed_predecessor_with_unrelated_rights_is_not_a_shell():
    refs = _refs(
        _current("VATE", "C1", "S1"),
        _rec("PTGI", "C1", "", kind="CS", gone=DAYS[50]),
        _rec("VATEr", "C1", "", kind="RIGHT", gone=DAYS[200]),
        listed={"VATE": DAYS[0]},
    )
    assert shell_delisting("VATE", refs.issuers["VATE"][0], refs.issuers) is None


def test_another_issuers_warrant_on_a_reused_ticker_does_not_reject_the_name_s_ticker():
    refs = _refs(
        _current("AAA", "C1", "S1"),
        _rec("AAAX", "C1", "S1", gone=DAYS[100]),
        _rec("AAAX", "C9", "", kind="WARRANT", gone=DAYS[2]),
        listed={"AAA": date(1990, 1, 1)},
    )
    span = Span("AAA", "before_first_event", DAYS[0], DAYS[20], ("AAA", "AAAX"))
    cands, claims = place_span(refs, span, {"AAAX": DAYS[:10]})
    assert claims["AAAX"] == tuple(DAYS[3:10])
