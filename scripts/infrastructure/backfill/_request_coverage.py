"""Answered-request coverage for intraday gap detection (todo 462, phase 185 `ohlcv_request`).

With placeholder bars gone from the stored table, a session slot without a bar is ambiguous:
never fetched, fetched and the provider had nothing (a thin name that did not trade), or a
provider hole. `ohlcv_request` records every provider request with its window and outcome, so
"was this window already asked and answered" is read from there instead of being inferred from a
stored placeholder row.

- `load_answered_windows()` returns the merged windows the provider answered (`bars` or `no_data`)
  for one symbol and timeframe over the TRADES route the stored bars come from. `timeout` and
  `failed` requests are never coverage, and a `bars` answer counts only once a bar is stored in its window.
- `AnsweredWindows.covers()` says whether a whole bar slot lies inside one of them.

A window the provider answered can still hold a provider hole; that is found by reconciling a
coarser timeframe against a finer one (todo 462), not by re-requesting here. Coverage decides only
which requests to skip; it never writes, deletes or hides a bar.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# The route and request type behind stored bars (`market_data_ohlcv` holds SMART TRADES bars).
# A venue-route or ADJUSTED_LAST request answers a different question and is not coverage.
_COVERAGE_ROUTE = "SMART"
_COVERAGE_WHAT_TO_SHOW = "TRADES"
_ANSWERED_OUTCOMES = ("bars", "no_data")

# A `bars` answer counts only when at least one row is stored in its window: the request record
# is written by a separate connection from the bar insert, so a chunk whose insert failed (the run
# exits nonzero and the lane retries) must not leave a window that looks covered. Chunk inserts
# commit whole, so a lost chunk leaves the window empty. The check is deliberately not
# `count >= n_bars`: IBKR durations round up to whole days, so a short window's answer can hold
# bars from before `window_start` and n_bars overshoots what the window itself stores. A short
# window with no stored row inside it is re-requested, which costs one small request.
_ANSWERED_WINDOWS_SQL = """
SELECT r.window_start, r.window_end FROM ohlcv_request r
WHERE r.symbol = %s AND r.timeframe = %s
  AND r.route = %s AND r.what_to_show = %s
  AND r.outcome = ANY(%s)
  AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM market_data_ohlcv m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m.timestamp >= r.window_start AND m.timestamp < r.window_end
    )
  )
ORDER BY r.window_start
"""


@dataclass(frozen=True)
class AnsweredWindows:
    """Merged, sorted, non-overlapping [start, end) windows the provider answered."""

    starts: tuple[datetime, ...] = ()
    ends: tuple[datetime, ...] = ()

    @classmethod
    def from_rows(cls, rows: list[tuple[datetime, datetime]]) -> AnsweredWindows:
        merged: list[list[datetime]] = []
        for start, end in sorted(rows):
            if end <= start:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return cls(
            starts=tuple(window[0] for window in merged),
            ends=tuple(window[1] for window in merged),
        )

    def covers(self, slot: datetime, interval: timedelta) -> bool:
        """True if the whole bar [slot, slot + interval) lies inside one answered window."""
        index = bisect_right(self.starts, slot) - 1
        return index >= 0 and slot + interval <= self.ends[index]


def load_answered_windows(conn: Any, symbol: str, timeframe: str) -> AnsweredWindows:
    """Answered SMART TRADES windows for `symbol` and `timeframe`, merged."""
    with conn.cursor() as cur:
        cur.execute(
            _ANSWERED_WINDOWS_SQL,
            (symbol, timeframe, _COVERAGE_ROUTE, _COVERAGE_WHAT_TO_SHOW, list(_ANSWERED_OUTCOMES)),
        )
        rows = cur.fetchall()
    return AnsweredWindows.from_rows([(row[0], row[1]) for row in rows])
