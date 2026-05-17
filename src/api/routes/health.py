"""
Health Check Routes

System health monitoring endpoints.
"""

from datetime import UTC, datetime

import aiohttp
import structlog
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "IndicAgent API",
        "version": "2.0.0-clean",
    }


@router.get("/database")
async def database_health(db_manager=Depends(get_db_manager)):
    """Database health check."""
    try:
        # Test database connection
        conn = await db_manager.connection_manager.get_connection()
        _ = await conn.fetchval("SELECT 1")
        await conn.close()

        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}") from e


@router.get("/full")
async def full_health_check(db_manager=Depends(get_db_manager)):
    """Comprehensive health check."""
    health_status = {
        "service": "IndicAgent API",
        "version": "2.0.0-clean",
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {},
    }

    try:
        conn = await db_manager.connection_manager.get_connection()
        await conn.fetchval("SELECT 1")
        await conn.close()
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["components"]["database"] = f"unhealthy: {str(e)}"

    all_healthy = all(status == "healthy" for status in health_status["components"].values())
    health_status["status"] = "healthy" if all_healthy else "degraded"

    if not all_healthy:
        raise HTTPException(status_code=503, detail=health_status)

    return health_status


@router.get("/system")
async def system_health() -> dict:
    """Machine-readable system health: lag, DLQ depth, replay gauge, agent heartbeats."""
    prom_url = "http://localhost:9090/api/v1/query"
    timeout = aiohttp.ClientTimeout(total=3)

    result: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "consumer_lag": {},
        "dlq_depth": None,
        "signal_replay_unresolved": None,
        "agent_heartbeats": {},
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Query 1: consumer lag per agent
        try:
            async with session.get(
                prom_url, params={"query": "persistence_consumer_lag_records"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("data", {}).get("result", []):
                        agent_id = item["metric"].get("agent_id", "unknown")
                        result["consumer_lag"][agent_id] = int(float(item["value"][1]))
        except Exception:
            pass

        # Query 2: DLQ depth (sum of all agent DLQ events)
        try:
            async with session.get(prom_url, params={"query": "agent_dlq_total"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", {}).get("result", [])
                    if items:
                        total = sum(float(i["value"][1]) for i in items)
                        result["dlq_depth"] = int(total)
        except Exception:
            pass

        # Query 3: signal replay unresolved gauge
        try:
            async with session.get(
                prom_url, params={"query": "signal_replay_unresolved_gauge"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", {}).get("result", [])
                    if items:
                        result["signal_replay_unresolved"] = int(float(items[0]["value"][1]))
        except Exception:
            pass

        # Query 4: agent heartbeats (last message timestamp per agent)
        try:
            async with session.get(
                prom_url, params={"query": "agent_last_message_timestamp_seconds"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("data", {}).get("result", []):
                        agent_key = item["metric"].get("agent", "unknown")
                        ts = float(item["value"][1])
                        result["agent_heartbeats"][agent_key] = datetime.fromtimestamp(
                            ts, tz=UTC
                        ).isoformat()
        except Exception:
            pass

    return result
