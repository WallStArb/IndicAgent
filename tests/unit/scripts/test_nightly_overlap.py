"""Plan 185-22 (D-21): the nightly 1d fetch overlaps what D1 already holds.

with_overlap_window adds a window over the last overlap_sessions sessions to the planned 1d
gaps, merged, so a fresh observation overlaps an earlier one and a split shows as a constant
ratio (services/split_detection.py). The pipeline wiring test lives beside its fixture in
test_historical_pipeline_d1_capture.py.
"""

from __future__ import annotations

from datetime import date

from scripts.infrastructure.backfill._d1_gaps import with_overlap_window

# Mon 2026-09-14 .. Fri 2026-10-02: 15 sessions, weekends absent.
_SESSIONS = {
    date(2026, 9, 14),
    date(2026, 9, 15),
    date(2026, 9, 16),
    date(2026, 9, 17),
    date(2026, 9, 18),
    date(2026, 9, 21),
    date(2026, 9, 22),
    date(2026, 9, 23),
    date(2026, 9, 24),
    date(2026, 9, 25),
    date(2026, 9, 28),
    date(2026, 9, 29),
    date(2026, 9, 30),
    date(2026, 10, 1),
    date(2026, 10, 2),
}
_END = date(2026, 10, 2)


def test_an_up_to_date_symbol_gets_exactly_the_overlap_window():
    assert with_overlap_window([], _SESSIONS, _END, 5) == [(date(2026, 9, 28), date(2026, 10, 2))]


def test_the_window_counts_sessions_not_calendar_days():
    (window,) = with_overlap_window([], _SESSIONS, _END, 7)
    assert window == (date(2026, 9, 24), date(2026, 10, 2))


def test_zero_overlap_leaves_the_plan_untouched():
    gaps = [(date(2026, 9, 14), date(2026, 9, 15))]
    assert with_overlap_window(gaps, _SESSIONS, _END, 0) == gaps


def test_a_gap_inside_or_touching_the_overlap_merges_into_one_window():
    gaps = [(date(2026, 9, 30), date(2026, 10, 1))]
    assert with_overlap_window(gaps, _SESSIONS, _END, 5) == [(date(2026, 9, 28), date(2026, 10, 2))]
    touching = [(date(2026, 9, 25), date(2026, 9, 25))]
    assert with_overlap_window(touching, _SESSIONS, _END, 3) == [
        (date(2026, 9, 25), date(2026, 9, 25)),
        (date(2026, 9, 30), date(2026, 10, 2)),
    ]


def test_an_older_gap_stays_a_separate_window():
    gaps = [(date(2026, 9, 14), date(2026, 9, 16))]
    assert with_overlap_window(gaps, _SESSIONS, _END, 3) == [
        (date(2026, 9, 14), date(2026, 9, 16)),
        (date(2026, 9, 30), date(2026, 10, 2)),
    ]


def test_fewer_sessions_than_the_overlap_start_at_the_first_one():
    (window,) = with_overlap_window([], _SESSIONS, _END, 250)
    assert window == (date(2026, 9, 14), date(2026, 10, 2))


def test_no_sessions_up_to_end_means_no_window():
    assert with_overlap_window([], {date(2026, 10, 5)}, _END, 5) == []
