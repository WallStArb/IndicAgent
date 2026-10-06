"""D6 listing venue (phase 185 plan 24, D-25): the pure inference and reconciliation.

No database: inventory rows arrive as data. services/listing_venue_writer.py only loads
them, runs these functions and writes the result.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.listing_venue_writer import (
    RangeScore,
    SpanPlan,
    infer_listing_spans,
    reconcile_spans,
    score_range,
)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _bars(start: date, end: date, close: float, volume: float) -> dict[date, tuple[float, float]]:
    return dict.fromkeys(_days(start, end), (close, volume))


NO_OFFICIAL: dict[date, float] = {}


class TestInferListingSpans:
    def test_moved_name_gets_closed_former_span_and_open_current_span(self):
        first = date(2009, 1, 2)
        head = date(2015, 1, 2)
        spans = infer_listing_spans(
            first,
            head,
            [("NYSE", first, date(2014, 12, 30))],
            "NASDAQ",
            venue_bars={"NYSE": _bars(first, date(2014, 12, 30), 10.0, 1000.0)},
            official_close=NO_OFFICIAL,
        )
        assert spans == [("NYSE", first, head), ("NASDAQ", head, None)]

    def test_island_route_is_stored_as_the_nasdaq_listing(self):
        first = date(2009, 1, 2)
        head = date(2015, 1, 2)
        spans = infer_listing_spans(
            first,
            head,
            [("ISLAND", first, date(2014, 12, 30))],
            "NYSE",
            venue_bars={"ISLAND": _bars(first, date(2014, 12, 30), 10.0, 1.0)},
            official_close=NO_OFFICIAL,
        )
        assert spans == [("NASDAQ", first, head), ("NYSE", head, None)]

    def test_unmoved_name_gets_one_open_span_from_its_first_bar(self):
        first = date(2006, 1, 3)
        spans = infer_listing_spans(
            first, first, [], "NYSE", venue_bars={}, official_close=NO_OFFICIAL
        )
        assert spans == [("NYSE", first, None)]

    def test_no_smart_head_and_no_venue_spans_is_one_open_span(self):
        first = date(2000, 1, 3)
        spans = infer_listing_spans(first, None, [], "ARCA", venue_bars={}, official_close={})
        assert spans == [("ARCA", first, None)]

    def test_no_current_primary_and_no_history_yields_nothing(self):
        assert (
            infer_listing_spans(date(2000, 1, 3), None, [], None, venue_bars={}, official_close={})
            == []
        )

    def test_venue_spans_after_the_smart_head_are_not_former_listings(self):
        # A venue answering concurrently with SMART (the venue study's recent windows)
        # says nothing about a former listing.
        first = date(2006, 1, 3)
        spans = infer_listing_spans(
            first,
            first,
            [("ARCA", date(2026, 1, 2), date(2026, 3, 31))],
            "NYSE",
            venue_bars={"ARCA": _bars(date(2026, 1, 2), date(2026, 3, 31), 10.0, 5.0)},
            official_close=NO_OFFICIAL,
        )
        assert spans == [("NYSE", first, None)]

    def test_without_official_closes_overlapping_spans_go_to_max_volume(self):
        # TLT shape: NYSE and AMEX early, ARCA throughout, BATS from 2010.
        first = date(2006, 2, 6)
        head = date(2016, 2, 3)
        early_end = date(2007, 8, 16)
        venue_spans = [
            ("NYSE", first, early_end),
            ("AMEX", first, early_end),
            ("ARCA", first, date(2016, 2, 1)),
            ("BATS", date(2010, 6, 22), date(2016, 2, 1)),
        ]
        bars = {
            "NYSE": _bars(first, early_end, 10.0, 900.0),  # NYSE leads while it trades
            "AMEX": _bars(first, early_end, 10.0, 100.0),
            "ARCA": _bars(first, date(2016, 2, 1), 10.0, 500.0),
            "BATS": _bars(date(2010, 6, 22), date(2016, 2, 1), 10.0, 400.0),
        }
        spans = infer_listing_spans(
            first, head, venue_spans, "NASDAQ", venue_bars=bars, official_close=NO_OFFICIAL
        )
        assert spans == [
            ("NYSE", first, early_end + timedelta(days=1)),
            ("ARCA", early_end + timedelta(days=1), head),
            ("NASDAQ", head, None),
        ]
        # Never overlapping, contiguous from the first bar.
        for (_, _, end), (_, start, _) in zip(spans, spans[1:], strict=False):
            assert end == start

    def test_nearest_official_close_beats_volume(self):
        # AMD shape: BATS prints more venue volume, but NYSE's close is the official close
        # (the listing venue runs the closing auction).
        first = date(2008, 10, 17)
        last = date(2008, 12, 31)
        head = date(2009, 1, 2)
        official = {d: 10.0 + 0.01 * i for i, d in enumerate(_days(first, last))}
        nyse = {d: (c, 100.0) for d, c in official.items()}
        bats = {
            d: (c + 0.02 * (1 if i % 2 else -1), 900.0) for i, (d, c) in enumerate(official.items())
        }
        spans = infer_listing_spans(
            first,
            head,
            [("NYSE", first, last), ("BATS", first, last)],
            "NASDAQ",
            venue_bars={"NYSE": nyse, "BATS": bats},
            official_close=official,
        )
        assert spans == [("NYSE", first, head), ("NASDAQ", head, None)]

    def test_a_venue_on_another_split_scale_still_compares(self):
        first = date(2006, 1, 3)
        last = date(2006, 3, 31)
        head = date(2006, 4, 3)
        official = {d: 30.0 + 0.1 * i for i, d in enumerate(_days(first, last))}
        # AMEX stored on a 3:1 scale but its closes track the official close exactly.
        amex = {d: (c / 3.0, 1.0) for d, c in official.items()}
        arca = {
            d: (c * (1.001 if i % 2 else 0.999), 50.0) for i, (d, c) in enumerate(official.items())
        }
        spans = infer_listing_spans(
            first,
            head,
            [("AMEX", first, last), ("ARCA", first, last)],
            "NASDAQ",
            venue_bars={"AMEX": amex, "ARCA": arca},
            official_close=official,
        )
        assert spans[0] == ("AMEX", first, head)

    def test_adjacent_ranges_won_by_the_same_venue_merge(self):
        first = date(2006, 1, 3)
        head = date(2012, 1, 3)
        venue_spans = [
            ("NYSE", first, date(2011, 12, 29)),
            ("BATS", date(2008, 10, 17), date(2011, 12, 29)),
        ]
        bars = {
            "NYSE": _bars(first, date(2011, 12, 29), 10.0, 1000.0),
            "BATS": _bars(date(2008, 10, 17), date(2011, 12, 29), 10.0, 10.0),
        }
        spans = infer_listing_spans(
            first, head, venue_spans, "NASDAQ", venue_bars=bars, official_close=NO_OFFICIAL
        )
        assert spans == [("NYSE", first, head), ("NASDAQ", head, None)]

    def test_history_earlier_than_venue_evidence_extends_the_first_former_span(self):
        # Tradier holds bars before IBKR's venue window: the first former venue covers them.
        first = date(2000, 1, 3)
        head = date(2015, 1, 2)
        spans = infer_listing_spans(
            first,
            head,
            [("NYSE", date(2006, 1, 3), date(2014, 12, 30))],
            "NASDAQ",
            venue_bars={"NYSE": _bars(date(2006, 1, 3), date(2014, 12, 30), 10.0, 1.0)},
            official_close=NO_OFFICIAL,
        )
        assert spans == [("NYSE", first, head), ("NASDAQ", head, None)]

    def test_full_tie_breaks_deterministically_by_venue_name(self):
        first = date(2013, 9, 11)
        head = date(2013, 9, 30)
        last = date(2013, 9, 26)
        venue_spans = [("BATS", first, last), ("ARCA", first, last)]
        bars = {"BATS": _bars(first, last, 10.0, 1.0), "ARCA": _bars(first, last, 10.0, 1.0)}
        official = dict.fromkeys(_days(first, last), 10.0)
        spans = infer_listing_spans(
            first, head, venue_spans, "NYSE", venue_bars=bars, official_close=official
        )
        assert spans[0][0] == "ARCA"

    def test_former_venue_equal_to_current_primary_is_one_open_span(self):
        # The SMART head restarted without a visible venue change: no closed span is
        # invented; D7's coverage check reports the moved name.
        first = date(2006, 1, 3)
        head = date(2010, 1, 4)
        spans = infer_listing_spans(
            first,
            head,
            [("NYSE", first, date(2009, 12, 31))],
            "NYSE",
            venue_bars={"NYSE": _bars(first, date(2009, 12, 31), 10.0, 1.0)},
            official_close=NO_OFFICIAL,
        )
        assert spans == [("NYSE", first, None)]


class TestScoreRange:
    def test_ties_split_the_win_and_a_route_alone_wins_its_day(self):
        d0, d1 = date(2010, 1, 4), date(2010, 1, 5)
        scores = score_range(
            ["ARCA", "NYSE"],
            d0,
            d1 + timedelta(days=1),
            {"ARCA": {d0: (10.0, 5.0), d1: (10.0, 5.0)}, "NYSE": {d0: (10.0, 7.0)}},
            {d0: 10.0, d1: 10.0},
        )
        assert scores["ARCA"] == RangeScore(1.5, 2, 10.0)
        assert scores["NYSE"] == RangeScore(0.5, 2, 7.0)


class TestReconcileSpans:
    FIRST = date(2006, 1, 3)
    HEAD = date(2015, 1, 2)

    def test_nothing_stored_inserts_everything(self):
        desired = [("NYSE", self.FIRST, self.HEAD), ("NASDAQ", self.HEAD, None)]
        assert reconcile_spans([], desired) == SpanPlan(None, tuple(desired), None)

    def test_identical_spans_are_skipped(self):
        desired = [("NYSE", self.FIRST, self.HEAD), ("NASDAQ", self.HEAD, None)]
        plan = reconcile_spans(desired, desired)
        assert plan == SpanPlan(None, (), None)
        assert plan.is_noop

    def test_a_new_move_closes_the_open_span_then_inserts(self):
        later = date(2026, 10, 1)
        existing = [("NYSE", self.FIRST, None)]
        desired = [("NYSE", self.FIRST, later), ("NASDAQ", later, None)]
        plan = reconcile_spans(existing, desired)
        assert plan.close == (self.FIRST, later)
        assert plan.insert == (("NASDAQ", later, None),)
        assert plan.conflict is None

    def test_a_changed_history_is_a_conflict_never_a_rewrite(self):
        existing = [("NYSE", self.FIRST, None)]
        desired = [("ARCA", self.FIRST, None)]
        plan = reconcile_spans(existing, desired)
        assert plan.conflict is not None
        assert plan.close is None and plan.insert == ()

    def test_a_closed_span_that_differs_is_a_conflict(self):
        existing = [("NYSE", self.FIRST, self.HEAD), ("NASDAQ", self.HEAD, None)]
        desired = [("NYSE", self.FIRST, date(2015, 1, 5)), ("NASDAQ", date(2015, 1, 5), None)]
        assert reconcile_spans(existing, desired).conflict is not None

    def test_stored_spans_but_nothing_inferred_is_a_conflict(self):
        assert reconcile_spans([("NYSE", self.FIRST, None)], []).conflict is not None

    @pytest.mark.parametrize("desired", [[], [("NYSE", date(2006, 1, 3), None)]])
    def test_plan_is_a_noop_only_when_it_writes_nothing(self, desired):
        plan = reconcile_spans(desired, desired)
        assert plan.is_noop
