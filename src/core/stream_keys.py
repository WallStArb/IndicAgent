"""
Stream key helpers and retention policies

Version: 1.0.0
Last Updated: 2025-08-09
Status: Current ✅

Centralizes stream name construction and maxlen policies to ensure consistency
across publishers and consumers.
"""

from __future__ import annotations

from typing import Literal


def prefix(env_name: str) -> str:
    return f"{env_name}:" if env_name else ""


def live_tick(env_prefix: str, symbol: str) -> str:
    return f"{env_prefix}ticks:{symbol}:live"


def market(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}market:{symbol}:{timeframe}"


def indicators(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}indicators:{symbol}:{timeframe}"


def intelligence(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}intelligence:{symbol}:{timeframe}"


def get_stream_maxlen(
    timeframe: str, kind: Literal["ticks", "market", "indicators", "intelligence"]
) -> int:
    if kind == "ticks":
        return 20000
    if kind == "market":
        if timeframe == "1m":
            return 2000
        if timeframe in {"5m", "15m", "1h"}:
            return 1000
        return 500
    if kind == "indicators":
        return 1000
    if kind == "intelligence":
        return 1000
    return 1000


# Pattern helpers for wildcard subscriptions
def ticks_pattern(env_prefix: str) -> str:
    return f"{env_prefix}ticks:*:live"


def market_pattern(env_prefix: str) -> str:
    return f"{env_prefix}market:*:*"


def indicators_pattern(env_prefix: str) -> str:
    return f"{env_prefix}indicators:*:*"


def intelligence_pattern(env_prefix: str) -> str:
    return f"{env_prefix}intelligence:*:*"


def patterns_pattern(env_prefix: str) -> str:
    return f"{env_prefix}patterns:*"
