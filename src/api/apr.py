"""Fresh APR reads for the dashboard's read routes.

The shared ConfigService caches a key forever once read; a dashboard bound (a staleness window, a
poll interval) must follow a config change within one refresh, so every read here invalidates the
key first. One helper per bound that more than one route applies, so the routes cannot drift.
"""

from datetime import timedelta
from typing import Any


async def apr(config: Any, key: str, default: Any) -> Any:
    """A fresh APR read: the shared ConfigService caches forever, the dashboard must not."""
    config.invalidate(key)
    return await config.get(key, default)


async def stale_hours(config: Any) -> float:
    """How many hours old a newest row may be before a stage, feed or name shows stale."""
    return float(await apr(config, "ui.dashboard.stale_hours", 36))


async def stale_after(config: Any) -> timedelta:
    return timedelta(hours=await stale_hours(config))


async def ingest_failing_fraction(config: Any) -> float:
    """The share of a feed's names with fetch failures above which the feed shows failing."""
    return float(await apr(config, "ui.dashboard.ingest_failing_fraction", 0.1))


async def refresh_seconds(config: Any) -> int:
    """The dashboard poll interval, and the TTL of the summary caches."""
    return int(await apr(config, "ui.dashboard.refresh_seconds", 60))


async def passport_refresh_seconds(config: Any) -> int:
    """The instrument passport's poll interval and cache TTL: a name's history changes about once
    a day and each read scans every bar it has, so it is longer than the summaries'."""
    return int(await apr(config, "ui.dashboard.passport_refresh_seconds", 900))


async def integrity_window_hours(config: Any) -> int:
    """Hours before a check's newest row within which each subject's newest result is current."""
    return int(await apr(config, "ui.dashboard.integrity_window_hours", 12))


async def research_rows(config: Any) -> int:
    """The newest research attempts the Research page lists."""
    return int(await apr(config, "ui.dashboard.research_rows", 500))
