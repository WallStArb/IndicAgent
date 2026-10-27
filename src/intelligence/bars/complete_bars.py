"""Which served bars are complete vendor answers (second review of plan 191-07, finding 5).

Owner rule (2026-10-14): "we need complete bars from each source if they are available". A bar
the vendor served truncated (its request ended inside the bar), still forming (the answer came
before the bar ended), or before the closing auction settled (a bar ending at or after its NYSE
session close, answered less than `settle` after the close: ADM 2026-10-12 19:55 UTC moved from
380,459 to 380,759 after the close) is not that source's answer for the slot. Raw is last-wins,
so storing it would make the completion look like the vendor restating its own history, or keep a
partial as current. The fetch layer drops such a bar before it reaches the ingress contract and
records it on its ledger (the request row on the fetcher path, the load row on the load engine
path), so nothing is dropped silently, and the gap planner keeps the slot a gap.

The rule is vendor-agnostic and lives here, not in a provider leaf (src/providers/CLAUDE.md:
policy never enters a leaf). The intraday analogue of D-191-J; 1d keeps D-191-J's rule (complete
at the session close, `session_complete_at`), so a daily bar is judged exactly as before.

A bar is judged against the ANSWER time of the request that served it, never the time the bars
are parsed or written. The grid block end (the bar's grid start plus its size, capped at the
session close for a regular-hours bar) is an upper bound on the bar's own end (a session's first bar on a coarse grid, 13:30 on 1h or 4h, is the short
first bar of its block), so a bar kept is always whole.

Pure Ring 1: no database, no clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.intelligence.bars.selection import session_date
from src.intelligence.bars.sessions import nyse_sessions, session_complete_at

# Intraday bar sizes in seconds (bar lengths, not tunables). Every vendor stamps an intraday bar
# on the UTC grid of its size.
INTRADAY_BAR_SECONDS: dict[str, int] = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def _stamp(bar: Any) -> datetime:
    ts = bar["timestamp"] if isinstance(bar, dict) else bar.timestamp
    return ts.astimezone(UTC)


def block_end(ts: datetime, timeframe: str) -> datetime:
    """The end of the grid block holding the intraday bar that starts at `ts`."""
    size = INTRADAY_BAR_SECONDS[timeframe]
    epoch = int(ts.astimezone(UTC).timestamp())
    return datetime.fromtimestamp(epoch - epoch % size + size, tz=UTC)


def _bounds(stamps: Iterable[datetime]) -> dict[date, tuple[datetime, datetime]]:
    days = {session_date(ts) for ts in stamps}
    if not days:
        return {}
    return dict(nyse_sessions(min(days), max(days)))


def on_grid(ts: datetime, timeframe: str, session_open: datetime | None) -> bool:
    """True when an intraday bar starts on the UTC grid of its size, or at its session's open
    (the short first bar of a coarse block, 13:30 on 1h or 4h). A bar starting anywhere else
    began at a request's start inside a block: it holds part of the block's trades only (HON
    2026-03-09 15:26:34, volume 4,828)."""
    size = INTRADAY_BAR_SECONDS[timeframe]
    return int(ts.astimezone(UTC).timestamp()) % size == 0 or ts == session_open


def split_complete[T](
    bars: Sequence[T],
    timeframe: str,
    *,
    answered_at: datetime,
    request_end: datetime | None = None,
    settle: timedelta = timedelta(0),
) -> tuple[list[T], list[T]]:
    """(complete, partial) in input order. `answered_at` is when the vendor answered (a lower
    bound when the caller only knows the time it asked: never later than the real answer).
    `request_end` is the request's end, when it had one inside the history (None: up to now).
    `settle` is APR threshold.bar_integrity.session_close_settle_s. Accepts objects with a
    `timestamp` attribute or dicts with a "timestamp" key."""
    if not bars:
        return [], []
    if timeframe == "1d":
        days = [_stamp(b).date() for b in bars]
        # One calendar build for the whole window, not one per bar (a 10-year history page
        # took minutes asking the calendar day by day).
        sessions = nyse_sessions(min(days), max(days))
        complete = [
            b for b, day in zip(bars, days) if session_complete_at(day, answered_at, sessions)
        ]
        kept = {id(b) for b in complete}
        return complete, [b for b in bars if id(b) not in kept]
    if timeframe not in INTRADAY_BAR_SECONDS:
        raise ValueError(f"no complete-bar rule for timeframe {timeframe!r}")
    bounds = _bounds(_stamp(b) for b in bars)
    complete: list[T] = []
    partial: list[T] = []
    for bar in bars:
        ts = _stamp(bar)
        end = block_end(ts, timeframe)
        session = bounds.get(session_date(ts))
        if session is not None and session[0] <= ts < session[1]:
            # a regular-hours bar ends at the close at the latest: the winter 4h 20:00 UTC bar
            # holds 15:00 to 16:00 ET, not its 20:00 to 24:00 grid block (second review, low)
            end = min(end, session[1])
        ok = (
            end <= answered_at
            and (request_end is None or end <= request_end)
            and on_grid(ts, timeframe, session[0] if session else None)
        )
        if ok and session is not None and end >= session[1]:
            ok = answered_at >= session[1] + settle
        (complete if ok else partial).append(bar)
    return complete, partial


def partial_json(bars: Iterable[Any]) -> list[dict[str, Any]]:
    """Partial bars as the ledger records them: [{t, o, h, l, c, v}] (t ISO-8601 UTC)."""

    def get(bar: Any, key: str) -> Any:
        return bar[key] if isinstance(bar, dict) else getattr(bar, key)

    return [
        {
            "t": _stamp(b).isoformat(),
            "o": float(get(b, "open")),
            "h": float(get(b, "high")),
            "l": float(get(b, "low")),
            "c": float(get(b, "close")),
            "v": None if get(b, "volume") is None else int(get(b, "volume")),
        }
        for b in bars
    ]
