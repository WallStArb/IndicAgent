"""
Stream key helpers, Kafka topic builders, and retention policies.

Version: 2.0.0
Last Updated: 2026-03-14
Status: Current ✅

Centralizes stream name construction and maxlen policies to ensure consistency
across publishers and consumers.

Phase 30 dual-run: Kafka topic builder functions (topic_* and env_prefix) are
added at the top. The existing Redis key functions remain intact and will be
removed in Plan 5 once DragonflyDB is retired.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Kafka topic builders (Phase 30+)
# env_prefix() is period-separated; contrast with the Redis prefix() below.
# ---------------------------------------------------------------------------


def env_prefix(env_name: str) -> str:
    """Return Kafka topic prefix: 'dev.' for env_name='dev', '' for env_name=''."""
    return f"{env_name}." if env_name else ""


def topic_market_ticks(env_name: str) -> str:
    """Kafka topic for raw tick data from TWS daemon."""
    return f"{env_prefix(env_name)}market.ticks"


def topic_market_bars(env_name: str) -> str:
    """Kafka topic for OHLCV bars (all timeframes)."""
    return f"{env_prefix(env_name)}market.bars"


def topic_indicators(env_name: str) -> str:
    """Kafka topic for I1 technical indicator output."""
    return f"{env_prefix(env_name)}indicators"


def topic_intelligence(env_name: str) -> str:
    """Kafka topic for I3–I6 intelligence pipeline output (IntelligenceEvent)."""
    return f"{env_prefix(env_name)}intelligence"


def topic_intelligence_i7(env_name: str) -> str:
    """Kafka topic for I7 signal scorecard (all_ranked per bar)."""
    return f"{env_prefix(env_name)}intelligence.i7"


def topic_intelligence_i8(env_name: str) -> str:
    """Kafka topic for I8 AI narrative metadata per bar."""
    return f"{env_prefix(env_name)}intelligence.i8"


def topic_signals(env_name: str) -> str:
    """Kafka topic for individual I7 signals (pre-aggregation)."""
    return f"{env_prefix(env_name)}signals"


def topic_signals_aggregated(env_name: str) -> str:
    """Kafka topic for aggregated/selected signal per bar."""
    return f"{env_prefix(env_name)}signals.aggregated"


def topic_narratives(env_name: str) -> str:
    """Kafka topic for I8 narrative output."""
    return f"{env_prefix(env_name)}narratives"


def topic_narratives_group(env_name: str) -> str:
    """Kafka topic for I8 group synthesis narrative output."""
    return f"{env_prefix(env_name)}narratives.group"


def topic_llm_calls(env_name: str) -> str:
    """Kafka topic for LLM call audit log (every call: success + failure + counterfactual)."""
    return f"{env_prefix(env_name)}llm.calls"


def topic_llm_outcomes(env_name: str) -> str:
    """Kafka topic for signal lifecycle exits with outcome/pnl_r/mae/mfe."""
    return f"{env_prefix(env_name)}llm.outcomes"


def message_key(symbol: str, timeframe: str | None = None) -> str:
    """Kafka partition routing key.

    Returns 'SYMBOL:TF' when timeframe is provided, or 'SYMBOL' for tick topics.
    """
    if timeframe:
        return f"{symbol}:{timeframe}"
    return symbol


# ---------------------------------------------------------------------------
# Redis key helpers (dual-run: kept through Plan 4, removed in Plan 5)
# prefix() below uses colon-separated format for backwards compatibility.
# ---------------------------------------------------------------------------


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


def system_events(env_prefix: str) -> str:
    """Global stream for system-level events (e.g. pipeline_reset sentinel).

    Intentionally excluded from pipeline_reset _REDIS_PATTERNS so it survives
    the stream clear — reconnecting SSE clients still see the event via snapshot.
    """
    return f"{env_prefix}system:events"


def llm_scores_cache(env_prefix: str, call_type: str, regime: str) -> str:
    """Redis HSET key for model score blobs keyed by model name."""
    return f"{env_prefix}llm_scores:{call_type}:{regime}"


def setup_performance_weights_cache(env_prefix: str) -> str:
    """Redis string key for JSON perf multiplier dict keyed by setup_plugin.

    Written nightly by run_setup_performance_update().
    Read at startup + every 60 min by signal_generator_service.
    Format: {"trad_TrendFollowing": 0.85, "trad_MeanReversion": 1.15, ...}
    Only setups with sample_size >= 30 appear (FEED-02 promotion gate).
    """
    return f"{env_prefix}setup_performance:weights"


def get_stream_maxlen(
    timeframe: str,
    kind: Literal[
        "ticks", "market", "indicators", "intelligence",
        "intelligence_i7", "intelligence_i8",
        "signals", "signals_aggregated", "narratives", "narratives_group",
        "llm_calls", "llm_outcomes", "system_events",
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
    if kind == "system_events":
        return 50
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


def drift_ks(env_prefix: str, symbol: str, tf: str) -> str:
    """Redis key for KS drift state per symbol/TF. Written by drift_monitor_service."""
    return f"{env_prefix}drift:ks:{symbol}:{tf}"


def drift_cusum(env_prefix: str, setup_plugin: str) -> str:
    """Redis key for CUSUM drift state per setup_plugin. Written by CUSUMMonitor."""
    return f"{env_prefix}drift:cusum:{setup_plugin}"
