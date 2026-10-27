"""Instruments pages: the universe map and one data passport per name.

`/summary` is one row per instrument with the state the map colours it by, judged here from the
writers' tables (never in the browser): `inactive` (instruments.is_active false), `ended` (a
current listing_end record), `failing` (any feed with consecutive fetch failures), `stale` (its
newest bar across feeds older than `ui.dashboard.stale_hours`), `no_data` (no coverage row) or
`current`. Classification is the point-in-time current assignment (SCH, levels 1 and 2).

`/{symbol}` is that name's passport: identity and eligibility, the coverage ledger per feed, bars
per session per (timeframe, vendor) lane over its whole history (from the tradeable view, so the
holes are visible), the 1d close on the same axis, unreviewed and reviewed restatement flags and
its current tags. Both are cached for one refresh interval.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...config.classification_service import current_level_name_sql
from ...core.database_manager import DatabaseManager
from ..apr import apr, refresh_seconds, stale_after
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, envelope, gather_sections, newest

router = APIRouter()

_ASSET_CLASS = current_level_name_sql("i", level=1)
_SECTOR = current_level_name_sql("i", level=2)

_SUMMARY_SQL = f"""
SELECT i.symbol, i.contract_details->>'name' AS name, i.is_active,
       i.compute_eligible, i.compute_eligible_1d,
       {_ASSET_CLASS} AS asset_class, {_SECTOR} AS sector,
       c.newest_bar, c.failing_feeds, c.feeds,
       le.last_session AS listing_ended
FROM instruments i
LEFT JOIN (
    SELECT symbol, max(latest_timestamp) AS newest_bar, count(*) AS feeds,
           count(*) FILTER (WHERE consecutive_failures > 0) AS failing_feeds
    FROM ohlcv_coverage GROUP BY symbol
) c ON c.symbol = i.symbol
LEFT JOIN listing_end_current le ON le.symbol = i.symbol
ORDER BY i.symbol
"""


def name_state(row: dict[str, Any], stale_before: datetime) -> str:
    """The one state a name shows, most severe first."""
    if not row["is_active"]:
        return "inactive"
    if row["listing_ended"] is not None:
        return "ended"
    if not row["feeds"]:
        return "no_data"
    if row["failing_feeds"]:
        return "failing"
    if row["newest_bar"] is None or row["newest_bar"] < stale_before:
        return "stale"
    return "current"


async def _summary(db: DatabaseManager, config: Any) -> Envelope:
    rows = await db.execute_query(_SUMMARY_SQL)
    stale = await stale_after(config)
    stale_before = datetime.now(UTC) - stale
    for row in rows:
        row["state"] = name_state(row, stale_before)
    return envelope(
        "instruments, ohlcv_coverage, listing_end_current, instrument_classification",
        rows,
        newest(rows, "newest_bar"),
        stale_hours=stale.total_seconds() / 3600,
    )


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> Envelope:
    """Every instrument with its map state, asset class and sector."""
    refresh = await refresh_seconds(config)
    return await cached("universe", refresh, lambda: _summary(db, config))


async def _identity(db: DatabaseManager, symbol: str) -> Envelope:
    levels = ", ".join(f"{current_level_name_sql('i', level=n)} AS level_{n}" for n in range(1, 5))
    rows = await db.execute_query(
        f"SELECT i.symbol, i.contract_details->>'name' AS name, "
        f"i.contract_details->>'exchange' AS exchange, i.is_active, i.compute_eligible, "
        f"i.compute_eligible_1d, i.live_tradeable, {levels}, "
        f"le.last_session AS listing_ended, le.reason AS listing_end_reason "
        f"FROM instruments i LEFT JOIN listing_end_current le ON le.symbol = i.symbol "
        f"WHERE i.symbol = $1",
        symbol,
    )
    return envelope("instruments, instrument_classification, listing_end_current", rows, None)


async def _coverage(db: DatabaseManager, symbol: str) -> Envelope:
    rows = await db.execute_query(
        "SELECT timeframe, provider, earliest_timestamp AS earliest, latest_timestamp AS latest, "
        "row_count AS bars, last_fetched_at AS last_fetch, last_fetch_status, "
        "consecutive_failures AS failures "
        "FROM ohlcv_coverage WHERE symbol = $1 ORDER BY timeframe, provider",
        symbol,
    )
    return envelope("ohlcv_coverage", rows, newest(rows, "latest"))


async def _lanes(db: DatabaseManager, symbol: str) -> Envelope:
    """Bars per UTC session per (timeframe, vendor), one row per lane with parallel arrays."""
    rows = await db.execute_query(
        "SELECT timeframe, vendor, array_agg(session ORDER BY session) AS sessions, "
        "array_agg(bars ORDER BY session) AS bars FROM ("
        "  SELECT timeframe, vendor, (timestamp AT TIME ZONE 'UTC')::date AS session, "
        "  count(*) AS bars FROM market_data_ohlcv_tradeable WHERE symbol = $1 "
        "  GROUP BY 1, 2, 3"
        ") s GROUP BY timeframe, vendor ORDER BY timeframe, vendor",
        symbol,
    )
    last = max((r["sessions"][-1] for r in rows if r["sessions"]), default=None)
    as_of = datetime.combine(last, datetime.min.time(), UTC) if last else None
    return envelope("market_data_ohlcv_tradeable", rows, as_of)


# The close line is drawn from daily bars: one point per session for any asset class.
_CLOSE_TIMEFRAME = "1d"


async def _closes(db: DatabaseManager, symbol: str) -> Envelope:
    rows = await db.execute_query(
        "SELECT array_agg(timestamp ORDER BY timestamp) AS t, "
        "array_agg(close ORDER BY timestamp) AS close "
        "FROM market_data_ohlcv_tradeable WHERE symbol = $1 AND timeframe = $2",
        symbol,
        _CLOSE_TIMEFRAME,
    )
    series = rows[0] if rows and rows[0]["t"] else {"t": [], "close": []}
    as_of = series["t"][-1] if series["t"] else None
    return envelope("market_data_ohlcv_tradeable", [series], as_of, timeframe=_CLOSE_TIMEFRAME)


async def _restatements(db: DatabaseManager, symbol: str) -> Envelope:
    rows = await db.execute_query(
        "SELECT timeframe, vendor, kind, n_changed, n_stored, share, flagged_at, reviewed_at "
        "FROM ohlcv_restatement_flag WHERE symbol = $1 ORDER BY flagged_at DESC",
        symbol,
    )
    return envelope("ohlcv_restatement_flag", rows, newest(rows, "flagged_at"))


async def _tags(db: DatabaseManager, symbol: str) -> Envelope:
    rows = await db.execute_query(
        "SELECT tag, source, weight, discovery_state, assigned_at FROM instrument_tags "
        "WHERE symbol = $1 AND valid_to IS NULL ORDER BY source, weight DESC NULLS LAST, tag",
        symbol,
    )
    return envelope("instrument_tags", rows, newest(rows, "assigned_at"))


_SECTIONS = {
    "coverage": _coverage,
    "lanes": _lanes,
    "closes": _closes,
    "restatements": _restatements,
    "tags": _tags,
}


async def _passport(db: DatabaseManager, symbol: str) -> dict[str, Any]:
    identity = await _identity(db, symbol)
    if not identity["rows"]:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found")
    sections = await gather_sections({name: fn(db, symbol) for name, fn in _SECTIONS.items()})
    return {"identity": identity, **sections}


@router.get("/{symbol}")
async def passport(
    symbol: str,
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    """One name's data passport; a failing section reports meta.error, an unknown name 404s."""
    symbol = symbol.upper()
    # A name's history changes about once a day, and reading it scans every bar the name has
    # (about 2 s for a 26-year name), so the passport keeps its own longer TTL.
    ttl = await apr(config, "ui.dashboard.passport_refresh_seconds", 900)
    return await cached(f"universe:{symbol}", ttl, lambda: _passport(db, symbol))
