"""Provider-verified empty OHLCV history (ohlcv_empty_history, migration 354).

Gap detection counts every expected session slot missing from market_data_ohlcv as a gap,
so history the provider does not have (pre-listing, or simply not served) is re-requested
every run and answered "no data" every time. This module remembers those answers:

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
    fresh_empty_span,
)
from src.intelligence.bars.gap_plan import (
    confirmed_empty_spans as _confirmed,
)
from src.intelligence.bars.sources import GRID_SOURCE_TF, GRID_TIMEFRAMES
from src.providers.base import VENUE_ROUTE_ALIASES, EmptyHistory

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


def is_fresh(verified_at: datetime, now: datetime, reverify_days: int) -> bool:
    """A record younger than the APR re-verification age still suppresses requests.

    Thin alias of the freshness half of gap_plan.fresh_empty_span, kept for the
    unit test that pins the boundary; production readers decide through
    fresh_empty_span so freshness and confirmations can never diverge.
    """
    return now - verified_at < timedelta(days=reverify_days)


def load_reverify_days(conn: Any) -> int:
    """The APR re-verification age. Raises if unset: without it, staleness is undefined."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = %s", (_REVERIFY_DAYS_KEY,)
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"APR key {_REVERIFY_DAYS_KEY!r} is not set (migration 354)")
    return int(row[0])


def load(conn: Any, provider: str) -> dict[tuple[str, str], EmptyRange]:
    """Every recorded range for `provider`, keyed by (symbol, timeframe), fresh or stale."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, timeframe, empty_from, empty_through, verified_at, "
            "n_confirming_chunks FROM ohlcv_empty_history WHERE provider = %s",
            (provider,),
        )
        return {(r[0], r[1]): EmptyRange(r[2], r[3], r[4], r[5]) for r in cur.fetchall()}


def subtract(
    gaps: list[tuple[datetime, datetime]], empty: EmptyRange, interval: timedelta
) -> list[tuple[datetime, datetime]]:
    """Remove `empty`'s range from sorted gap ranges; keeps every slot outside it."""
    kept: list[tuple[datetime, datetime]] = []
    for start, end in gaps:
        if end < empty.empty_from or start > empty.empty_through:
            kept.append((start, end))
            continue
        if start < empty.empty_from:
            kept.append((start, empty.empty_from - interval))
        if end > empty.empty_through:
            kept.append((empty.empty_through + interval, end))
    return kept


def has_bar_before(conn: Any, symbol: str, timeframe: str, ts: datetime) -> bool:
    """True if any real bar is older than `ts`, i.e. a window starting there is not
    pre-history. The tradeable view is exact here: the store holds real rows only
    (migration 444 refuses synthetic_fill)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s AND timestamp < %s)",
            (symbol, timeframe, ts),
        )
        return bool(cur.fetchone()[0])


def has_bar_between(conn: Any, symbol: str, timeframe: str, start: datetime, end: datetime) -> bool:
    """True if a real bar lies inside [start, end]: the span is not empty."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s)",
            (symbol, timeframe, start, end),
        )
        return bool(cur.fetchone()[0])


def record(
    conn: Any,
    symbol: str,
    timeframe: str,
    provider: str,
    window_start: datetime,
    observed: EmptyHistory,
    prior: EmptyRange | None = None,
) -> None:
    """Upsert the empty range a pre-history window's walk ended in.

    `empty_from` is the window start: the part older than `observed.verified_from` is
    inferred when the walk stopped on its confirmation threshold, exactly the range the
    walk never requests anyway; `verified_from` and `reached_request_start` keep the two
    parts distinguishable.

    `prior` is the existing range when the new one adjoins it: the two are merged (a later
    walk that verifies the sliver between a range and the first bar extends the range, it
    never replaces it) and confirmations accumulate across runs, so a range reaches the
    apply threshold only after repeated definitive answers.
    """
    empty_from = min(window_start, observed.verified_from)
    empty_through = observed.empty_through
    n_confirming = observed.n_confirming_chunks
    if prior is not None:
        empty_from = min(empty_from, prior.empty_from)
        empty_through = max(empty_through, prior.empty_through)
        n_confirming += prior.n_confirming_chunks
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ohlcv_empty_history (
                symbol, timeframe, provider, empty_from, empty_through, verified_from,
                n_confirming_chunks, reached_request_start, verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (symbol, timeframe, provider) DO UPDATE SET
                empty_from = EXCLUDED.empty_from,
                empty_through = EXCLUDED.empty_through,
                verified_from = EXCLUDED.verified_from,
                n_confirming_chunks = EXCLUDED.n_confirming_chunks,
                reached_request_start = EXCLUDED.reached_request_start,
                verified_at = EXCLUDED.verified_at
            """,
            (
                symbol,
                timeframe,
                provider,
                empty_from,
                empty_through,
                observed.verified_from,
                n_confirming,
                observed.reached_request_start,
            ),
        )
    conn.commit()


def drop(conn: Any, symbol: str, timeframe: str, provider: str) -> None:
    """Remove a range the provider no longer confirms as empty."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ohlcv_empty_history WHERE symbol = %s AND timeframe = %s AND provider = %s",
            (symbol, timeframe, provider),
        )
    conn.commit()


def load_fresh_heads(conn: Any, provider: str, reverify_days: int) -> dict[str, datetime]:
    """Fresh provider head timestamps (migration 355), keyed by symbol."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, head_ts FROM ohlcv_provider_head WHERE provider = %s "
            "AND verified_at > NOW() - make_interval(days => %s)",
            (provider, reverify_days),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def load_first_bars(conn: Any, symbols: list[str]) -> dict[str, datetime]:
    """Each symbol's oldest real bar across timeframes (one indexed MIN per symbol)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.symbol, (SELECT min(m.timestamp) FROM market_data_ohlcv_tradeable m "
            "WHERE m.symbol = s.symbol) FROM unnest(%s::text[]) AS s(symbol)",
            (symbols,),
        )
        return {r[0]: r[1] for r in cur.fetchall() if r[1] is not None}


def record_head(conn: Any, symbol: str, provider: str, head_ts: datetime) -> None:
    """Upsert a successful head lookup. Failures are never stored: a failed lookup can be
    transient (a pacing violation), and a stored failure would suppress the floor until it
    went stale.

    LIVE PATH under the wave-5 activation gate (plan 190-03 contract point 5): the old
    (symbol, provider) shape stays until 190-06 Task 2 applies migration 465 and flips the
    write; the per-TF variant (record_head_per_tf below) is code + tested but must not run
    before that flip, because its ON CONFLICT key has no matching unique index on the live
    tables while the PK is (symbol, provider)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ohlcv_provider_head (symbol, provider, head_ts, verified_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (symbol, provider) DO UPDATE SET
                head_ts = EXCLUDED.head_ts,
                verified_at = EXCLUDED.verified_at
            """,
            (symbol, provider, head_ts),
        )
    conn.commit()


def record_head_per_tf(
    conn: Any, symbol: str, provider: str, timeframe: str, head_ts: datetime
) -> None:
    """Upsert a successful head lookup at the per-(symbol, provider, timeframe) key
    (migration 465's shape, todo 526's per-TF floors).

    WAVE-5 ACTIVATION GATE: NOT the live path until 190-06 Task 2 applies migration 465
    and flips the write (the planner's per-TF floor reads in _fetch_queue already tolerate
    both worlds). Callers before that flip fail with 42P10: the live PK is (symbol,
    provider), so the three-column ON CONFLICT has no matching unique index."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ohlcv_provider_head (symbol, provider, timeframe, head_ts, verified_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (symbol, provider, timeframe) DO UPDATE SET
                head_ts = EXCLUDED.head_ts,
                verified_at = EXCLUDED.verified_at
            """,
            (symbol, provider, timeframe, head_ts),
        )
    conn.commit()


def load_fresh_heads_per_tf(
    conn: Any, provider: str, timeframe: str, reverify_days: int
) -> dict[str, datetime]:
    """Fresh provider head timestamps for one timeframe (migration 465's per-TF rows;
    same wave-5 gate as record_head_per_tf on the write side), keyed by symbol. A symbol
    with no row for `timeframe` falls back to the provider's NULL-timeframe row (the
    pre-465 labeling rule: NULL is the 1d daily-bounds registry row); a timeframe row
    always wins over the NULL row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, timeframe, head_ts FROM ohlcv_provider_head WHERE provider = %s "
            "AND (timeframe = %s OR timeframe IS NULL) "
            "AND verified_at > NOW() - make_interval(days => %s)",
            (provider, timeframe, reverify_days),
        )
        heads: dict[str, datetime] = {}
        for symbol, row_tf, head_ts in cur.fetchall():
            if row_tf is not None or symbol not in heads:
                heads[symbol] = head_ts
        return heads


def apply_empty_range(
    gaps: list[tuple[datetime, datetime]],
    empty: EmptyRange | None,
    now: datetime,
    reverify_days: int,
    interval: timedelta,
    min_confirmations: int,
) -> list[tuple[datetime, datetime]]:
    """Gaps with a fresh, sufficiently confirmed range removed; otherwise unchanged.

    The freshness/confirmation decision is gap_plan.fresh_empty_span, the one
    rule every reader applies; `min_confirmations` is the provider's own
    no-data confirmation threshold (infra.ibkr.no_data_confirmation_chunks).
    """
    if not gaps or empty is None:
        return gaps
    span = fresh_empty_span(
        empty.empty_from,
        empty.empty_through,
        empty.verified_at,
        empty.n_confirming_chunks,
        now=now,
        reverify_days=reverify_days,
        min_confirmations=min_confirmations,
    )
    if span is None:
        return gaps
    return subtract(gaps, empty, interval)


def reconcile(
    conn: Any,
    symbol: str,
    timeframe: str,
    provider: str,
    window: tuple[datetime, datetime],
    observed: EmptyHistory | None,
    prior: EmptyRange | None,
    slack: timedelta,
) -> None:
    """After fetching a (symbol, timeframe)'s oldest window: record the empty range its walk
    ended in, or drop a prior range the provider no longer confirmed. Applies only when the
    window is pre-history (no real bar older than it); anything else says nothing about
    what precedes the first bar."""
    window_start, window_end = window
    # Adjoining is enough to merge a newly verified sliver into the prior range; only an
    # overlap means the prior range's own span was asked again, which is what may drop it.
    touches_prior = prior is not None and prior.adjoins(window_start, window_end, slack)
    overlaps_prior = prior is not None and prior.adjoins(window_start, window_end, timedelta(0))
    if observed is None and not overlaps_prior:
        return
    if has_bar_before(conn, symbol, timeframe, window_start):
        return
    if observed is not None:
        record(
            conn,
            symbol,
            timeframe,
            provider,
            window_start,
            observed,
            prior if touches_prior else None,
        )
    else:
        # The prior range's own span was asked again and not confirmed empty: the provider
        # now serves (part of) it, or the walk ended on a non-definitive failure. A window
        # elsewhere (e.g. the sliver after the range) says nothing about the range.
        drop(conn, symbol, timeframe, provider)


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
    conn: Any, symbol: str, timeframe: str, venues: list[str], slack: timedelta
) -> list[ConfirmedSpan]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fetch_run_id, route, primary_exchange, window_start, window_end "
            "FROM ohlcv_request WHERE symbol = %s AND timeframe = %s "
            "AND what_to_show = 'TRADES' AND window_start IS NOT NULL "
            "AND (outcome = 'no_data' OR (route = 'SMART' AND outcome = 'bars'))",
            (symbol, timeframe),
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
        if not has_bar_between(conn, symbol, timeframe, span.start, span.end)
    ]


def confirmed_empty_spans(
    conn: Any, symbol: str, timeframe: str
) -> list[tuple[datetime, datetime]]:
    """Spans where SMART answered and every former venue other than the primary answered
    no_data within one fetch run, with no real bar inside, read from ohlcv_request (D-20).
    A timeout or failure on any route leaves that run's span unconfirmed. Derived grid
    timeframes read their source's answers."""
    confirm_tf = _confirmation_timeframe(conn, timeframe)
    spans = _confirmed_spans(
        conn,
        symbol,
        confirm_tf,
        load_venue_routes(conn),
        timedelta(days=1) + _interval(confirm_tf),
    )
    return [(s.start, s.end) for s in spans]


def _record_span(
    conn: Any,
    symbol: str,
    timeframe: str,
    provider: str,
    span: ConfirmedSpan,
    window_start: datetime,
) -> None:
    record(
        conn,
        symbol,
        timeframe,
        provider,
        window_start,
        EmptyHistory(
            verified_from=span.start,
            empty_through=span.end,
            n_confirming_chunks=span.n_confirming,
            reached_request_start=False,
        ),
    )


def reconcile_empty_history(
    conn: Any, timeframe: str, provider: str, *, symbols: list[str] | None = None
) -> dict[str, int]:
    """Make ohlcv_empty_history agree with the recorded answers (D-20).

    A row whose verified span is not covered by a confirmed span is deleted, so the
    range is asked again; a row the answers extend is extended; a confirmed span that
    precedes the symbol's first real bar and has no row is inserted. A derived grid
    timeframe (15m, 1h) is judged by its source's answers and only ever deleted or
    kept: its rows are written by the fetch walk, not derived here. `symbols` limits
    the pass (the pipeline passes its run's names); None considers every row and every
    symbol with a recorded venue no_data answer.
    """
    confirm_tf = _confirmation_timeframe(conn, timeframe)
    derived = timeframe != confirm_tf
    slack = timedelta(days=1) + _interval(confirm_tf)
    venues = load_venue_routes(conn)
    sql = (
        "SELECT symbol, empty_from, empty_through, verified_from FROM ohlcv_empty_history "
        "WHERE timeframe = %s AND provider = %s"
    )
    params: tuple[Any, ...] = (timeframe, provider)
    if symbols is not None:
        sql += " AND symbol = ANY(%s)"
        params += (list(symbols),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = {r[0]: r for r in cur.fetchall()}
    if symbols is not None:
        candidates = set(symbols)
    elif derived:
        candidates = set(rows)
    else:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT symbol FROM ohlcv_request WHERE timeframe = %s "
                "AND what_to_show = 'TRADES' AND outcome = 'no_data' "
                "AND window_start IS NOT NULL AND route <> 'SMART'",
                (timeframe,),
            )
            candidates = {r[0] for r in cur.fetchall()} | set(rows)

    counts = {"kept": 0, "deleted": 0, "inserted": 0, "extended": 0}
    for symbol in sorted(candidates):
        spans = _confirmed_spans(conn, symbol, confirm_tf, venues, slack)
        row = rows.get(symbol)
        if row is not None:
            _, empty_from, empty_through, verified_from = row
            cover = next(
                (
                    s
                    for s in spans
                    if s.start - slack <= verified_from and s.end + slack >= empty_through
                ),
                None,
            )
            if cover is not None:
                if not derived and (cover.end > empty_through or cover.start < verified_from):
                    _record_span(
                        conn, symbol, timeframe, provider, cover, min(cover.start, empty_from)
                    )
                    counts["extended"] += 1
                else:
                    counts["kept"] += 1
                continue
            drop(conn, symbol, timeframe, provider)
            counts["deleted"] += 1
        if derived:
            continue
        pre_history = [s for s in spans if not has_bar_before(conn, symbol, timeframe, s.start)]
        if pre_history:
            span = max(pre_history, key=lambda s: s.end)
            _record_span(conn, symbol, timeframe, provider, span, span.start)
            counts["inserted"] += 1
    return counts
