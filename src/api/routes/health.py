"""
Health Check Routes

System health monitoring endpoints.
"""

import asyncio
from datetime import UTC, datetime

import aiohttp
import structlog
from fastapi import APIRouter, Depends, HTTPException

from src.observability.metrics import API_HEALTH

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
        async with db_manager.get_connection() as conn:
            _ = await conn.fetchval("SELECT 1")
        API_HEALTH.set(1, {"service": "indicagent-api"})
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as error:
        API_HEALTH.set(0, {"service": "indicagent-api"})
        logger.error("Database health check failed", error=str(error))
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(error)}") from error


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
        async with db_manager.get_connection() as conn:
            await conn.fetchval("SELECT 1")
        health_status["components"]["database"] = "healthy"
    except Exception as error:
        health_status["components"]["database"] = f"unhealthy: {str(error)}"

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

    async def _query(session: aiohttp.ClientSession, query: str) -> list:
        async with session.get(prom_url, params={"query": query}) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("data", {}).get("result", [])
            return []

    async with aiohttp.ClientSession(timeout=timeout) as session:
        lag_items, dlq_items, replay_items, hb_items = await asyncio.gather(
            _query(session, "persistence_consumer_lag_records"),
            _query(session, "agent_dlq_total"),
            _query(session, "signal_replay_unresolved_gauge"),
            _query(session, "agent_last_message_timestamp_seconds"),
            return_exceptions=True,
        )

        if isinstance(lag_items, list):
            for item in lag_items:
                agent_id = item["metric"].get("agent_id", "unknown")
                result["consumer_lag"][agent_id] = int(float(item["value"][1]))

        if isinstance(dlq_items, list) and dlq_items:
            result["dlq_depth"] = int(sum(float(i["value"][1]) for i in dlq_items))

        if isinstance(replay_items, list) and replay_items:
            result["signal_replay_unresolved"] = int(float(replay_items[0]["value"][1]))

        if isinstance(hb_items, list):
            for item in hb_items:
                agent_key = item["metric"].get("agent_id", "unknown")
                ts = float(item["value"][1])
                result["agent_heartbeats"][agent_key] = datetime.fromtimestamp(
                    ts, tz=UTC
                ).isoformat()

    return result
