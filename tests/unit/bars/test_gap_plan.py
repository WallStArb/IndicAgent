"""Tests for src/intelligence/bars/gap_plan.py: one pure definition of a missing bar
(plan 185-18 task 1a, todo 462; design: docs/plans/2026-09-29-intraday-bar-store-
redesign.md change 2).

The AnsweredWindows cases moved here from the deleted
tests/unit/scripts/test_request_coverage.py when the interim module was folded into
the planner; the plan_gaps cases are the planner's own contract: end-exclusive
windows, coverage by stored observation / answered window / provider-verified empty
span, the still-forming cap at the run's end, and the empty plan a completed fetch
must leave.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
    expected_grid_slots,
    plan_gaps,
)

_HOUR = timedelta(hours=1)
_QUARTER = timedelta(minutes=15)


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


class TestAnsweredWindows:
    def test_empty_covers_nothing(self):
        assert not AnsweredWindows().covers(_t(2, 15), _HOUR)

    def test_slot_inside_a_window_is_covered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 18))])
        assert windows.covers(_t(2, 15), _HOUR)
        assert windows.covers(_t(2, 17), _HOUR)

    def test_slot_running_past_the_window_end_is_not_covered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 18))])
        assert not windows.covers(_t(2, 18), _HOUR)
        assert not windows.covers(_t(2, 14), _HOUR)
        # a 90 minute bar starting at 17:00 would end at 18:30, past the window
        assert not windows.covers(_t(2, 17), timedelta(minutes=90))

    def test_overlapping_and_touching_windows_merge(self):
        windows = AnsweredWindows.from_rows(
            [(_t(2, 17), _t(2, 19)), (_t(2, 15), _t(2, 18)), (_t(2, 19), _t(2, 21))]
        )
        assert windows.starts == (_t(2, 15),)
        assert windows.ends == (_t(2, 21),)

    def test_disjoint_windows_leave_the_gap_uncovered(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 16)), (_t(2, 18), _t(2, 19))])
        assert windows.covers(_t(2, 15), _HOUR)
        assert not windows.covers(_t(2, 16), _HOUR)
        assert not windows.covers(_t(2, 17), _HOUR)
        assert windows.covers(_t(2, 18), _HOUR)

    def test_empty_or_inverted_window_is_ignored(self):
        windows = AnsweredWindows.from_rows([(_t(2, 15), _t(2, 15)), (_t(2, 17), _t(2, 16))])
        assert windows == AnsweredWindows()

    def test_coverage_constants_name_the_stored_bar_route(self):
        assert (COVERAGE_ROUTE, COVERAGE_WHAT_TO_SHOW) == ("SMART", "TRADES")
        # timeout and failed answers never cover
        assert set(ANSWERED_OUTCOMES) == {"bars", "no_data"}


class TestPlanGaps:
    def test_completed_fetch_leaves_an_empty_plan(self):
        """A symbol and timeframe whose fetch completed cleanly has an empty plan
        (the plan's own invariant, asserted against the planner directly)."""
        slots = [_t(2, h) for h in range(14, 20)]
        plan = plan_gaps(slots, list(slots), AnsweredWindows(), _HOUR, run_end=_t(2, 20))
        assert plan == []

    def test_one_slot_gap_is_one_bar_interval_never_an_empty_window(self):
        plan = plan_gaps([_t(2, 15)], [], AnsweredWindows(), _HOUR, run_end=_t(2, 17))
        assert plan == [(_t(2, 15), _t(2, 16))]

    def test_contiguous_missing_slots_form_one_end_exclusive_window(self):
        slots = [_t(2, h) for h in range(15, 19)]
        stored = [_t(2, 15)]
        plan = plan_gaps(slots, stored, AnsweredWindows(), _HOUR, run_end=_t(2, 19))
        # the window ends at the LAST missing slot's end, not its start
        assert plan == [(_t(2, 16), _t(2, 19))]

    def test_discontiguous_runs_split_into_separate_windows(self):
        slots = [_t(2, h) for h in range(15, 19)]
        stored = [_t(2, 16)]
        plan = plan_gaps(slots, stored, AnsweredWindows(), _HOUR, run_end=_t(2, 19))
        assert plan == [(_t(2, 15), _t(2, 16)), (_t(2, 17), _t(2, 19))]

    def test_answered_window_covers_a_slot(self):
        slots = [_t(2, h) for h in range(15, 18)]
        answered = AnsweredWindows.from_rows([(_t(2, 16), _t(2, 18))])
        plan = plan_gaps(slots, [], answered, _HOUR, run_end=_t(2, 18))
        assert plan == [(_t(2, 15), _t(2, 16))]

    def test_slot_still_forming_stays_a_gap_capped_at_the_run_end(self):
        """A slot whose end lands after the run's end is not covered by the cap: it
        stays a gap, and its window ends at the run's end."""
        slot = _t(2, 15)
        run_end = _t(2, 15, 30)  # mid-bar
        plan = plan_gaps([slot], [], AnsweredWindows(), _HOUR, run_end=run_end)
        assert plan == [(slot, run_end)]

    def test_empty_span_covers_slots_starting_inside_it(self):
        """A provider-verified empty span [from, through] covers a slot whose START
        lies within it (the provider definitively served nothing there); the slot
        before `from` and the one after `through` stay gaps."""
        slots = [_t(2, 14), _t(2, 15), _t(2, 16), _t(2, 17)]
        spans = [(_t(2, 15), _t(2, 16))]
        plan = plan_gaps(slots, [], AnsweredWindows(), _HOUR, run_end=_t(2, 18), empty_ranges=spans)
        assert plan == [(_t(2, 14), _t(2, 15)), (_t(2, 17), _t(2, 18))]

    def test_duplicate_or_unsorted_slots_are_tolerated(self):
        slots = [_t(2, 16), _t(2, 15), _t(2, 15)]
        plan = plan_gaps(slots, [], AnsweredWindows(), _HOUR, run_end=_t(2, 17))
        assert plan == [(_t(2, 15), _t(2, 17))]


def test_gap_plan_module_is_pure():
    """Ring rule + purity: no import from services/ or scripts/, and no clock or
    connection reaches the planner (enforced as a source-level guard so CI catches
    a new import without executing anything)."""
    source = Path("src/intelligence/bars/gap_plan.py").read_text()
    assert "import services" not in source
    assert "from services" not in source
    assert "import scripts" not in source
    assert "from scripts" not in source
    assert "datetime.now" not in source
    assert "cursor" not in source


@pytest.mark.parametrize(
    ("timeframe", "interval"),
    [("5m", timedelta(minutes=5)), ("15m", _QUARTER), ("1h", _HOUR)],
)
def test_plan_gaps_interval_scales_with_timeframe(timeframe: str, interval: timedelta):
    slot = _t(2, 15)
    plan = plan_gaps([slot], [], AnsweredWindows(), interval, run_end=slot + 3 * interval)
    assert plan == [(slot, slot + interval)]


class TestConfirmedEmptySpans:
    """Plan 185-19 (D-20): a span is empty only when SMART and every required venue
    answered no_data for it; the rule is pure, over one fetch run's no_data windows."""

    _DAY = timedelta(days=1)

    @staticmethod
    def _w(a, b):
        return (datetime(2012, 1, a, tzinfo=UTC), datetime(2012, 1, b, tzinfo=UTC))

    def test_the_span_every_route_answered_is_confirmed_with_its_answer_count(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        windows = {
            "SMART": [self._w(1, 10)],
            "NYSE": [self._w(1, 10)],
            "ARCA": [self._w(1, 10)],
        }
        (span,) = confirmed_empty_spans(windows, ["SMART", "NYSE", "ARCA"], slack=self._DAY)
        assert (span.start, span.end) == self._w(1, 10)
        assert span.n_confirming == 3

    def test_only_the_intersection_of_the_routes_is_confirmed(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        windows = {"SMART": [self._w(1, 20)], "NYSE": [self._w(5, 30)]}
        (span,) = confirmed_empty_spans(windows, ["SMART", "NYSE"], slack=self._DAY)
        assert (span.start, span.end) == self._w(5, 20)

    def test_a_required_route_with_no_answer_confirms_nothing(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        windows = {"SMART": [self._w(1, 10)], "NYSE": [self._w(1, 10)]}
        assert confirmed_empty_spans(windows, ["SMART", "NYSE", "ARCA"], slack=self._DAY) == []

    def test_adjacent_chunks_merge_within_the_slack_and_count_every_answer(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        windows = {
            "SMART": [self._w(1, 5), self._w(6, 10)],
            "NYSE": [self._w(1, 10)],
        }
        (span,) = confirmed_empty_spans(windows, ["SMART", "NYSE"], slack=self._DAY)
        assert (span.start, span.end) == self._w(1, 10)
        assert span.n_confirming == 3

    def test_a_gap_wider_than_the_slack_leaves_two_spans(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        windows = {"SMART": [self._w(1, 3), self._w(9, 12)], "NYSE": [self._w(1, 12)]}
        spans = confirmed_empty_spans(windows, ["SMART", "NYSE"], slack=self._DAY)
        assert [(s.start, s.end) for s in spans] == [self._w(1, 3), self._w(9, 12)]

    def test_no_required_routes_confirms_nothing(self):
        from src.intelligence.bars.gap_plan import confirmed_empty_spans

        assert confirmed_empty_spans({"SMART": [self._w(1, 5)]}, [], slack=self._DAY) == []


# --- the 1h RTH grid is IBKR's stamping: the opening bar, then clock hours (review finding 5) ---


def _hhmm(slots):
    return [slot.strftime("%H:%M") for slot in slots]


def _day_slots(year, month, day, timeframe="1h"):
    return expected_grid_slots(
        "nyse",
        "NYSE",
        timeframe,
        datetime(year, month, day, tzinfo=UTC),
        datetime(year, month, day, 23, 59, tzinfo=UTC),
    )


def test_1h_grid_summer_is_the_330_bar_then_clock_hours():
    # AAPL 2026-07-14 as stored by IBKR
    assert _hhmm(_day_slots(2026, 7, 14)) == [
        "13:30", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"
    ]  # fmt: skip


def test_1h_grid_winter_is_the_430_bar_then_clock_hours():
    # AAPL 2026-01-14 as stored by IBKR
    assert _hhmm(_day_slots(2026, 1, 14)) == [
        "14:30", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"
    ]  # fmt: skip


def test_1h_grid_half_day_stops_at_the_early_close():
    # 2025-11-28 closes 13:00 ET: the last bar starts 12:00 ET (17:00 UTC)
    assert _hhmm(_day_slots(2025, 11, 28)) == ["14:30", "15:00", "16:00", "17:00"]


def test_15m_grid_is_unchanged_open_anchored_quarters():
    slots = _day_slots(2026, 7, 14, "15m")
    assert slots[0].strftime("%H:%M") == "13:30" and slots[-1].strftime("%H:%M") == "19:45"
    assert len(slots) == 26


def test_a_missing_opening_bar_asks_only_its_own_half_hour():
    slots = _day_slots(2026, 7, 14)
    stored = slots[1:]
    plan = plan_gaps(
        slots,
        stored,
        AnsweredWindows(),
        timedelta(hours=1),
        run_end=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert plan == [
        (datetime(2026, 7, 14, 13, 30, tzinfo=UTC), datetime(2026, 7, 14, 14, 0, tzinfo=UTC))
    ]


def test_the_opening_bar_and_the_next_hour_form_one_contiguous_window():
    slots = _day_slots(2026, 7, 14)
    plan = plan_gaps(
        slots,
        slots[2:],
        AnsweredWindows(),
        timedelta(hours=1),
        run_end=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert plan == [
        (datetime(2026, 7, 14, 13, 30, tzinfo=UTC), datetime(2026, 7, 14, 15, 0, tzinfo=UTC))
    ]


def test_an_answered_window_ending_at_the_opening_bars_end_covers_it():
    slots = _day_slots(2026, 7, 14)
    answered = AnsweredWindows.from_rows(
        [(datetime(2026, 7, 14, 13, 30, tzinfo=UTC), datetime(2026, 7, 14, 14, 0, tzinfo=UTC))]
    )
    plan = plan_gaps(
        slots, slots[1:], answered, timedelta(hours=1), run_end=datetime(2026, 7, 15, tzinfo=UTC)
    )
    assert plan == []


def test_a_partial_slot_is_never_covered_and_stays_a_gap():
    """Migration 479 (second review of 191-07, finding 5): a bar an answer served incomplete is
    not an answer for its slot, whatever window holds it, so the planner asks it again."""
    t0 = datetime(2026, 10, 12, 19, 50, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    windows = AnsweredWindows.from_rows([(t0, t1 + timedelta(minutes=30))], partial=[t1])
    assert windows.covers(t0, timedelta(minutes=5)) and not windows.covers(t1, timedelta(minutes=5))
    plan = plan_gaps([t0, t1], [], windows, timedelta(minutes=5), run_end=t1 + timedelta(hours=1))
    assert plan == [(t1, t1 + timedelta(minutes=5))]


def test_load_range_windows_run_from_the_first_midnight_to_the_midnight_after_the_end_day():
    from datetime import date

    from src.intelligence.bars.gap_plan import load_range_windows

    windows = load_range_windows(
        [(date(2026, 10, 5), date(2026, 10, 7)), (date(2026, 10, 9), date(2026, 10, 8))]
    )
    assert windows == [(datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))]
    answered = AnsweredWindows.from_rows(windows)
    last_slot = datetime(2026, 10, 7, 19, 55, tzinfo=UTC)
    assert answered.covers(last_slot, timedelta(minutes=5))
    assert not answered.covers(datetime(2026, 10, 8, 13, 30, tzinfo=UTC), timedelta(minutes=5))
