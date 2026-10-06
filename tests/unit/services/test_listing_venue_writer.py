"""D6 listing venue (phase 185 plan 24, D-25): the pure inference and reconciliation.

No database: inventory rows arrive as data. services/listing_venue_writer.py only loads
them, runs these functions and writes the result.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.listing_venue_writer import (
    SpanPlan,
    infer_listing_spans,
    reconcile_spans,
)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _volume(start: date, end: date, per_day: float) -> dict[date, float]:
    return dict.fromkeys(_days(start, end), per_day)


class TestInferListingSpans:
    def test_moved_name_gets_closed_former_span_and_open_current_span(self):
        first = date(2009, 1, 2)
        head = date(2015, 1, 2)
        spans = infer_listing_spans(
            first,
            head,
            [("NYSE", first, date(2014, 12, 30))],
            "NASDAQ",
            venue_volume={"NYSE": _volume(first, date(2014, 12, 30), 1000.0)},
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
            venue_volume={"ISLAND": _volume(first, date(2014, 12, 30), 1.0)},
        )
        assert spans == [("NASDAQ", first, head), ("NYSE", head, None)]

    def test_unmoved_name_gets_one_open_span_from_its_first_bar(self):
        first = date(2006, 1, 3)
        assert infer_listing_spans(first, first, [], "NYSE", venue_volume={}) == [
            ("NYSE", first, None)
        ]

    def test_no_smart_head_and_no_venue_spans_is_one_open_span(self):
        first = date(2000, 1, 3)
        assert infer_listing_spans(first, None, [], "ARCA", venue_volume={}) == [
            ("ARCA", first, None)
        ]

    def test_no_current_primary_and_no_history_yields_nothing(self):
        assert infer_listing_spans(date(2000, 1, 3), None, [], None, venue_volume={}) == []

    def test_venue_spans_after_the_smart_head_are_not_former_listings(self):
        # A venue answering concurrently with SMART (the venue study's recent windows)
        # says nothing about a former listing.
        first = date(2006, 1, 3)
        spans = infer_listing_spans(
            first,
            first,
            [("ARCA", date(2026, 1, 2), date(2026, 3, 31))],
            "NYSE",
            venue_volume={"ARCA": _volume(date(2026, 1, 2), date(2026, 3, 31), 5.0)},
        )
        assert spans == [("NYSE", first, None)]

    def test_overlapping_spans_resolve_to_the_max_volume_venue_per_range(self):
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
        volume = {
            "NYSE": _volume(first, early_end, 900.0),  # NYSE leads while it trades
            "AMEX": _volume(first, early_end, 100.0),
            "ARCA": _volume(first, date(2016, 2, 1), 500.0),
            "BATS": _volume(date(2010, 6, 22), date(2016, 2, 1), 400.0),
        }
        spans = infer_listing_spans(first, head, venue_spans, "NASDAQ", venue_volume=volume)
        assert spans == [
            ("NYSE", first, early_end + timedelta(days=1)),
            ("ARCA", early_end + timedelta(days=1), head),
            ("NASDAQ", head, None),
        ]
        # Never overlapping, contiguous from the first bar.
        for (_, _, end), (_, start, _) in zip(spans, spans[1:], strict=False):
            assert end == start

    def test_adjacent_ranges_won_by_the_same_venue_merge(self):
        first = date(2006, 1, 3)
        head = date(2012, 1, 3)
        venue_spans = [
            ("NYSE", first, date(2011, 12, 29)),
            ("BATS", date(2008, 10, 17), date(2011, 12, 29)),
        ]
        volume = {
            "NYSE": _volume(first, date(2011, 12, 29), 1000.0),
            "BATS": _volume(date(2008, 10, 17), date(2011, 12, 29), 10.0),
        }
        spans = infer_listing_spans(first, head, venue_spans, "NASDAQ", venue_volume=volume)
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
            venue_volume={"NYSE": _volume(date(2006, 1, 3), date(2014, 12, 30), 1.0)},
        )
        assert spans == [("NYSE", first, head), ("NASDAQ", head, None)]

    def test_volume_tie_breaks_deterministically_by_venue_name(self):
        first = date(2013, 9, 11)
        head = date(2013, 9, 30)
        last = date(2013, 9, 26)
        venue_spans = [("BATS", first, last), ("ARCA", first, last)]
        volume = {"BATS": _volume(first, last, 1.0), "ARCA": _volume(first, last, 1.0)}
        spans = infer_listing_spans(first, head, venue_spans, "NYSE", venue_volume=volume)
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
            venue_volume={"NYSE": _volume(first, date(2009, 12, 31), 1.0)},
        )
        assert spans == [("NYSE", first, None)]


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
