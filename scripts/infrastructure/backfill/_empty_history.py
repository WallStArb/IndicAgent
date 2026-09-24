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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.providers.base import EmptyHistory

_REVERIFY_DAYS_KEY = "infra.backfill.empty_history_reverify_days"


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
    """A record younger than the APR re-verification age still suppresses requests."""
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
    pre-history. The tradeable view is exact here: normalize_bars() never fabricates a
    synthetic fill before a symbol's first real bar."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s AND timestamp < %s)",
            (symbol, timeframe, ts),
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
    went stale."""
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


def apply_empty_range(
    gaps: list[tuple[datetime, datetime]],
    empty: EmptyRange | None,
    now: datetime,
    reverify_days: int,
    interval: timedelta,
    min_confirmations: int,
) -> list[tuple[datetime, datetime]]:
    """Gaps with a fresh, sufficiently confirmed range removed; otherwise unchanged.

    `min_confirmations` is the provider's own no-data confirmation threshold
    (infra.ibkr.no_data_confirmation_chunks): a single "no data" answer is not trusted
    (todo 049), so a range confirmed by fewer answers keeps being asked until it is.
    """
    if (
        not gaps
        or empty is None
        or empty.n_confirming_chunks < min_confirmations
        or not is_fresh(empty.verified_at, now, reverify_days)
    ):
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
