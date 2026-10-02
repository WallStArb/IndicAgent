"""One pure definition of a missing bar (plan 185-18 task 1a, todo 462; design:
docs/plans/2026-09-29-intraday-bar-store-redesign.md change 2).

plan_gaps is the single planner every gap consumer calls. The fetch pipeline
reads its inputs over psycopg (scripts/infrastructure/backfill/_d1_gaps.py) and
the auditor over asyncpg (services/bar_auditor.py); both feed this module, so
the fetcher and the auditor produce the same plan for the same record. A slot
is covered when:

- a stored observation exists for it (the archive for 15m/1h,
  market_data_ohlcv for 5m; the SQL readers pick the table), or
- the whole bar lies inside an answered SMART TRADES request window whose
  outcome is `bars` (corroborated by a stored row in the window, enforced in
  the loaders' SQL, so a lost insert never looks covered) or a definitive
  `no_data` (timeout and failed never cover), or
- its start lies inside a provider-verified ohlcv_empty_history span that is
  fresh and sufficiently confirmed (gated by the readers).

Everything else is a gap. Contiguous missing slots form one end-exclusive
window: a window covering a slot ends at the slot's end, so a one-slot gap is
a request of one bar interval, never an empty window. A slot still forming
(its end after the run's end) stays a gap whose window is capped at the run's
end. A completed fetch leaves an empty plan.

Pure by construction: no connection, no clock. Datetimes arrive as data;
`run_end` is passed in. expected_grid_slots (plan 12's RTH-grid rule) lives
here too so services/ reaches it without a pipeline import.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.core.bar_normalizer import generate_session_slots
from src.intelligence.bars.sessions import nyse_sessions

# A request answer only covers its window when the provider definitively
# served bars (corroborated by a stored row, in the loaders' SQL) or
# definitively served nothing. timeout and failed never cover.
ANSWERED_OUTCOMES: tuple[str, ...] = ("bars", "no_data")
# The stored-bar route whose answers the coverage rule trusts (D-20: venue
# routes widen this set where venue fallback applies; 1d-only today).
COVERAGE_ROUTE = "SMART"
COVERAGE_WHAT_TO_SHOW = "TRADES"

# IBKR serves NYSE 15m/1h on its own RTH grid (a 09:30 partial 1h bar then
# clock hours; :00/:15/:30/:45 at 15m), so those timeframes' expected slots are
# session-anchored rather than on-the-hour UTC (plan 12's 42-name hole).
_RTH_GRID_TFS = frozenset({"15m", "1h"})
_GRID_TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60}


@dataclass(frozen=True)
class AnsweredWindows:
    """Merged provider-answered request windows for one (symbol, timeframe)."""

    starts: tuple[datetime, ...] = ()
    ends: tuple[datetime, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.starts)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[datetime, datetime]]) -> AnsweredWindows:
        """Merge overlapping or touching (window_start, window_end) rows."""
        merged: list[tuple[datetime, datetime]] = []
        for start, end in sorted(row for row in rows if row[1] > row[0]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return cls(tuple(s for s, _ in merged), tuple(e for _, e in merged))

    def covers(self, slot: datetime, interval: timedelta) -> bool:
        """True when the whole bar starting at `slot` lies inside a window."""
        if not self.starts:
            return False
        i = bisect_right(self.starts, slot) - 1
        return i >= 0 and slot + interval <= self.ends[i]


def expected_grid_slots(
    session_id: str,
    exchange: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> list[datetime]:
    """Expected stored timestamps for gap detection at `timeframe`.

    15m/1h NYSE equities use IBKR's own RTH grid: a 09:30 partial 1h bar
    (13:30 UTC) then clock hours; :00/:15/:30/:45 at 15m. The old on-the-hour
    UTC generation never expected 13:30, so a missing 09:30 bar was never
    refetched (the 42-name hole the plan 12 SUMMARY records). Other session
    types and timeframes keep generate_session_slots. Moved here from the
    pipeline (plan 185-18) so services/bar_auditor reaches the same rule
    without a pipeline import.
    """
    if timeframe in _RTH_GRID_TFS and session_id == "nyse":
        return _rth_grid_slots(timeframe, start_dt, end_dt)
    return generate_session_slots(session_id, exchange, timeframe, start_dt, end_dt)


def _rth_grid_slots(timeframe: str, start_dt: datetime, end_dt: datetime) -> list[datetime]:
    """Session-anchored RTH slots for every NYSE session overlapping the window."""
    interval = timedelta(minutes=_GRID_TF_MINUTES[timeframe])
    sessions = nyse_sessions(start_dt.date() - timedelta(days=1), end_dt.date() + timedelta(days=1))
    slots: list[datetime] = []
    for session_open, session_close in sessions.values():
        slot = session_open
        while slot < session_close:
            if start_dt <= slot <= end_dt:
                slots.append(slot)
            slot += interval
    return slots


def plan_gaps(
    slots: Iterable[datetime],
    stored: Iterable[datetime],
    answered: AnsweredWindows,
    interval: timedelta,
    *,
    run_end: datetime,
    empty_ranges: Iterable[tuple[datetime, datetime]] = (),
) -> list[tuple[datetime, datetime]]:
    """The missing-bar plan as end-exclusive (start, end) fetch windows.

    `slots` are the expected slot starts (deduplicated and sorted here);
    `stored` the observed slot timestamps; `answered` the provider-answered
    windows; `empty_ranges` the provider-verified empty spans as
    (empty_from, empty_through), covering slots whose start lies within --
    exactly the suppression the legacy subtract() applied to slot-start
    ranges. A slot whose start is at or after `run_end` is not planned; a
    planned window never ends after `run_end`, so a slot still forming stays
    a gap whose ask is capped at the run's end.
    """
    horizon = sorted({slot for slot in slots if slot < run_end})
    if not horizon:
        return []
    stored_set = set(stored)
    spans = [(empty_from, through) for empty_from, through in empty_ranges if through >= empty_from]
    missing = [
        slot
        for slot in horizon
        if slot not in stored_set
        and not answered.covers(slot, interval)
        and not any(empty_from <= slot <= through for empty_from, through in spans)
    ]
    if not missing:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    run_start = missing[0]
    prev = missing[0]
    for slot in missing[1:]:
        if slot - prev != interval:
            ranges.append((run_start, min(prev + interval, run_end)))
            run_start = slot
        prev = slot
    ranges.append((run_start, min(prev + interval, run_end)))
    return ranges
