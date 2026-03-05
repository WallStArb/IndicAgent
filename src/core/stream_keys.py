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


def quote_latest(env_prefix: str, symbol: str) -> str:
    """Hash key for latest bid/ask snapshot. Written by AsyncTickPublisher."""
    return f"{env_prefix}price:{symbol}:latest"


def market(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}market:{symbol}:{timeframe}"


def indicators(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}indicators:{symbol}:{timeframe}"


def intelligence(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}intelligence:{symbol}:{timeframe}"


def intelligence_i7(env_prefix: str, symbol: str, timeframe: str) -> str:
    """Enrichment stream: signal_generator publishes all_ranked per bar."""
    return f"{env_prefix}intelligence_i7:{symbol}:{timeframe}"


def intelligence_i8(env_prefix: str, symbol: str, timeframe: str) -> str:
    """Enrichment stream: ai_narrative publishes narrative metadata per bar."""
    return f"{env_prefix}intelligence_i8:{symbol}:{timeframe}"


def signals(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}signals:{symbol}:{timeframe}"


def signals_aggregated(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}signals:{symbol}:{timeframe}:aggregated"


def narratives(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}narratives:{symbol}:{timeframe}"


def narratives_group(env_prefix: str, group_name: str) -> str:
    return f"{env_prefix}narratives:group:{group_name}"


def llm_calls_stream(env_prefix: str) -> str:
    """Stream written by ai_narrative_service after every LLM call."""
    return f"{env_prefix}llm_calls:stream"


def llm_outcomes_stream(env_prefix: str) -> str:
    """Stream written by signal_lifecycle_service on signal exit for outcome back-fill."""
    return f"{env_prefix}llm_outcomes:stream"


def llm_scores_cache(env_prefix: str, call_type: str, regime: str) -> str:
    """Redis HSET key for model score blobs keyed by model name."""
    return f"{env_prefix}llm_scores:{call_type}:{regime}"


def get_stream_maxlen(
    timeframe: str,
    kind: Literal[
        "ticks", "market", "indicators", "intelligence",
        "intelligence_i7", "intelligence_i8",
        "signals", "signals_aggregated", "narratives", "narratives_group",
        "llm_calls", "llm_outcomes",
    ],
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
    if kind in {"intelligence_i7", "intelligence_i8"}:
        return 200
    if kind == "signals":
        return 500
    if kind == "signals_aggregated":
        return 200
    if kind == "narratives":
        return 100
    if kind == "narratives_group":
        return 50
    if kind == "llm_calls":
        return 500
    if kind == "llm_outcomes":
        return 200
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


def intelligence_i7_pattern(env_prefix: str) -> str:
    return f"{env_prefix}intelligence_i7:*:*"


def intelligence_i8_pattern(env_prefix: str) -> str:
    return f"{env_prefix}intelligence_i8:*:*"


def signals_pattern(env_prefix: str) -> str:
    return f"{env_prefix}signals:*:*"


def patterns_pattern(env_prefix: str) -> str:
    return f"{env_prefix}patterns:*"


def narratives_pattern(env_prefix: str) -> str:
    return f"{env_prefix}narratives:*:*"
