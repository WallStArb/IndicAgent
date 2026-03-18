"""
Stream key helpers and Kafka topic builders.

Version: 3.0.0
Last Updated: 2026-03-14
Status: Phase 30 complete — DragonflyDB retired ✅

Kafka topic builder functions (topic_*) are the primary API.
Legacy Redis key helpers retained for sse.py backward compat:
  live_tick, market, indicators, intelligence, intelligence_i7, intelligence_i8,
  signals, signals_aggregated, narratives, narratives_group, system_events,
  llm_calls_stream, llm_outcomes_stream, prefix, patterns_pattern

Removed in Phase 30 (no remaining callers in services or API):
  quote_latest, llm_scores_cache, setup_performance_weights_cache,
  drift_ks, drift_cusum, get_stream_maxlen,
  ticks_pattern, market_pattern, indicators_pattern,
  intelligence_pattern, intelligence_i7_pattern, intelligence_i8_pattern,
  signals_pattern, narratives_pattern
"""

from __future__ import annotations

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


def topic_system_events(env_name: str) -> str:
    """Kafka topic for system-level events (roll detection, pipeline control)."""
    return f"{env_prefix(env_name)}system.events"


def topic_cross_asset(env_name: str) -> str:
    """Kafka topic for cross-asset spread features (group-level)."""
    return f"{env_prefix(env_name)}cross_asset"


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


# Pattern helpers (ticks_pattern, market_pattern, etc.) removed in Phase 30.
# No remaining callers in services/ or src/api/.
# drift_ks and drift_cusum removed in Phase 30 — replaced by drift_state DB table.
# See production/migrations/030_drift_state.sql.
