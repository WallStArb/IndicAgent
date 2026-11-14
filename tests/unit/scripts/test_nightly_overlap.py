"""Plan 185-22 (D-21): the nightly 1d fetch overlaps what D1 already holds.

with_overlap_window adds a window over the last overlap_sessions sessions to the planned 1d
gaps, merged, so a fresh observation overlaps an earlier one and a split shows as a constant
ratio (services/split_detection.py). The pipeline wiring test lives beside its fixture in
test_historical_pipeline_d1_capture.py.
"""

from __future__ import annotations

from datetime import date

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
