"""The pit-anchor planner (todo 609, stage 2): runs, securities, spans, symbols, residual."""

from __future__ import annotations

from datetime import date

import pytest

from src.intelligence.bars.ticker_entity_map_pit import (
    ALREADY_LIVE,
    CIK_TICKER,
    CLAIMED_TWICE,
    CLIPPED_BY_LIVE_SPAN,
    COMPOSITE_FIGI,
    MASSIVE_ARCHIVE_START,
    NO_KEY,
    PLACED,
    PLACED_PARTIAL,
    SHARE_CLASS_FIGI,
    LiveState,
    PitPlanError,
    PitRecord,
    PitSnapshot,
    pins,
    pit_record,
    plan_pit_map,
    records_from_pages,
)

M = [
    date(2003, 9, 30), date(2003, 10, 31), date(2003, 11, 28), date(2003, 12, 31),
    date(2004, 1, 30), date(2004, 2, 27),
]  # fmt: skip
CF1, CF2 = "BBG000C2V3D6", "BBG000B9XB24"  # both match the composite FIGI format
SF1 = "BBG001SCTQY4"
CIK_A, CIK_B = "0000000001", "0000000002"
NO_LIVE = LiveState(frozenset(), {}, ())


def rec(ticker, cik=None, cf=None, sf=None, typ=None, delisted=None, name=None):
    return PitRecord(ticker, cik, cf, sf, typ, name, None, delisted, f"raw-{ticker}")


def snap(i, active=(), inactive=()):
    return PitSnapshot(M[i], tuple(active), tuple(inactive))


def plan(snaps, live=NO_LIVE):
    return plan_pit_map(snaps, live)


def by_symbol(p):
    return {s.symbol: s for s in p.securities}


def test_cik_only_run_is_one_security_from_the_archive_start_to_the_first_month_end_it_is_absent():
    p = plan([snap(0, [rec("AAA", CIK_A)]), snap(1, [rec("AAA", CIK_A)]), snap(2)])
    assert [s.symbol for s in p.securities] == ["AAA"]
    (span,) = p.spans
    assert (span.start, span.end) == (MASSIVE_ARCHIVE_START, M[2])
    (ident,) = p.identifiers
    assert (ident.scheme, ident.value) == (CIK_TICKER, f"{CIK_A}:AAA")
    assert p.securities[0].key_kind == CIK_TICKER


def test_a_run_that_starts_after_the_first_snapshot_starts_at_its_first_month_end():
    p = plan([snap(0), snap(1, [rec("BBB", CIK_A)]), snap(2, [rec("BBB", CIK_A)]), snap(3)])
    (span,) = p.spans
    assert (span.start, span.end) == (M[1], M[3])


def test_a_run_present_in_the_last_snapshot_is_open():
    p = plan([snap(0, [rec("CCC", CIK_A)]), snap(1, [rec("CCC", CIK_A)])])
    assert p.spans[0].end is None
    assert p.securities[0].last is None


def test_composite_figi_upgrade_with_the_same_cik_keeps_one_run_and_keys_on_the_figi():
    p = plan([
        snap(0, [rec("DDD", CIK_A)]),
        snap(1, [rec("DDD", CIK_A)]),
        snap(2, [rec("DDD", CIK_A, cf=CF1, sf=SF1)]),
    ])  # fmt: skip
    (sec,) = p.securities
    assert (sec.key_kind, sec.key_value) == (COMPOSITE_FIGI, CF1)
    assert len(p.spans) == 1
    schemes = {(i.scheme, i.value) for i in p.identifiers}
    assert schemes == {(COMPOSITE_FIGI, CF1), (SHARE_CLASS_FIGI, SF1)}


def test_two_composite_figis_on_one_ticker_are_two_securities_even_with_one_cik():
    p = plan([
        snap(0, [rec("EEE", CIK_A, cf=CF1)]),
        snap(1, [rec("EEE", CIK_A, cf=CF1)]),
        snap(2, [rec("EEE", CIK_A, cf=CF2)]),
        snap(3, [rec("EEE", CIK_A, cf=CF2)]),
    ])  # fmt: skip
    assert len(p.securities) == 2
    spans = sorted(p.spans, key=lambda s: s.start)
    assert spans[0].end == date(2003, 11, 1) and spans[1].start == M[2]
    assert spans[0].end <= spans[1].start


def test_a_reused_ticker_is_two_securities_and_the_later_one_gets_a_suffixed_symbol():
    p = plan([
        snap(0, [rec("FFF", CIK_A)]),
        snap(1, [rec("FFF", CIK_A)]),
        snap(2, [rec("FFF", CIK_B)]),
        snap(3, [rec("FFF", CIK_B)]),
    ])  # fmt: skip
    syms = {s.symbol: s for s in p.securities}
    assert set(syms) == {"FFF", "FFF~2"}
    assert syms["FFF"].cik == CIK_A and syms["FFF~2"].cik == CIK_B
    gap = [s for s in p.spans]
    assert max(s.end for s in gap if s.symbol == "FFF") == date(2003, 11, 1)
    # the days between the first holder's last month-end and the second's first are in no span
    assert min(s.start for s in gap if s.symbol == "FFF~2") == M[2]


def test_a_rename_with_one_composite_figi_is_one_security_named_by_its_last_ticker():
    p = plan([
        snap(0, [rec("OLD", cf=CF1, cik=CIK_A)]),
        snap(1, [rec("OLD", cf=CF1, cik=CIK_A)]),
        snap(2, [rec("NEW", cf=CF1, cik=CIK_A)]),
        snap(3, [rec("NEW", cf=CF1, cik=CIK_A)]),
    ])  # fmt: skip
    (sec,) = p.securities
    assert sec.symbol == "NEW" and sec.tickers == ("NEW", "OLD")
    assert {(s.ticker) for s in p.spans} == {"OLD", "NEW"}
    assert all(s.symbol == "NEW" for s in p.spans)


def test_a_composite_figi_served_under_two_tickers_in_one_snapshot_is_unplaced_that_month():
    p = plan([
        snap(0, [rec("GGG", cf=CF1, cik=CIK_A)]),
        snap(1, [rec("GGG", cf=CF1, cik=CIK_A), rec("GGH", cf=CF1, cik=CIK_A)]),
        snap(2, [rec("GGG", cf=CF1, cik=CIK_A)]),
    ])  # fmt: skip
    claimed = sum(n for (_, _, why), n in p.residual.items() if why == CLAIMED_TWICE)
    assert claimed == 2
    # the claimed month is one missing month inside GGG's listing: bridged, so one open span
    assert [(s.start, s.end) for s in p.spans] == [(MASSIVE_ARCHIVE_START, None)]
    assert p.bridged_months == 1


def test_a_record_with_no_cik_and_no_composite_figi_is_unplaced_and_counted_by_year_and_type():
    p = plan([snap(0, [rec("HHH", typ="CS")]), snap(1, [rec("HHH", typ="CS")])])
    assert p.securities == ()
    assert p.residual[(2003, "CS", NO_KEY)] == 2
    assert (2003, "CS", PLACED) not in p.residual


def test_a_malformed_figi_or_cik_counts_as_not_served():
    r = pit_record({"ticker": "III", "cik": "12", "composite_figi": "bad"}, "raw")
    assert (r.cik, r.composite_figi) == (None, None)


def test_a_run_whose_composite_figi_is_live_is_left_to_the_live_map():
    live = LiveState(frozenset({"LIV"}), {(COMPOSITE_FIGI, CF1): "LIV"}, ())
    p = plan([snap(0, [rec("LIV", cf=CF1, cik=CIK_A, typ="CS")])], live)
    assert p.securities == () and p.spans == ()
    assert p.residual[(2003, "CS", ALREADY_LIVE)] == 1


def test_a_live_share_class_figi_also_leaves_the_run_to_the_live_map():
    live = LiveState(frozenset({"LIV"}), {(SHARE_CLASS_FIGI, SF1): "LIV"}, ())
    p = plan([snap(0, [rec("LIX", cf=CF2, sf=SF1, cik=CIK_A)])], live)
    assert p.securities == ()


def test_a_ticker_window_held_by_a_live_span_is_not_given_to_a_new_security():
    live = LiveState(frozenset({"EXE"}), {}, (("JJJ", date(2003, 10, 15), None),))
    p = plan(
        [snap(0, [rec("JJJ", CIK_A)]), snap(1, [rec("JJJ", CIK_A)]), snap(2, [rec("JJJ", CIK_A)])],
        live,
    )
    spans = sorted(p.spans, key=lambda s: s.start)
    assert [(s.start, s.end) for s in spans] == [(MASSIVE_ARCHIVE_START, date(2003, 10, 15))]
    assert sum(n for (_, _, why), n in p.residual.items() if why == PLACED_PARTIAL) == 3


def test_a_run_wholly_inside_a_live_span_is_dropped_and_counted():
    live = LiveState(frozenset(), {}, (("KKK", date(2003, 1, 1), None),))
    p = plan(
        [snap(0, [rec("KKK", CIK_A, typ="ETF")]), snap(1, [rec("KKK", CIK_A, typ="ETF")])], live
    )
    assert p.spans == ()
    assert p.residual[(2003, "ETF", CLIPPED_BY_LIVE_SPAN)] == 2


def test_a_run_on_a_ticker_an_instrument_with_spans_holds_gets_a_suffixed_symbol():
    live = LiveState(frozenset({"LLL"}), {}, (), {}, frozenset({"LLL"}))
    p = plan([snap(0, [rec("LLL", CIK_A)]), snap(1)], live)
    assert [s.symbol for s in p.securities] == ["LLL~1"]


def test_an_active_run_whose_ticker_is_an_instrument_with_no_live_span_is_that_instrument():
    live = LiveState(frozenset({"ROKU"}), {}, (), {}, frozenset())
    p = plan(
        [snap(0, [rec("ROKU", CIK_A, typ="CS")]), snap(1, [rec("ROKU", CIK_A, typ="CS")])], live
    )
    assert p.securities == () and p.spans == ()
    assert p.residual[(2003, "CS", ALREADY_LIVE)] == 2


def test_every_earlier_run_of_the_active_instruments_key_is_left_to_the_live_map_too():
    live = LiveState(frozenset({"OLDN"}), {}, ())
    p = plan([
        snap(0, [rec("OLDO", cf=CF1, cik=CIK_A)]),
        snap(1, [rec("OLDN", cf=CF1, cik=CIK_A)]),
    ], live)  # fmt: skip
    assert p.securities == ()


def test_the_active_instrument_rule_does_not_swallow_a_stage2_symbol_of_the_same_key():
    key = (CIK_TICKER, f"{CIK_A}:LLL")
    live = LiveState(frozenset({"LLL"}), {}, (), {key: "LLL"})
    p = plan([snap(0, [rec("LLL", CIK_A)])], live)
    assert [s.symbol for s in p.securities] == ["LLL"]


def test_a_first_snapshot_run_starts_after_another_holders_delisting_in_the_archive_window():
    old_holder = rec("TTT", CIK_B, delisted=date(2003, 9, 15))
    p = plan([snap(0, [rec("TTT", CIK_A)], [old_holder]), snap(1)])
    assert p.spans[0].start == date(2003, 9, 15)


def test_a_first_snapshot_run_keeps_the_archive_start_when_the_other_holder_left_earlier():
    gone = rec("TTT", CIK_B, delisted=date(2001, 5, 1))
    p = plan([snap(0, [rec("TTT", CIK_A)], [gone]), snap(1)])
    assert p.spans[0].start == MASSIVE_ARCHIVE_START


def test_two_inactive_records_of_the_runs_own_cik_suppress_the_delisting_hint():
    a, b = rec("UUU", CIK_A, delisted=date(2003, 10, 10)), rec(
        "UUU", CIK_A, delisted=date(2003, 10, 20)
    )
    p = plan([snap(0, [rec("UUU", CIK_A)]), snap(1, [], [a, b])])
    assert p.spans[0].end == M[1]


def test_a_composite_figi_held_by_two_tickers_over_the_same_days_gives_the_overlap_to_neither():
    # BBB serves the FIGI in month 1 only; AAA omits it that month but keeps its run by CIK
    p = plan([
        snap(0, [rec("AAA", cf=CF1, cik=CIK_A, typ="CS")]),
        snap(1, [rec("AAA", cik=CIK_A, typ="CS"), rec("BBB", cf=CF1, cik=CIK_A, typ="CS")]),
        snap(2, [rec("AAA", cf=CF1, cik=CIK_A, typ="CS")]),
        snap(3),
    ])  # fmt: skip
    assert [s.ticker for s in p.spans] == ["AAA", "AAA"]
    assert [(s.start, s.end) for s in sorted(p.spans, key=lambda s: s.start)] == [
        (MASSIVE_ARCHIVE_START, M[1]),
        (M[2], M[3]),
    ]
    assert p.residual[(2003, "CS", CLAIMED_TWICE)] == 1


def test_snapshots_a_missing_month_apart_refuse_the_build():
    with pytest.raises(PitPlanError, match="missing"):
        plan([snap(0, [rec("PPP", CIK_A)]), snap(2, [rec("PPP", CIK_A)])])


def test_snapshots_out_of_order_refuse_the_build():
    with pytest.raises(PitPlanError, match="out of order"):
        plan([snap(1, [rec("QQQ", CIK_A)]), snap(0, [rec("QQQ", CIK_A)])])


def test_cik_keyed_records_of_one_cik_under_two_tickers_are_counted_ambiguous_but_placed():
    p = plan([snap(0, [rec("RRR", CIK_A), rec("RRR.B", CIK_A)])])
    assert p.ambiguous_cik_ticker == {2003: 2}
    assert {s.symbol for s in p.securities} == {"RRR", "RRR.B"}


def test_the_plan_is_deterministic():
    snaps = [
        snap(0, [rec("SSS", CIK_A), rec("TTT", cf=CF1, cik=CIK_B)]),
        snap(1, [rec("SSS", CIK_A)]),
    ]
    a, b = plan(snaps), plan(list(snaps))
    assert pins(a) == pins(b)
    assert a.spans == b.spans and a.identifiers == b.identifiers


def test_residual_report_totals_every_reason_by_year_and_type():
    p = plan([snap(0, [rec("UUU", CIK_A, typ="CS"), rec("VVV", typ="CS")])])
    (row,) = p.residual_report()
    assert row["year"] == 2003 and row["type"] == "CS" and row["total"] == 2
    assert row[NO_KEY] == 1 and row[PLACED] == 1


def _page(page, results, nxt, status="OK"):
    body = {"status": status, "results": results}
    if nxt:
        body["next_url"] = "u"
    return (page, f"id{page}", body)


def test_pages_are_read_in_order_and_a_partial_capture_refuses():
    ok = records_from_pages(
        M[0], "active", [_page(2, [{"ticker": "B"}], False), _page(1, [{"ticker": "A"}], True)]
    )
    assert [r.ticker for r in ok] == ["A", "B"]
    with pytest.raises(PitPlanError, match="1..N"):
        records_from_pages(M[0], "active", [_page(1, [], True), _page(3, [], False)])
    with pytest.raises(PitPlanError, match="status"):
        records_from_pages(M[0], "active", [_page(1, [], False, status="ERROR")])
    with pytest.raises(PitPlanError, match="next_url"):
        records_from_pages(M[0], "active", [_page(1, [], True)])
    with pytest.raises(PitPlanError, match="no pages"):
        records_from_pages(M[0], "active", [])


def test_a_stage2_instrument_a_rollback_left_behind_is_reused_so_a_reinstall_is_the_same_plan():
    snaps = [snap(0, [rec("LLL", CIK_A)]), snap(1, [rec("LLL", CIK_A)])]
    first = plan(snaps, LiveState(frozenset(), {}, ()))
    # after the install the instrument row exists; the rollback retired the identifiers and spans
    left = LiveState(frozenset({"LLL"}), {}, (), {(CIK_TICKER, f"{CIK_A}:LLL"): "LLL"})
    again = plan(snaps, left)
    assert pins(first) == pins(again)
    assert [s.symbol for s in again.securities] == ["LLL"]


def test_a_stage2_symbol_is_not_given_to_another_key():
    left = LiveState(frozenset({"LLL"}), {}, (), {(CIK_TICKER, f"{CIK_B}:LLL"): "LLL"})
    p = plan([snap(0, [rec("LLL", CIK_A)])], left)
    assert [s.symbol for s in p.securities] == ["LLL~1"]


def test_a_closed_run_of_a_ticker_an_instrument_with_no_span_holds_is_still_that_instrument():
    # ROKU left the vendor's active list at month 2; the instrument stays ours and has no span
    live = LiveState(frozenset({"ROKU"}), {}, (), {}, frozenset())
    p = plan([snap(0, [rec("ROKU", CIK_A)]), snap(1, [rec("ROKU", CIK_A)]), snap(2)], live)
    assert p.securities == () and p.spans == ()


def test_an_instrument_that_has_spans_does_not_claim_a_new_holders_run():
    # T is a dead stage 1 security with spans; a new holder of the string is a new security
    live = LiveState(frozenset({"TTT"}), {}, (), {}, frozenset({"TTT"}))
    p = plan([snap(0, [rec("TTT", CIK_B)]), snap(1, [rec("TTT", CIK_B)])], live)
    assert [s.symbol for s in p.securities] == ["TTT~2"]


def test_only_the_latest_holder_of_the_ticker_is_the_instrument():
    live = LiveState(frozenset({"XXX"}), {}, (), {}, frozenset())
    p = plan([
        snap(0, [rec("XXX", CIK_A)]),
        snap(1, [rec("XXX", CIK_A)]),
        snap(2, [rec("XXX", CIK_B)]),
        snap(3, [rec("XXX", CIK_B)]),
    ], live)  # fmt: skip
    assert [s.symbol for s in p.securities] == ["XXX~1"]  # the earlier holder, a dead security


def test_an_earlier_run_of_the_instruments_ticker_under_the_same_issuer_is_the_instrument_too():
    # the vendor's list skips a month: one listing becomes a CIK-keyed run and a FIGI-keyed run
    live = LiveState(frozenset({"BZH"}), {}, (), {}, frozenset())
    p = plan([
        snap(0, [rec("BZH", CIK_A)]),
        snap(1, [rec("BZH", CIK_A)]),
        snap(2),
        snap(3, [rec("BZH", cf=CF1, cik=CIK_A)]),
        snap(4, [rec("BZH", cf=CF1, cik=CIK_A)]),
    ], live)  # fmt: skip
    assert p.securities == ()


def test_an_earlier_run_of_the_ticker_under_another_issuer_stays_a_dead_security():
    live = LiveState(frozenset({"BZH"}), {}, (), {}, frozenset())
    p = plan([
        snap(0, [rec("BZH", CIK_B)]),
        snap(1, [rec("BZH", CIK_B)]),
        snap(2),
        snap(3, [rec("BZH", cf=CF1, cik=CIK_A)]),
    ], live)  # fmt: skip
    assert [s.symbol for s in p.securities] == ["BZH~2"]


def test_a_ticker_missing_one_month_end_between_two_observations_of_one_identity_is_bridged():
    p = plan([snap(0, [rec("BBB", CIK_A)]), snap(1), snap(2, [rec("BBB", CIK_A)]), snap(3)])
    assert [(s.start, s.end) for s in p.spans] == [(MASSIVE_ARCHIVE_START, M[3])]
    assert p.bridged_months == 1


def test_a_ticker_missing_two_month_ends_is_two_runs_with_no_span_over_the_gap():
    snaps = [snap(0, [rec("BBB", CIK_A)]), snap(1), snap(2), snap(3, [rec("BBB", CIK_A)]), snap(4)]
    p = plan(snaps)
    assert [(s.start, s.end) for s in p.spans] == [(MASSIVE_ARCHIVE_START, M[1]), (M[3], M[4])]
    assert p.bridged_months == 0


def test_a_missing_month_is_not_bridged_when_another_record_with_no_key_held_the_ticker():
    snaps = [snap(0, [rec("BBB", CIK_A)]), snap(1, [rec("BBB")]), snap(2, [rec("BBB", CIK_A)])]
    p = plan(snaps)
    assert p.bridged_months == 0 and len(p.spans) == 2


def test_a_missing_month_is_not_bridged_across_a_change_of_identity():
    snaps = [snap(0, [rec("BBB", CIK_A)]), snap(1), snap(2, [rec("BBB", CIK_B)]), snap(3)]
    p = plan(snaps)
    assert p.bridged_months == 0
    assert [(s.start, s.end) for s in sorted(p.spans, key=lambda s: s.start)] == [
        (MASSIVE_ARCHIVE_START, M[1]),
        (M[2], M[3]),
    ]


def test_a_run_replaced_by_another_holder_ends_the_day_after_its_last_month_end():
    snaps = [snap(0, [rec("BBB", CIK_A)]), snap(1, [rec("BBB", CIK_B)]), snap(2)]
    p = plan(snaps)
    first = min(p.spans, key=lambda s: s.start)
    assert (first.start, first.end) == (MASSIVE_ARCHIVE_START, date(2003, 10, 1))


def test_a_rename_of_a_name_with_no_composite_figi_is_counted_not_merged():
    snaps = [snap(0, [rec("OLD", CIK_A)]), snap(1, [rec("NEW", CIK_A)]), snap(2)]
    p = plan(snaps)
    assert len(p.securities) == 2
    assert p.cik_renames_split == 1


# ---------------------------------------------------------------------------------------------
# Placement rule P1: spans on an existing instrument that has none
# ---------------------------------------------------------------------------------------------


def p1_live(symbol="ACN", name="Accenture Plc-Cl A", figi=CF1, spans=()):
    return LiveState(
        frozenset({symbol}), {(COMPOSITE_FIGI, figi): symbol}, spans, {}, frozenset(),
        p1_symbols=frozenset({symbol}), names={symbol: name}, ciks={symbol: CIK_A},
    )  # fmt: skip


def test_p1_places_a_cik_keyed_run_on_the_instrument_when_the_name_overlaps():
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE PLC")]) for i in range(3)]
    p = plan([*snaps, snap(3)], p1_live())
    assert p.securities == () and p.identifiers == ()
    (span,) = p.spans
    assert (span.symbol, span.ticker) == ("ACN", "ACN")
    assert (span.start, span.end) == (MASSIVE_ARCHIVE_START, M[3])
    assert p.attached_figi == {"ACN": CF1}
    assert p.residual[(2003, "CS", PLACED)] == 3 and (2003, "CS", ALREADY_LIVE) not in p.residual
    assert '"placement":"P1"' in span.evidence


def test_p1_leaves_a_run_whose_name_does_not_overlap_the_instrument():
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="OTHER HOLDINGS")]) for i in range(2)]
    p = plan(snaps, p1_live())
    assert p.spans == () and p.attached_figi == {}
    assert p.residual[(2003, "CS", ALREADY_LIVE)] == 2


def test_p1_requires_a_run_composite_figi_to_equal_the_instruments():
    bad = [snap(i, [rec("A", CIK_A, cf=CF2, typ="CS", name="AGILENT")]) for i in range(2)]
    p = plan(bad, p1_live("A", "Agilent Technologies Inc"))
    assert p.spans == () and p.residual[(2003, "CS", ALREADY_LIVE)] == 2
    ok = [snap(i, [rec("A", CIK_A, cf=CF1, typ="CS", name="AGILENT")]) for i in range(2)]
    assert [s.symbol for s in plan(ok, p1_live("A", "Agilent Technologies Inc")).spans] == ["A"]


def test_p1_does_not_apply_to_an_instrument_off_the_gap_list():
    live = LiveState(
        frozenset({"ACN"}), {(COMPOSITE_FIGI, CF1): "ACN"}, (), {}, frozenset(),
        names={"ACN": "Accenture"},
    )  # fmt: skip
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")]) for i in range(2)]
    assert plan(snaps, live).spans == ()


def test_p1_needs_a_live_composite_figi_identifier_to_attach_to():
    live = LiveState(
        frozenset({"ACN"}), {}, (), {}, frozenset(),
        p1_symbols=frozenset({"ACN"}), names={"ACN": "Accenture"},
    )  # fmt: skip
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")]) for i in range(2)]
    p = plan(snaps, live)
    assert p.spans == () and p.residual[(2003, "CS", ALREADY_LIVE)] == 2


def test_p1_places_every_run_of_the_key_not_only_the_latest_and_not_a_renamed_ticker():
    def fiserv(ticker):
        return [rec(ticker, cf=CF1, cik=CIK_A, typ="CS", name="FISERV INC")]

    snaps = [snap(0, fiserv("FISV")), snap(1, fiserv("FISV")), snap(2), snap(3),
             snap(4, fiserv("FISV")), snap(5, fiserv("FI"))]  # fmt: skip
    p = plan(snaps, p1_live("FISV", "Fiserv Inc"))
    assert [(s.symbol, s.ticker) for s in p.spans] == [("FISV", "FISV"), ("FISV", "FISV")]
    assert p.residual[(2004, "CS", ALREADY_LIVE)] == 1  # the FI month is left alone


def test_p1_places_the_run_minus_a_live_span_of_the_ticker():
    live = p1_live(spans=(("ACN", date(2003, 10, 15), date(2003, 11, 15)),))
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")]) for i in range(4)]
    p = plan(snaps, live)
    assert [(s.start, s.end) for s in p.spans] == [
        (MASSIVE_ARCHIVE_START, date(2003, 10, 15)),
        (date(2003, 11, 15), None),
    ]


def test_spanless_holds_equity_instruments_only_so_a_futures_ticker_gets_a_new_security():
    live = LiveState(
        frozenset({"ES"}), {}, (), {}, frozenset(), non_equity_symbols=frozenset({"ES"})
    )  # fmt: skip
    p = plan([snap(0, [rec("ES", CIK_A, typ="CS")]), snap(1, [rec("ES", CIK_A, typ="CS")])], live)
    assert [s.symbol for s in p.securities] == ["ES~1"]
    assert [s.symbol for s in p.spans] == ["ES~1"]


def test_p1_is_deterministic():
    snaps = [snap(i, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE PLC")]) for i in range(3)]
    assert pins(plan(snaps, p1_live())) == pins(plan(snaps, p1_live()))


def test_p1_serves_an_instrument_that_holds_spans_for_earlier_years():
    live = LiveState(
        frozenset({"ARES"}), {(COMPOSITE_FIGI, CF1): "ARES"},
        (("ARES", MASSIVE_ARCHIVE_START, M[1]),), {}, frozenset({"ARES"}),
        p1_symbols=frozenset({"ARES"}), names={"ARES": "Ares Management Corp - A"},
    )  # fmt: skip
    snaps = [
        snap(i, [rec("ARES", CIK_A, cf=CF1, typ="CS", name="ARES MANAGEMENT")]) for i in range(4)
    ]
    p = plan(snaps, live)
    assert [(s.symbol, s.start, s.end) for s in p.spans] == [("ARES", M[1], None)]


def test_p1_places_only_the_instruments_own_runs_when_another_issuer_held_the_ticker_between():
    snaps = [
        snap(0, [rec("XYZ", CIK_A, cf=CF1, typ="CS", name="XYZ")]),
        snap(1, [rec("XYZ", CIK_B, typ="CS", name="OTHER")]),
        snap(2, [rec("XYZ", CIK_A, cf=CF1, typ="CS", name="XYZ")]),
        snap(3, [rec("XYZ", CIK_A, cf=CF1, typ="CS", name="XYZ")]),
    ]
    p = plan(snaps, p1_live("XYZ", "XYZ Inc"))
    assert [s.start for s in p.spans if s.symbol == "XYZ"] == [MASSIVE_ARCHIVE_START, M[2]]
    assert [s.symbol for s in p.spans if s.symbol != "XYZ"] == ["XYZ~2"]


def test_p1_places_nothing_when_another_issuer_holds_the_ticker_last():
    snaps = [
        snap(0, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")]),
        snap(1, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")]),
        snap(2),
        snap(3, [rec("ACN", CIK_B, typ="CS", name="ACCENTURE ENERGY")]),
    ]
    p = plan(snaps, p1_live())
    assert [s.symbol for s in p.spans if s.symbol == "ACN"] == []


def test_a_figi_less_run_must_carry_the_cik_of_the_instruments_overview():
    live = p1_live("FAC", "First Alpha Capital")
    other = [snap(i, [rec("FAC", CIK_B, typ="CS", name="FIRST ALPHA CAPITAL")]) for i in range(2)]
    assert plan(other, live).spans == ()
    own = [snap(i, [rec("FAC", CIK_A, typ="CS", name="FIRST ALPHA CAPITAL")]) for i in range(2)]
    assert [s.symbol for s in plan(own, live).spans] == ["FAC"]
    no_cik = LiveState(
        live.symbols, live.identifiers, (), {}, frozenset(),
        p1_symbols=live.p1_symbols, names=live.names,
    )  # fmt: skip
    assert plan(own, no_cik).spans == ()


def test_two_live_composite_figis_on_one_symbol_refuse_the_plan():
    live = LiveState(
        frozenset({"ACN"}), {(COMPOSITE_FIGI, CF1): "ACN", (COMPOSITE_FIGI, CF2): "ACN"}, (), {},
        frozenset(), p1_symbols=frozenset({"ACN"}), names={"ACN": "Accenture"},
    )  # fmt: skip
    with pytest.raises(PitPlanError, match="two live composite FIGIs"):
        plan([snap(0, [rec("ACN", CIK_A, typ="CS", name="ACCENTURE")])], live)
