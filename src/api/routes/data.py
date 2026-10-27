"""Data page: where the bar data is, by vendor and timeframe, and whether it is clean.

Each section is an `Envelope` read from the table its writer owns: the coverage ledger
(`ohlcv_coverage`, the fetcher), integrity checks (`integrity_monitor`, the bar integrity and
reconciliation audits), restatement flags (`ohlcv_restatement_flag`, the raw capture), listing
ends (`listing_end`) and dividend coverage (`dividend_event_coverage`). Integrity is reported as
each check's most recent run, not a window's pile-up of repeated evaluations. The page reads one
cached summary of all six sections per refresh interval.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ..apr import apr, refresh_seconds, stale_after
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, envelope, gather_sections, newest
from .pipeline import ingest, ingest_status

router = APIRouter()


async def feeds(db: DatabaseManager, config: Any) -> Envelope:
    """The coverage ledger per (timeframe, provider), each row with the status the Pipeline ingest
    card judges it by (same function, same APR bounds), so the two pages cannot disagree."""
    env = await ingest(db)
    frac = await apr(config, "ui.dashboard.ingest_failing_fraction", 0.1)
    ingest_status(env, await stale_after(config), datetime.now(UTC), frac)
    return env


async def failing(db: DatabaseManager) -> Envelope:
    """Names whose last fetches failed, worst first."""
    rows = await db.execute_query(
        "SELECT symbol, timeframe, provider, consecutive_failures, last_fetch_status, "
        "last_fetched_at FROM ohlcv_coverage WHERE consecutive_failures > 0 "
        "ORDER BY consecutive_failures DESC, last_fetched_at DESC, symbol, timeframe"
    )
    return envelope("ohlcv_coverage", rows, newest(rows, "last_fetched_at"))


async def integrity(db: DatabaseManager) -> Envelope:
    """Each (monitor, metric) check's most recent run: subjects failed of subjects evaluated."""
    rows = await db.execute_query(
        "WITH latest AS (SELECT monitor_type, metric_name, max(evaluated_at) AS evaluated_at "
        "FROM integrity_monitor GROUP BY monitor_type, metric_name) "
        "SELECT m.monitor_type, m.metric_name, count(*) FILTER (WHERE NOT m.passed) AS failed, "
        "count(*) AS evaluated, l.evaluated_at "
        "FROM integrity_monitor m JOIN latest l USING (monitor_type, metric_name, evaluated_at) "
        "GROUP BY m.monitor_type, m.metric_name, l.evaluated_at "
        "ORDER BY failed DESC, m.monitor_type, m.metric_name"
    )
    return envelope("integrity_monitor", rows, newest(rows, "evaluated_at"))


async def restatements(db: DatabaseManager) -> Envelope:
    """Vendor restatements flagged by the raw capture and not yet reviewed, newest first."""
    rows = await db.execute_query(
        "SELECT symbol, timeframe, vendor, kind, n_stored, n_changed, share, flagged_at "
        "FROM ohlcv_restatement_flag WHERE reviewed_at IS NULL ORDER BY flagged_at DESC"
    )
    return envelope("ohlcv_restatement_flag", rows, newest(rows, "flagged_at"))


async def listing_ends(db: DatabaseManager) -> Envelope:
    """Names whose listing ended, newest record first."""
    rows = await db.execute_query(
        "SELECT symbol, last_session, reason, recorded_at FROM listing_end "
        "ORDER BY recorded_at DESC"
    )
    return envelope("listing_end", rows, newest(rows, "recorded_at"))


async def dividends(db: DatabaseManager) -> Envelope:
    """Dividend coverage per source: names covered, the span, and the newest check."""
    rows = await db.execute_query(
        "SELECT source, count(*) AS symbols, min(covered_from) AS covered_from, "
        "max(covered_to) AS covered_to, max(checked_at) AS checked_at "
        "FROM dividend_event_coverage GROUP BY source ORDER BY source"
    )
    return envelope("dividend_event_coverage", rows, newest(rows, "checked_at"))


_SECTIONS = {
    "integrity": integrity,
    "failing": failing,
    "restatements": restatements,
    "listing_ends": listing_ends,
    "dividends": dividends,
}


async def _compute(db: DatabaseManager, config: Any) -> dict[str, Any]:
    return await gather_sections(
        {"feeds": feeds(db, config), **{name: fn(db) for name, fn in _SECTIONS.items()}}
    )


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    """All six Data sections in one cached response; a failing section reports meta.error."""
    refresh = await refresh_seconds(config)
    return await cached("data", refresh, lambda: _compute(db, config))
