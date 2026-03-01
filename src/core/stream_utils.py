"""Utility functions for Redis stream operations.

Common utilities shared across services to reduce duplication.
"""

from __future__ import annotations

import redis.asyncio as redis


async def ensure_consumer_group_with_reset(
    redis_client: redis.Redis,
    stream_name: str,
    group_name: str,
    start_id: str = "$",
    mkstream: bool = True,
) -> None:
    """Ensure a consumer group exists, resetting to current tail if it already exists.

    This is a shared utility for the BUSYGROUP pattern across services:
    - Creates the group if it doesn't exist
    - Resets position to current tail ($) if BUSYGROUP error occurs
    - Prevents stale backlog replay on service restart

    Args:
        redis_client: Redis client instance
        stream_name: Exact stream name (e.g., "indicators:ES:1m")
        group_name: Consumer group name (e.g., "indicator_group")
        start_id: Starting message ID (default: "$" for current tail)
        mkstream: Whether to create stream if it doesn't exist

    Raises:
        redis.ResponseError: Re-raises non-BUSYGROUP errors
    """
    try:
        await redis_client.xgroup_create(
            stream_name, group_name, start_id, mkstream=mkstream
        )
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            # Group already exists - reset to current tail to skip stale backlog
            await redis_client.xgroup_setid(stream_name, group_name, start_id)
        else:
            raise
