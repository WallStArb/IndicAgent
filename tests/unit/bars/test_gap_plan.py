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
