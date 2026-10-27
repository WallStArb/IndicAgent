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


async def stale_after(config: Any) -> timedelta:
    """How old a newest row may be before a stage, feed or name shows stale."""
    return timedelta(hours=await apr(config, "ui.dashboard.stale_hours", 36))


async def refresh_seconds(config: Any) -> int:
    """The dashboard poll interval, and the TTL of the summary caches."""
    return await apr(config, "ui.dashboard.refresh_seconds", 60)
