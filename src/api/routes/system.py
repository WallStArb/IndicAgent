"""System page: indicagent systemd units and timers, and recent DLQ traffic.

Unit state comes straight from `systemctl ... --output=json` rather than the service auditor's
registry: src/ does not import services/ (ring rule), and systemd is the source of truth for
what is installed and running. A oneshot that is `inactive`/`dead` between runs is normal;
`failed` is the state to act on.
"""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...core.database_manager import DatabaseManager
from ..apr import apr, refresh_seconds
from ..dependencies import get_config_service, get_db_manager
from ..envelope import Envelope, envelope, newest
from ..utils import translate_db_errors

router = APIRouter()

_UNIT_GLOB = "indicagent-*"
# Unit state is cached for one refresh interval so N tabs polling /system do not fork 2N
# systemctl processes.
_units_cache: dict[str, Any] = {"expires": 0.0, "body": None}


async def _systemctl_json(*args: str) -> list[dict[str, Any]]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            *args,
            _UNIT_GLOB,
            "--all",
            "--output=json",
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:  # no systemd (CI, containers)
        raise HTTPException(status_code=503, detail="systemctl is not available") from error
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=f"systemctl failed: {err.decode().strip()}")
    return json.loads(out or b"[]")


def _usec(value: int | None) -> datetime | None:
    """systemd realtime microseconds to a UTC datetime; 0 means never."""
    return datetime.fromtimestamp(value / 1e6, tz=UTC) if value else None


@router.get("/units")
async def units(config: Any = Depends(get_config_service)) -> Envelope:
    if _units_cache["body"] is not None and time.monotonic() < _units_cache["expires"]:
        return _units_cache["body"]
    services, timers = await asyncio.gather(
        _systemctl_json("list-units", "--type=service"),
        _systemctl_json("list-timers"),
    )
    timer_by_service = {t["activates"]: t for t in timers}
    rows = []
    for unit in services:
        timer = timer_by_service.get(unit["unit"])
        rows.append(
            {
                "unit": unit["unit"],
                "active": unit["active"],
                "sub": unit["sub"],
                "description": unit["description"],
                "timer": timer["unit"] if timer else None,
                "last_run": _usec(timer["last"]) if timer else None,
                "next_run": _usec(timer["next"]) if timer else None,
            }
        )
    body = envelope("systemd", rows, datetime.now(UTC))
    ttl = await refresh_seconds(config)
    _units_cache.update(expires=time.monotonic() + ttl, body=body)
    return body


@router.get("/dlq")
@translate_db_errors
async def dlq(
    db: DatabaseManager = Depends(get_db_manager),
    config: Any = Depends(get_config_service),
) -> Envelope:
    days = await apr(config, "ui.dashboard.dlq_window_days", 7)
    rows = await db.execute_query(
        "SELECT dlq_topic, error_type, count(*) AS events, max(routed_at) AS newest, "
        "count(*) FILTER (WHERE quarantined) AS quarantined "
        "FROM dlq_events WHERE routed_at > $1 "
        "GROUP BY dlq_topic, error_type ORDER BY newest DESC",
        datetime.now(UTC) - timedelta(days=days),
    )
    return envelope("dlq_events", rows, newest(rows, "newest"), window_days=days)
