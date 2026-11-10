"""Span edge presence and the per-session ticker map (AGCO is served as AGCO before its event)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.intelligence.bars.massive_symbol_map import (
    REASON_BOTH_ABSENT,
    REASON_FIRST_ABSENT,
    REASON_LAST_ABSENT,
    REASON_NO_SESSIONS,
    TickerSpan,
    judge_span,
    tickers_on,
    unaccounted_instruments,
)

DAYS = [date(2008, 1, 1) + timedelta(days=i) for i in range(0, 40)]


def _span(ticker, start, end, symbol="AGCO", event="e1"):
    return TickerSpan(event, symbol, ticker, start, end)


def _present(table):
    return lambda day: table.get(day, frozenset())


def test_a_span_whose_string_is_served_at_both_edges_loads_and_counts_the_window():
    span = _span("AG", DAYS[0], DAYS[20])
    served = {d: {"AG"} for d in DAYS[:20] if d != DAYS[5]}
    verdict = judge_span(span, DAYS, _present(served), window=(DAYS[0], DAYS[9]))
    assert verdict.loadable
    assert (verdict.first_session, verdict.last_session) == (DAYS[0], DAYS[19])
    assert (verdict.n_window_sessions, verdict.n_window_present) == (10, 9)


def test_a_chain_that_lags_the_served_string_fails_its_first_edge():
    # the chain says AG from the first session; the files still serve AGCO until day 10
    span = _span("AG", DAYS[0], DAYS[20])
    served = {d: {"AGCO"} for d in DAYS[:10]} | {d: {"AG"} for d in DAYS[10:20]}
    verdict = judge_span(span, DAYS, _present(served))
    assert verdict.reason == REASON_FIRST_ABSENT and not verdict.loadable


def test_last_and_both_edges():
    span = _span("AG", DAYS[0], DAYS[20])
    assert judge_span(span, DAYS, _present({DAYS[0]: {"AG"}})).reason == REASON_LAST_ABSENT
    assert judge_span(span, DAYS, _present({})).reason == REASON_BOTH_ABSENT


def test_open_ended_span_uses_the_last_archive_session():
    span = _span("AGCO", DAYS[20], None)
    served = {DAYS[20]: {"AGCO"}, DAYS[-1]: {"AGCO"}}
    verdict = judge_span(span, DAYS, _present(served))
    assert verdict.loadable and verdict.last_session == DAYS[-1]


def test_a_span_with_no_archive_session_is_reported():
    span = _span("AG", date(1990, 1, 1), date(1990, 2, 1))
    assert judge_span(span, DAYS, _present({})).reason == REASON_NO_SESSIONS


def test_session_map_uses_only_the_spans_it_is_given_and_never_a_different_string():
    ag = _span("AG", DAYS[0], DAYS[20], event="e1")
    agco = _span("AGCO", DAYS[20], None, event="e2")
    assert tickers_on([ag, agco], DAYS[3]) == {"AG": ag}
    assert tickers_on([ag, agco], DAYS[25]) == {"AGCO": agco}
    assert tickers_on([agco], DAYS[3]) == {}  # AG failed its edge and is not passed: no mapping


def test_two_spans_for_one_string_on_a_day_is_a_tripwire():
    a, b = _span("X", DAYS[0], None, "A", "e1"), _span("X", DAYS[0], None, "B", "e2")
    with pytest.raises(ValueError, match="two instruments"):
        tickers_on([a, b], DAYS[1])


def test_instruments_with_neither_span_nor_gap_row_are_listed():
    spans = [_span("AAPL", DAYS[0], None, "AAPL")]
    assert unaccounted_instruments(["AAPL", "BRK.B", "ZZZ"], spans, {"BRK.B"}) == ["ZZZ"]
