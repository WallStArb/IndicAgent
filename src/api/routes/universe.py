"""Instruments pages: the universe map and one data passport per name.

`/summary` is one row per instrument with the state the map colours it by, judged here from the
writers' tables (never in the browser): `inactive` (instruments.is_active false), `ended` (a
current listing_end record), `failing` (any feed with consecutive fetch failures), `stale` (its
newest bar across feeds older than `ui.dashboard.stale_hours`), `no_data` (no coverage row) or
`current`. Classification is the point-in-time current assignment (SCH, levels 1 and 2).

`/{symbol}` is that name's passport: identity and eligibility, the coverage ledger per feed, bars
per session per (timeframe, vendor) lane over its whole history (from the tradeable view, so the
holes are visible), the 1d close on the same axis, unreviewed and reviewed restatement flags and
its current tags. The summary is cached for `ui.dashboard.refresh_seconds`, a passport for the
longer `ui.dashboard.passport_refresh_seconds`; a response with a failed section is not cached.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...config.classification_service import current_level_name_sql
from ...core.database_manager import DatabaseManager
from ..apr import passport_refresh_seconds, refresh_seconds, stale_hours
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, all_ok, envelope, gather_sections, newest

router = APIRouter()

# The SCH level names (1 asset class, 2 sector, 3 industry group, 4 industry), point in time.
_LEVELS = {n: current_level_name_sql("i", level=n) for n in range(1, 5)}

# The identity both pages show; the passport adds detail columns, the summary its coverage join.
_IDENTITY_COLUMNS = (
    "i.symbol, i.contract_details->>'name' AS name, i.is_active, i.compute_eligible, "
    "i.compute_eligible_1d, le.last_session AS listing_ended"
)
_IDENTITY_FROM = "instruments i LEFT JOIN listing_end_current le ON le.symbol = i.symbol"

_SUMMARY_SQL = f"""
SELECT {_IDENTITY_COLUMNS},
       {_LEVELS[1]} AS asset_class, {_LEVELS[2]} AS sector,
       c.newest_bar, c.failing_feeds, c.feeds
FROM {_IDENTITY_FROM}
LEFT JOIN (
    SELECT symbol, max(latest_timestamp) AS newest_bar, count(*) AS feeds,
           count(*) FILTER (WHERE consecutive_failures > 0) AS failing_feeds
    FROM ohlcv_coverage GROUP BY symbol
) c ON c.symbol = i.symbol
ORDER BY i.symbol
"""


def name_state(row: dict[str, Any], stale_before: datetime) -> str:
    """The one state a name shows: the first that applies, in this precedence (a name that is
    inactive or ended is that before anything its feeds say). The map's legend orders states by
    need for action instead (`STATE_ORDER` in the dashboard)."""
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
    rows, hours = await asyncio.gather(db.execute_query(_SUMMARY_SQL), stale_hours(config))
    stale_before = datetime.now(UTC) - timedelta(hours=hours)
    for row in rows:
        row["state"] = name_state(row, stale_before)
    return envelope(
        "instruments, ohlcv_coverage, listing_end_current, instrument_classification",
        rows,
        newest(rows, "newest_bar"),
        stale_hours=hours,
    )


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> Envelope:
    """Every instrument with its map state, asset class and sector."""
    return await cached("universe", lambda: refresh_seconds(config), lambda: _summary(db, config))


async def _identity(db: DatabaseManager, symbol: str) -> Envelope:
    levels = ", ".join(f"{sql} AS level_{n}" for n, sql in _LEVELS.items())
    rows = await db.execute_query(
        f"SELECT {_IDENTITY_COLUMNS}, i.contract_details->>'exchange' AS exchange, "
        f"i.live_tradeable, {levels}, le.reason AS listing_end_reason "
        f"FROM {_IDENTITY_FROM} WHERE i.symbol = $1",
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
    """Identity first, so an unknown name 404s on one query instead of scanning bars; an identity
    query that fails is a section error like any other, and the rest still render."""
    identity = (await gather_sections({"identity": _identity(db, symbol)}))["identity"]
    if not identity["rows"] and "error" not in identity["meta"]:
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
    return await cached(
        f"universe:{symbol}",
        lambda: passport_refresh_seconds(config),
        lambda: _passport(db, symbol),
        keep=all_ok,
    )
