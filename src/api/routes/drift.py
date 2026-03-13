"""
Drift Monitor API Routes — QUAL-09/QUAL-10

Provides observability into the KS distribution drift and CUSUM performance
drift state for all active symbols/TFs and setup plugins.

GET /api/drift — Returns current drift state from Redis for all monitored entities.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter()


@lru_cache(maxsize=1)
def _get_settings():
    from ...config.settings import Settings
    return Settings()


def _get_env_prefix() -> str:
    settings = _get_settings()
    return f"{settings.env_name}:" if settings.env_name else ""


def _get_redis_client():
    """Get raw redis client from app dependencies."""
    from .. import dependencies
    if dependencies.redis_manager is None:
        return None
    # RedisStreamsManager wraps the redis client
    return getattr(dependencies.redis_manager, "redis_client", None)


@router.get("")
async def get_drift_state() -> dict[str, Any]:
    """Return current KS and CUSUM drift state from Redis.

    Scans Redis for all drift:ks:* and drift:cusum:* keys and returns
    their current severity values.

    Returns:
        JSON with ks array, cusum array, and last_updated timestamp.
    """
    redis_client = _get_redis_client()
    env_prefix = _get_env_prefix()

    ks_entries: list[dict[str, Any]] = []
    cusum_entries: list[dict[str, Any]] = []

    if redis_client is not None:
        try:
            # Scan KS drift keys: {env_prefix}drift:ks:{symbol}:{tf}
            ks_pattern = f"{env_prefix}drift:ks:*"
            ks_keys = []
            cursor = 0
            while True:
                cursor, batch = await redis_client.scan(cursor, match=ks_pattern, count=100)
                ks_keys.extend(batch)
                if cursor == 0:
                    break

            for key in ks_keys:
                severity = await redis_client.get(key)
                if severity is None:
                    continue
                # Parse symbol and TF from key: {prefix}drift:ks:{symbol}:{tf}
                # Strip env prefix first
                suffix = key[len(env_prefix):]  # drift:ks:{symbol}:{tf}
                parts = suffix.split(":", 3)  # ["drift", "ks", "{symbol}", "{tf}"]
                if len(parts) == 4:
                    ks_entries.append(
                        {
                            "symbol": parts[2],
                            "timeframe": parts[3],
                            "severity": severity,
                            "checked_at": datetime.now(UTC).isoformat(),
                        }
                    )

            # Scan CUSUM drift keys: {env_prefix}drift:cusum:{setup_plugin}
            cusum_pattern = f"{env_prefix}drift:cusum:*"
            cusum_keys = []
            cursor = 0
            while True:
                cursor, batch = await redis_client.scan(cursor, match=cusum_pattern, count=100)
                cusum_keys.extend(batch)
                if cursor == 0:
                    break

            for key in cusum_keys:
                severity = await redis_client.get(key)
                if severity is None:
                    continue
                # Parse setup_plugin from key: {prefix}drift:cusum:{setup_plugin}
                suffix = key[len(env_prefix):]  # drift:cusum:{setup_plugin}
                parts = suffix.split(":", 2)  # ["drift", "cusum", "{setup_plugin}"]
                if len(parts) == 3:
                    # Read additional CUSUM state if available (severity is the value)
                    cusum_entries.append(
                        {
                            "setup_plugin": parts[2],
                            "severity": severity,
                            "s_neg": None,  # Not stored in Redis — would need separate key
                        }
                    )

        except Exception as exc:
            logger.warning("drift endpoint: Redis scan error", error=str(exc))

    return {
        "ks": ks_entries,
        "cusum": cusum_entries,
        "last_updated": datetime.now(UTC).isoformat(),
    }
