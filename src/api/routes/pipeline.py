"""Pipeline summary: one row per v3.5 DAG stage (dashboard home).

Each stage is one query function returning an `Envelope` (src/api/envelope.py); the summary
composes the same functions the stage pages call, so the home page and a stage page cannot
disagree. Status is a read of what the writers stored, never a recomputed statistic:

- ingest is judged per (timeframe, provider) feed and reports the worst: `failing` when more than
  `ui.dashboard.ingest_failing_fraction` of a feed's names report consecutive fetch failures,
  `stale` when a feed's newest bar is older than `ui.dashboard.stale_hours` (a fetcher that runs
  but gets no bars still goes stale), so one healthy feed cannot hide a dead one;
- feature and regime are `stale` when their newest bar is older than the bound;
- concept states and research runs are records, not a feed, so they carry no staleness bound;
- `empty` when a stage's own table has no rows, `error` when its query raised (the other stages
  still render), `not_built` for books until phase 188.

The summary is cached for `ui.dashboard.refresh_seconds` behind a lock: any number of open tabs
costs one query set per interval. APR values are re-read on each computation, so a config change
shows within one interval without a restart.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends

from ...core.database_manager import DatabaseManager
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, envelope, newest

router = APIRouter()


async def apr(config: Any, key: str, default: Any) -> Any:
    """A fresh APR read: the shared ConfigService caches forever, the dashboard must not."""
    config.invalidate(key)
    return await config.get(key, default)


async def ingest(db: DatabaseManager) -> Envelope:
    """Coverage ledger per (timeframe, provider): names held, newest bar, last fetch, failing."""
    rows = await db.execute_query(
        "SELECT timeframe, provider, count(*) AS symbols, max(latest_timestamp) AS newest_bar, "
        "max(last_fetched_at) AS last_fetch, "
        "count(*) FILTER (WHERE consecutive_failures > 0) AS failing "
        "FROM ohlcv_coverage GROUP BY timeframe, provider ORDER BY timeframe, provider"
    )
    return envelope("ohlcv_coverage", rows, newest(rows, "newest_bar"))


async def features(db: DatabaseManager) -> Envelope:
    """Newest bar in the live feature store and in the 186-26 rebuild target."""
    rows = await db.execute_query(
        "SELECT 'feature_vectors' AS store, max(bar_ts) AS newest_bar FROM feature_vectors "
        "UNION ALL SELECT 'feature_vectors_v2', max(bar_ts) FROM feature_vectors_v2"
    )
    return envelope("feature_vectors, feature_vectors_v2", rows, newest(rows, "newest_bar"))


async def regimes(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query("SELECT max(ts) AS newest_bar FROM market_regimes")
    return envelope("market_regimes", rows, rows[0]["newest_bar"])


async def measure(db: DatabaseManager) -> Envelope:
    """Concept lifecycle counts; the fresh IC writer's row count and newest row go in meta."""
    rows = await db.execute_query(
        "SELECT status, count(*) AS count FROM concept_registry GROUP BY status ORDER BY status"
    )
    ic = await db.execute_query(
        "SELECT count(*) AS ic_rows, max(computed_at) AS newest FROM feature_ic_scores_v2"
    )
    return envelope(
        "concept_registry, feature_ic_scores_v2", rows, ic[0]["newest"], ic_rows=ic[0]["ic_rows"]
    )


async def research(db: DatabaseManager) -> Envelope:
    rows = await db.execute_query(
        "SELECT status, count(*) AS runs, max(finished_at) AS newest FROM research_run "
        "GROUP BY status ORDER BY status"
    )
    return envelope("research_run", rows, newest(rows, "newest"))


async def books(_db: DatabaseManager) -> Envelope:
    return envelope(None, [], None, detail="BookTracker and BookPositionWriter land with phase 188")


# (stage, query, bounded by staleness). Record stages (measure, research) carry no bound.
_STAGES: list[tuple[str, Callable[[DatabaseManager], Awaitable[Envelope]], bool]] = [
    ("ingest", ingest, True),
    ("feature", features, True),
    ("regime", regimes, True),
    ("measure", measure, False),
    ("research", research, False),
    ("book", books, False),
]

_SEVERITY = {"ok": 0, "stale": 1, "failing": 2}
_cache: dict[str, Any] = {"expires": 0.0, "body": None}
_lock = asyncio.Lock()


def _ingest_status(env: Envelope, stale_after: timedelta, now: datetime, frac: float) -> str:
    """Worst feed: each (timeframe, provider) row is judged on its own failures and newest bar."""
    worst = "ok"
    for row in env["rows"]:
        if int(row["failing"]) / max(int(row["symbols"]), 1) > frac:
            feed = "failing"
        elif row["newest_bar"] is None or now - row["newest_bar"] > stale_after:
            feed = "stale"
        else:
            feed = "ok"
        row["status"] = feed
        worst = max(worst, feed, key=_SEVERITY.__getitem__)
    env["meta"]["failing_rows"] = sum(int(r["failing"]) for r in env["rows"])
    return worst


def _status(
    stage: str, env: Envelope, stale_after: timedelta | None, now: datetime, frac: float
) -> str:
    if stage == "book":
        return "not_built"
    if not env["rows"] or (stale_after is not None and env["as_of"] is None):
        return "empty"
    if stage == "ingest" and stale_after is not None:
        return _ingest_status(env, stale_after, now, frac)
    if stale_after is not None and now - env["as_of"] > stale_after:
        return "stale"
    return "ok"


async def _compute(db: DatabaseManager, config: Any, refresh: int) -> dict[str, Any]:
    stale_after = timedelta(hours=await apr(config, "ui.dashboard.stale_hours", 36))
    frac = await apr(config, "ui.dashboard.ingest_failing_fraction", 0.1)
    now = datetime.now(UTC)
    results = await asyncio.gather(*(query(db) for _, query, _ in _STAGES), return_exceptions=True)
    stages = []
    for (name, _, bounded), result in zip(_STAGES, results, strict=True):
        if isinstance(result, BaseException):
            env = envelope(None, [], None, error=type(result).__name__)
            stages.append({"stage": name, "status": "error", **env})
            continue
        status = _status(name, result, stale_after if bounded else None, now, frac)
        stages.append({"stage": name, "status": status, **result})
    return {
        "generated_at": now,
        "refresh_seconds": refresh,
        "stale_hours": stale_after.total_seconds() / 3600,
        "stages": stages,
    }


@router.get("/config")
async def ui_config(config: Any = Depends(get_config_service)) -> dict[str, Any]:
    """The dashboard-wide APR values every page polls by (one source, not per page)."""
    return {
        "refresh_seconds": await apr(config, "ui.dashboard.refresh_seconds", 60),
        "stale_hours": await apr(config, "ui.dashboard.stale_hours", 36),
    }


@router.get("/summary")
async def summary(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> dict[str, Any]:
    if _cache["body"] is not None and time.monotonic() < _cache["expires"]:
        return _cache["body"]
    async with _lock:  # one computation per interval however many requests arrive at expiry
        if _cache["body"] is None or time.monotonic() >= _cache["expires"]:
            refresh = await apr(config, "ui.dashboard.refresh_seconds", 60)
            body = await _compute(db, config, refresh)
            _cache.update(expires=time.monotonic() + refresh, body=body)
    return _cache["body"]
