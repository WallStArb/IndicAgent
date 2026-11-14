"""Provider-verified empty OHLCV history (ohlcv_empty_history, migration 354).

Gap detection counts every expected session slot missing from the provider's own ohlcv_raw rows
as a gap, so history the provider does not have (pre-listing, or simply not served) is
re-requested every run and answered "no data" every time. Raw is stored per source: whether a
span is pre-history, and whether it holds a real bar, is judged against the asking provider's
own raw rows and answers, never another vendor's or the canonical selection. This module
remembers those answers:

- `record()` stores the empty range a fetch's backward walk ended in, for the window that
  precedes a symbol's first bar (pre-history). Only IBKR's definitive "no data" answers
  produce a range (see `src.providers.ibkr.EmptyHistory`).
- `subtract()` removes a fresh range from the detected gaps, so it is not requested again.
- A row older than `infra.backfill.empty_history_reverify_days` is stale: it suppresses
  nothing, the walk runs again, and the row is refreshed or, if the provider now serves
  that history, dropped.

It never deletes or hides a bar; it only decides which requests to skip.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.bar_accumulator import _TF_MINUTES
from src.intelligence.bars.gap_plan import (
    ConfirmedSpan,
)
from src.intelligence.bars.gap_plan import (
    confirmed_empty_spans as _confirmed,
)
from src.intelligence.bars.sources import GRID_SOURCE_TF, GRID_TIMEFRAMES
from src.intelligence.bars.vendor_kind import VENDOR_IBKR
from src.providers.base import VENUE_ROUTE_ALIASES

_REVERIFY_DAYS_KEY = "infra.backfill.empty_history_reverify_days"
_VENUE_EXCHANGES_KEY = "infra.ibkr.venue_fallback.exchanges"
_VENUE_TIMEFRAMES_KEY = "infra.ibkr.venue_fallback.timeframes"
_SMART_ROUTE = "SMART"


@dataclass(frozen=True)
class EmptyRange:
    empty_from: datetime
    empty_through: datetime
    verified_at: datetime
    n_confirming_chunks: int

    def adjoins(self, start: datetime, end: datetime, slack: timedelta) -> bool:
        """True if [start, end] overlaps this range or touches it within `slack`."""
        return start <= self.empty_through + slack and end >= self.empty_from - slack


def has_bar_between(
    conn: Any, symbol: str, timeframe: str, start: datetime, end: datetime, vendor: str
) -> bool:
    """True if `vendor` holds a raw bar inside [start, end]: the span is not empty for it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM ohlcv_raw "
            "WHERE symbol = %s AND timeframe = %s AND vendor = %s "
            'AND "timestamp" >= %s AND "timestamp" <= %s)',
            (symbol, timeframe, vendor, start, end),
        )
        return bool(cur.fetchone()[0])


def _load_apr_list(conn: Any, key: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"APR key {key!r} is not set (migration 374)")
    return [str(v) for v in json.loads(row[0])]


def load_venue_routes(conn: Any) -> list[str]:
    """The former-venue routes the provider asks (APR infra.ibkr.venue_fallback.exchanges)."""
    return _load_apr_list(conn, _VENUE_EXCHANGES_KEY)


def _confirmation_timeframe(conn: Any, timeframe: str) -> str:
    """The timeframe whose recorded answers confirm `timeframe`'s empty history.

    A venue-fallback timeframe (APR infra.ibkr.venue_fallback.timeframes) is confirmed by its
    own answers; a derived grid timeframe (15m, 1h) inherits its source's, because the grid
    is derived from that source and has no provider-side truth of its own.
    """
    source = GRID_SOURCE_TF if timeframe in GRID_TIMEFRAMES else timeframe
    if source not in _load_apr_list(conn, _VENUE_TIMEFRAMES_KEY):
        raise ValueError(
            f"empty history for {timeframe!r} is confirmed by {source!r} answers, which "
            f"{_VENUE_TIMEFRAMES_KEY} does not cover"
        )
    return source


def _interval(timeframe: str) -> timedelta:
    return timedelta(minutes=_TF_MINUTES[timeframe])


def _union(spans: list[ConfirmedSpan], slack: timedelta) -> list[ConfirmedSpan]:
    merged: list[ConfirmedSpan] = []
    for span in sorted(spans, key=lambda s: s.start):
        last = merged[-1] if merged else None
        if last is not None and span.start <= last.end + slack:
            merged[-1] = ConfirmedSpan(
                last.start, max(last.end, span.end), last.n_confirming + span.n_confirming
            )
        else:
            merged.append(span)
    return merged


def _confirmed_spans(
    conn: Any, symbol: str, timeframe: str, venues: list[str], slack: timedelta, vendor: str
) -> list[ConfirmedSpan]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fetch_run_id, route, primary_exchange, window_start, window_end "
            "FROM ohlcv_request WHERE symbol = %s AND timeframe = %s "
            "AND what_to_show = 'TRADES' AND window_start IS NOT NULL "
            "AND (outcome = 'no_data' OR (route = 'SMART' AND outcome = 'bars')) "
            "AND source = %s",
            (symbol, timeframe, vendor),
        )
        rows = cur.fetchall()
    runs: dict[Any, dict[str, list[tuple[datetime, datetime]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    primaries: dict[Any, str | None] = {}
    for run, route, primary, window_start, window_end in rows:
        runs[run][route].append((window_start, window_end))
        if route == _SMART_ROUTE and primary:
            primaries[run] = primary
    spans: list[ConfirmedSpan] = []
    for run, windows in runs.items():
        primary = primaries.get(run)
        required = [_SMART_ROUTE] + [v for v in venues if VENUE_ROUTE_ALIASES.get(v, v) != primary]
        spans.extend(_confirmed(windows, required, slack=slack))
    # SMART answers a 1d head with one request that returns bars from the listing on, so the
    # empty span before it is implied, not a SMART no_data window: SMART counts as answered
    # with either outcome, and the span is confirmed only where no real bar sits inside it.
    return [
        span
        for span in _union(spans, slack)
        if not has_bar_between(conn, symbol, timeframe, span.start, span.end, vendor)
    ]


def confirmed_empty_spans(
    conn: Any, symbol: str, timeframe: str, vendor: str = VENDOR_IBKR
) -> list[tuple[datetime, datetime]]:
    """Spans where SMART answered and every former venue other than the primary answered
    no_data within one fetch run, with no real bar of `vendor` inside, read from the vendor's
    own ohlcv_request rows (D-20; the venue routes are an IBKR mechanism, so the default).
    A timeout or failure on any route leaves that run's span unconfirmed. Derived grid
    timeframes read their source's answers."""
    confirm_tf = _confirmation_timeframe(conn, timeframe)
    spans = _confirmed_spans(
        conn,
        symbol,
        confirm_tf,
        load_venue_routes(conn),
        timedelta(days=1) + _interval(confirm_tf),
        vendor,
    )
    return [(s.start, s.end) for s in spans]
