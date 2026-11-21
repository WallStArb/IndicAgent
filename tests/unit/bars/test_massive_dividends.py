"""Massive dividends: page parsing, point-in-time mapping, collapse and the coverage rule (pure)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from src.intelligence.bars import massive_dividends as md

CAP = date(2026, 11, 10)


def _rec(
    rid, ticker, ex, amount=0.5, currency="USD", declared=None, page=1, kind="recurring", pay=None
):
    return md.DividendRecord(rid, ticker, ex, amount, currency, kind, declared, page, pay)


def _quarterly(start: date, n: int, step: int = 91) -> list[date]:
    return [start + timedelta(days=step * i) for i in range(n)]


SPAN = [md.TickerSpan("te", "ACME", "ACME", date(2003, 9, 10), None)]


# --- parse_page -----------------------------------------------------------------------------


def test_parse_page_reads_the_fields_and_keeps_a_missing_declaration_as_none():
    body = {
        "status": "OK",
        "results": [
            {
                "id": "E1",
                "ticker": "ACME",
                "ex_dividend_date": "2010-03-01",
                "cash_amount": 0.25,
                "currency": "USD",
                "distribution_type": "recurring",
                "declaration_date": "2010-02-01",
            },
            {"id": "E2", "ticker": "ACME", "ex_dividend_date": "2010-06-01", "cash_amount": 1},
        ],
    }
    a, b = md.parse_page(body, 7)
    assert (a.ex_date, a.cash_amount, a.declared_on, a.page) == (
        date(2010, 3, 1),
        0.25,
        date(2010, 2, 1),
        7,
    )
    assert b.declared_on is None and b.currency is None and b.cash_amount == 1.0


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ERROR", "results": []},
        {"status": "OK"},
        {"status": "OK", "results": [{"ticker": "A", "ex_dividend_date": "2010-01-01"}]},
        {"status": "OK", "results": [{"id": "E", "ticker": "A", "ex_dividend_date": "2010-13-01"}]},
    ],
)
def test_parse_page_refuses_a_malformed_page_or_record(body):
    with pytest.raises(ValueError):
        md.parse_page(body, 1)


# --- mapping --------------------------------------------------------------------------------


def test_a_reused_ticker_maps_each_record_to_the_company_holding_it_on_the_ex_date():
    spans = md.SpanIndex(
        [
            md.TickerSpan("te", "DD~OLD", "DD", date(2003, 9, 10), date(2017, 9, 5)),
            md.TickerSpan("te", "DD", "DD", date(2026, 6, 24), None),
        ]
    )
    assert spans.symbol_of("DD", date(2010, 1, 1)) == "DD~OLD"
    assert spans.symbol_of("DD", date(2017, 9, 5)) is None  # valid_to is exclusive
    assert spans.symbol_of("DD", date(2020, 1, 1)) is None  # between the two companies
    assert spans.symbol_of("DD", date(2026, 8, 31)) == "DD"
    assert spans.symbol_of("DD", date(2003, 1, 1)) is None
    assert spans.symbol_of("XX", date(2010, 1, 1)) is None


def test_overlapping_spans_of_one_ticker_are_refused():
    with pytest.raises(ValueError):
        md.SpanIndex(
            [
                md.TickerSpan("te", "A", "T", date(2010, 1, 1), date(2012, 1, 1)),
                md.TickerSpan("te", "B", "T", date(2011, 1, 1), None),
            ]
        )


# --- collapse_events ------------------------------------------------------------------------


def _collapse(records, spans=SPAN):
    return md.collapse_events(records, md.SpanIndex(spans), CAP)


def test_exact_repeats_collapse_and_distinct_amounts_sum():
    d = date(2010, 3, 1)
    out = _collapse(
        [
            _rec("E1", "ACME", d, 0.25, page=2),
            _rec("E2", "ACME", d, 0.25, page=1),  # the same dividend under a second id
            _rec("E3", "ACME", d, 1.00, page=2),  # a special on the same ex-date
        ]
    )
    (event,) = out.events["ACME"]
    assert event.amount == pytest.approx(1.25)
    assert event.record_ids == ("E1", "E2", "E3") and event.pages == (1, 2)


def test_one_dividend_restated_with_a_close_amount_drops_its_date():
    d = date(2007, 9, 28)
    out = _collapse(
        [
            _rec("E1", "ACME", d, 0.10693, pay="2007-10-15"),
            _rec("E2", "ACME", d, 0.10785, pay="2007-10-15"),
        ]
    )
    assert "ACME" not in out.events and out.dropped_dates["ACME"] == {d}
    assert out.drops[md.DROP_CONFLICTING] == 2


def test_the_same_amount_paid_on_two_dates_drops_its_date():
    d = date(2024, 12, 23)
    out = _collapse(
        [
            _rec("E1", "ACME", d, 0.089, pay="2024-12-31"),
            _rec("E2", "ACME", d, 0.089, pay="2025-01-31"),
        ]
    )
    assert "ACME" not in out.events and out.drops[md.DROP_CONFLICTING] == 2


@pytest.mark.parametrize(
    "second",
    [
        {"amount": 0.26, "kind": "special", "pay": "2010-03-15"},  # another type
        {"amount": 0.26, "pay": "2010-04-15"},  # another pay date
        {"amount": 1.00, "pay": "2010-03-15"},  # far apart
    ],
)
def test_two_distinct_payments_on_one_ex_date_sum(second):
    d = date(2010, 3, 1)
    recs = [_rec("E1", "ACME", d, 0.25, pay="2010-03-15"), _rec("E2", "ACME", d, **second)]
    (event,) = _collapse(recs).events["ACME"]
    assert event.amount == pytest.approx(0.25 + second["amount"])


def test_a_non_usd_record_drops_its_whole_date_and_counts_every_record():
    d = date(2010, 3, 1)
    out = _collapse([_rec("E1", "ACME", d, 0.25), _rec("E2", "ACME", d, 0.3, currency="CAD")])
    assert "ACME" not in out.events
    assert out.dropped_dates["ACME"] == {d} and out.reported_dates["ACME"] == {d}
    assert out.drops[md.DROP_NON_USD] == 2


@pytest.mark.parametrize("amount", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_a_record_without_a_positive_finite_amount_drops_its_date(amount):
    out = _collapse([_rec("E1", "ACME", date(2010, 3, 1), amount)])
    assert out.drops[md.DROP_BAD_AMOUNT] == 1 and out.dropped_dates["ACME"] == {date(2010, 3, 1)}


def test_records_after_the_capture_date_and_unmapped_records_are_counted_not_kept():
    out = _collapse(
        [
            _rec("E1", "ACME", CAP),
            _rec("E2", "ACME", CAP + timedelta(days=1)),
            _rec("E3", "NOPE", date(2010, 1, 1)),
        ]
    )
    assert [e.ex_date for e in out.events["ACME"]] == [CAP]
    assert out.drops == {md.DROP_AFTER_CAPTURE: 1, md.DROP_UNMAPPED: 1}


def test_the_earliest_declaration_is_kept():
    d = date(2010, 3, 1)
    out = _collapse(
        [
            _rec("E1", "ACME", d, 0.25, declared=date(2010, 2, 10)),
            _rec("E2", "ACME", d, 0.50, declared=date(2010, 2, 1)),
            _rec("E3", "ACME", d, 0.75),
        ]
    )
    assert out.events["ACME"][0].declared_on == date(2010, 2, 1)


def test_collapse_does_not_depend_on_record_order():
    recs = [
        _rec(f"E{i}", "ACME", d, 0.1 * (i % 3 + 1))
        for i, d in enumerate(_quarterly(date(2005, 1, 3), 12))
    ]
    recs += [_rec("X", "ACME", date(2005, 1, 3), 0.3)]
    a = _collapse(recs)
    shuffled = recs[:]
    random.Random(1).shuffle(shuffled)
    b = _collapse(shuffled)
    assert a.events == b.events and a.reported_dates == b.reported_dates


# --- coverage -------------------------------------------------------------------------------


def test_no_events_no_claim():
    assert md.coverage([], [], SPAN, CAP) is None


def test_the_claim_starts_at_the_first_event_and_the_tail_stops_short_of_the_next_payment():
    days = _quarterly(date(2005, 1, 3), 8)
    claim = md.coverage(days, [], SPAN, CAP)
    assert claim.covered_from == days[0]
    assert claim.covered_to == days[-1] + timedelta(days=int(md.RULE.tail_intervals * 91))
    assert not claim.covers(days[0] - timedelta(days=1))
    assert not claim.covers(days[-1] + timedelta(days=91))  # the next expected payment
    assert claim.holes == ()


def test_one_missed_payment_is_a_hole_and_regular_gaps_are_not():
    days = _quarterly(date(2005, 1, 3), 12)
    missing = days.pop(6)
    claim = md.coverage(days, [], SPAN, CAP)
    assert not claim.covers(missing)
    (hole,) = claim.holes
    assert (hole.gap_from, hole.gap_to) == (
        days[5] + timedelta(days=1),
        days[6] - timedelta(days=1),
    )
    assert hole.reasons == (md.GAP_CADENCE,)
    assert claim.covers(days[2] + timedelta(days=30))


def test_a_monthly_payer_missing_one_month_gets_a_hole():
    days = _quarterly(date(2010, 1, 15), 24, step=30)
    missing = days.pop(10)
    claim = md.coverage(days, [], SPAN, CAP)
    assert not claim.covers(missing)


def test_a_single_event_claims_only_its_own_day():
    d = date(2010, 3, 1)
    claim = md.coverage([d], [], SPAN, CAP)
    assert (claim.covered_from, claim.covered_to, claim.holes) == (d, d, ())


def test_the_tail_is_capped_by_the_capture_date_the_span_end_and_the_day_cap():
    days = _quarterly(CAP - timedelta(days=91 * 4 + 30), 5)  # last ex-date 30 days before
    assert md.coverage(days, [], SPAN, CAP).covered_to == CAP
    ended = [md.TickerSpan("te", "ACME", "ACME", date(2003, 9, 10), days[-1] + timedelta(days=10))]
    assert md.coverage(days, [], ended, CAP).covered_to == days[-1] + timedelta(days=9)
    annual = _quarterly(date(2005, 6, 1), 4, step=730)  # biennial: 0.75 * 730 > the cap
    rule = md.CoverageRule(tail_intervals=0.75, tail_cap_days=400, gap_intervals=1.5)
    assert md.coverage(annual, [], SPAN, CAP, rule).covered_to == annual[-1] + timedelta(days=400)


def test_days_between_ticker_spans_and_dropped_dates_are_holes():
    days = _quarterly(date(2005, 1, 3), 12)
    spans = [
        md.TickerSpan("te", "ACME", "OLD", date(2003, 9, 10), date(2006, 1, 1)),
        md.TickerSpan("te", "ACME", "NEW", date(2006, 1, 20), None),
    ]
    dropped = days[9]
    claim = md.coverage(days, [dropped], spans, CAP)
    assert not claim.covers(date(2006, 1, 10)) and not claim.covers(dropped)
    assert claim.covers(dropped + timedelta(days=1))
    reasons = {h.reasons for h in claim.holes}
    assert reasons == {(md.GAP_SPAN,), (md.GAP_DROPPED,)}


def test_overlapping_holes_merge_and_keep_every_reason():
    days = _quarterly(date(2005, 1, 3), 12)
    a, b = days[4], days[7]
    gap_days = [d for d in days if not a < d < b]
    claim = md.coverage(gap_days, [a + timedelta(days=100)], SPAN, CAP)
    (hole,) = claim.holes
    assert hole.reasons == (md.GAP_CADENCE, md.GAP_DROPPED)


def test_overlapping_spans_of_one_symbol_are_refused():
    spans = [
        md.TickerSpan("te", "ACME", "A", date(2003, 9, 10), None),
        md.TickerSpan("te", "ACME", "B", date(2010, 1, 1), None),
    ]
    with pytest.raises(ValueError):
        md.coverage([date(2011, 1, 1), date(2011, 4, 1)], [], spans, CAP)


def test_an_ex_date_after_the_capture_is_refused():
    with pytest.raises(ValueError):
        md.coverage([CAP + timedelta(days=1)], [], SPAN, CAP)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tail_intervals": 1.0},  # would reach the next expected payment
        {"tail_intervals": -0.1},
        {"gap_intervals": 2.0},  # one missed payment would not be a hole
        {"gap_intervals": 1.0},
        {"tail_cap_days": -1},
    ],
)
def test_the_rule_refuses_constants_that_break_its_guarantees(kwargs):
    with pytest.raises(ValueError):
        md.CoverageRule(**kwargs)


def test_payment_interval_is_the_median_distinct_gap():
    assert md.payment_interval([date(2010, 1, 1)]) is None
    days = [
        date(2010, 1, 1),
        date(2010, 1, 1),
        date(2010, 4, 1),
        date(2010, 7, 1),
        date(2011, 7, 1),
    ]
    assert md.payment_interval(days) == 91.0
