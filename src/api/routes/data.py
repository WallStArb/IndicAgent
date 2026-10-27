"""Data page: where the bar data is, by vendor and timeframe, and whether it is clean.

Each section is an `Envelope` read from the table its writer owns: the coverage ledger
(`ohlcv_coverage`, the fetcher), integrity checks (`integrity_monitor`, the bar integrity and
reconciliation audits), restatement flags (`ohlcv_restatement_flag`, the raw capture), listing
ends (`listing_end`) and dividend coverage (`dividend_event_coverage`). Integrity is reported as
each check's current state: every subject's newest result within `ui.dashboard.integrity_window_hours`
of the check's own newest row (a run commits per row, so it spans many timestamps; a check that
last ran weeks ago still shows its last run). The page reads one cached summary of all six
sections per refresh interval.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ..apr import integrity_window_hours, refresh_seconds
from ..cache import cached
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, all_ok, envelope, gather_sections, newest
from .pipeline import judged_ingest

router = APIRouter()


async def failing(db: DatabaseManager) -> Envelope:
    """Names whose last fetches failed, worst first."""
    rows = await db.execute_query(
        "SELECT symbol, timeframe, provider, consecutive_failures, last_fetch_status, "
        "last_fetched_at FROM ohlcv_coverage WHERE consecutive_failures > 0 "
        "ORDER BY consecutive_failures DESC, last_fetched_at DESC, symbol, timeframe"
    )
    return envelope("ohlcv_coverage", rows, newest(rows, "last_fetched_at"))


_INTEGRITY_SQL = """
WITH latest AS (
    SELECT monitor_type, metric_name, max(evaluated_at) AS evaluated_at
    FROM integrity_monitor GROUP BY monitor_type, metric_name
), current AS (
    SELECT DISTINCT ON (m.monitor_type, m.metric_name, m.subject)
           m.monitor_type, m.metric_name, m.passed
    FROM integrity_monitor m JOIN latest l USING (monitor_type, metric_name)
    WHERE m.evaluated_at > l.evaluated_at - make_interval(hours => $1)
    ORDER BY m.monitor_type, m.metric_name, m.subject, m.evaluated_at DESC
)
SELECT c.monitor_type, c.metric_name, count(*) FILTER (WHERE NOT c.passed) AS failed,
       count(*) AS evaluated, l.evaluated_at
FROM current c JOIN latest l USING (monitor_type, metric_name)
GROUP BY c.monitor_type, c.metric_name, l.evaluated_at
ORDER BY failed DESC, c.monitor_type, c.metric_name
"""


async def integrity(db: DatabaseManager, config: Any) -> Envelope:
    """Each (monitor, metric) check's current state: subjects failing of subjects evaluated."""
    hours = await integrity_window_hours(config)
    rows = await db.execute_query(_INTEGRITY_SQL, hours)
    return envelope("integrity_monitor", rows, newest(rows, "evaluated_at"), window_hours=hours)


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
    "failing": failing,
    "restatements": restatements,
    "listing_ends": listing_ends,
    "dividends": dividends,
}


async def _compute(db: DatabaseManager, config: Any) -> dict[str, Any]:
    return await gather_sections(
        {
            "feeds": judged_ingest(db, config),
            "integrity": integrity(db, config),
            **{name: fn(db) for name, fn in _SECTIONS.items()},
        }
    )


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    """All six Data sections in one cached response; a failing section reports meta.error."""
    return await cached(
        "data", lambda: refresh_seconds(config), lambda: _compute(db, config), keep=all_ok
    )
