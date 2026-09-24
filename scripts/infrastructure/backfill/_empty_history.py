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

from src.providers.ibkr import EmptyHistory

_REVERIFY_DAYS_KEY = "infra.backfill.empty_history_reverify_days"


@dataclass(frozen=True)
class EmptyRange:
    empty_from: datetime
    empty_through: datetime
    verified_at: datetime

    def is_fresh(self, now: datetime, reverify_days: int) -> bool:
        return now - self.verified_at < timedelta(days=reverify_days)


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
            "SELECT symbol, timeframe, empty_from, empty_through, verified_at "
            "FROM ohlcv_empty_history WHERE provider = %s",
            (provider,),
        )
        return {(r[0], r[1]): EmptyRange(r[2], r[3], r[4]) for r in cur.fetchall()}


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
) -> None:
    """Upsert the empty range a pre-history window's walk ended in.

    `empty_from` is the window start: the part older than `observed.verified_from` is
    inferred when the walk stopped on its confirmation threshold, exactly the range the
    walk never requests anyway; `verified_from` and `reached_request_start` keep the two
    parts distinguishable.
    """
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
                min(window_start, observed.verified_from),
                observed.empty_through,
                observed.verified_from,
                observed.n_confirming_chunks,
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


@dataclass(frozen=True)
class ProviderHead:
    """ohlcv_provider_head row (migration 355). head_ts None = lookup failed = no floor."""

    head_ts: datetime | None
    verified_at: datetime

    def is_fresh(self, now: datetime, reverify_days: int) -> bool:
        return now - self.verified_at < timedelta(days=reverify_days)


def load_heads(conn: Any, provider: str) -> dict[str, ProviderHead]:
    """Every recorded head for `provider`, keyed by symbol, fresh or stale."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, head_ts, verified_at FROM ohlcv_provider_head WHERE provider = %s",
            (provider,),
        )
        return {r[0]: ProviderHead(r[1], r[2]) for r in cur.fetchall()}


def record_head(
    conn: Any, symbol: str, provider: str, head_ts: datetime | None, error: str | None
) -> ProviderHead:
    """Upsert a head lookup's outcome, success or failure, and return it."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ohlcv_provider_head (symbol, provider, head_ts, lookup_error, verified_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (symbol, provider) DO UPDATE SET
                head_ts = EXCLUDED.head_ts,
                lookup_error = EXCLUDED.lookup_error,
                verified_at = EXCLUDED.verified_at
            RETURNING head_ts, verified_at
            """,
            (symbol, provider, head_ts, None if head_ts else (error or "no head timestamp")),
        )
        row = cur.fetchone()
    conn.commit()
    return ProviderHead(row[0], row[1])


def before_head(head_ts: datetime, interval: timedelta) -> EmptyRange:
    """The range a head timestamp rules out: everything strictly older than it.

    Expressed as an EmptyRange so `subtract()` applies it; `verified_at` is unused here.
    """
    return EmptyRange(datetime.min.replace(tzinfo=head_ts.tzinfo), head_ts - interval, head_ts)
