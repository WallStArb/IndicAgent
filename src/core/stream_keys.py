"""
Stream key helpers and Kafka topic builders.

Version: 3.2.0
Last Updated: 2026-05-07

Kafka topic builder functions (topic_*) and message_key() are the API.

Removed in Phase 30 (no remaining callers in services or API):
  quote_latest, llm_scores_cache, setup_performance_weights_cache,
  drift_ks, drift_cusum, get_stream_maxlen,
  ticks_pattern, market_pattern, indicators_pattern,
  intelligence_pattern, intelligence_i7_pattern, intelligence_i8_pattern,
  signals_pattern, narratives_pattern

Removed in v2.2 (Phase 44.2 in-process consolidation + Phase 44.3):
  topic_intelligence_i7, topic_winner, topic_attribution

Removed in v3.2 (Phase 44.2 DAG retirement + Phase 80 spec cleanup):
  topic_indicators, topic_signals, topic_audit — retired topics, no live consumers
  topic_quality_gated, topic_regime_gated, topic_tod_adjusted,
  topic_calibrated, topic_ranked — Phase 40 6-stage microservice DAG retired
  topic_data_quality — pipeline.data_quality never created, unused
  topic_intelligence_pipeline_state — topic deleted (Kafka is transport not state store)

Removed in todo 509 (2026-10-26; producers deleted in 185-45 and earlier):
  DLQ topics for roll, feature_writer, signal_writer, lifecycle_writer, signal_tracker,
  llm_writer, transform_graduation and signal_lineage; topic_intelligence_i7_signals;
  the Redis key helpers (prefix, live_tick, market, intelligence, intelligence_i7, signals,
  signals_aggregated, narratives_group, system_events, llm_calls_stream, llm_outcomes_stream,
  intelligence_i8); topic_market_ticks (no producer) and topic_intelligence_shadow (its
  pipeline is gone); the I8 narrative topics (topic_narratives, topic_narratives_group,
  topic_intelligence_i8), whose producer went with the AI stack
Removed in todo 509 item 3 (2026-10-26, ML batch chain deleted): topic_ml_data_quality_alerts,
  topic_ml_discovery_results, topic_ml_orchestrator_dlq
"""

from __future__ import annotations

from src.core.service_utils import TF_SECONDS  # noqa: F401 — re-exported for consumers

# ---------------------------------------------------------------------------
# Kafka topic builders (Phase 30+)
# env_prefix() is period-separated; contrast with the Redis prefix() below.
# ---------------------------------------------------------------------------


def env_prefix(env_name: str) -> str:
    """Return Kafka topic prefix: 'dev.' for env_name='dev', '' for env_name=''."""
    return f"{env_name}." if env_name else ""


def topic_market_bars(env_name: str) -> str:
    """Kafka topic for 1m OHLCV bars from TWS daemon (raw, immutable ground truth)."""
    return f"{env_prefix(env_name)}market.bars"


def topic_market_bars_htf(env_name: str) -> str:
    """Kafka topic for aggregated higher-timeframe bars (5m–1d) from timeframe builder.

    Separate from topic_market_bars (1m only from TWS) to make the DAG acyclic:
    timeframe builder reads market.bars, writes market.bars.htf — no self-reference.
    """
    return f"{env_prefix(env_name)}market.bars.htf"


def topic_bar_aggregator_state(env_name: str) -> str:
    """Kafka compacted topic for BarAggregator state checkpoints.

    Key format: {version}:{symbol}:{tf} (e.g., '1:ESM6:5m')
    Value: msgpack-encoded BarAccumulator state dict (_accumulators, _last_session_boundary_log)
    Topic config: cleanup.policy=compact, min.cleanable.dirty.ratio=0.1,
                  segment.ms=3600000 — set on topic creation, not in code.
    """
    return f"{env_prefix(env_name)}bar.aggregator.state"


def topic_gap_requests(env_name: str) -> str:
    """Kafka topic for BarGapRequest gap-fill events from BarAuditor."""
    return f"{env_prefix(env_name)}market.events.gap_requests"


def topic_contract_updates(env_name: str) -> str:
    """Kafka topic for ContractUpdateEvent messages from ContractMetadataWriterAgent.

    Published after each successful front-month promotion.
    Consumers (e.g. BarAuditor) use this to invalidate contract caches.
    Purpose: latency optimization — live services flush contract cache on receipt.
    NOT required for correctness; services converge within TTL cache cycle (60s).
    """
    return f"{env_prefix(env_name)}market.events.contract_update"


def topic_intelligence(env_name: str) -> str:
    """Kafka topic for I3–I6 intelligence pipeline output (IntelligenceEvent)."""
    return f"{env_prefix(env_name)}intelligence"


def topic_signals_aggregated(env_name: str) -> str:
    """Kafka topic for aggregated/selected signal per bar."""
    return f"{env_prefix(env_name)}signals.aggregated"


def topic_system_events(env_name: str) -> str:
    """Kafka topic for system-level events (roll detection, pipeline control)."""
    return f"{env_prefix(env_name)}system.events"


def topic_cross_asset(env_name: str) -> str:
    """Kafka topic for cross-asset spread features (group-level)."""
    return f"{env_prefix(env_name)}cross_asset"


def topic_intelligence_journal(env_name: str) -> str:
    """Kafka topic for atomic IntelligenceJournal records (all provenance/audit/state)."""
    return f"{env_prefix(env_name)}intelligence.journal"


def topic_feature_vectors(env_name: str) -> str:
    """Kafka topic for FeatureVectorRecord per bar.

    Published by IntelligencePipeline after FeatureFactory.compute().
    Consumed by feature_writer for persistence to feature_vectors hypertable.
    """
    return f"{env_prefix(env_name)}intelligence.feature_vectors"


def topic_market_bars_raw(env_name: str, provider: str) -> str:
    """Raw bars from a single provider before merger routing.

    Each provider publishes to its own isolated topic so the MergerAgent can
    consume all providers and apply quality-gating + primary selection logic.
    Topic pattern: <env>.market.bars.raw.<provider>
    """
    return f"{env_prefix(env_name)}market.bars.raw.{provider}"


def topic_health_events(env_name: str) -> str:
    """Service health state transitions published by ServiceAuditor."""
    return f"{env_prefix(env_name)}system.health.events"


def topic_health_events_dlq(env_name: str) -> str:
    """DLQ for services that exceed the escalation restart threshold."""
    return f"{env_prefix(env_name)}intelligence.service_auditor.journal.dlq"


def topic_signal_dlq(env_name: str) -> str:
    """DLQ for bars feature_vector_pipeline could not process (parse failure or bar timeout)."""
    return f"{env_prefix(env_name)}intelligence.signal.dlq"


def topic_market_data_quality(env_name: str) -> str:
    """ProviderQualityEvent side-channel: provider latency, gaps, failovers.

    Distinct from topic_data_quality (pipeline.data_quality — pipeline-level
    signal gate events). This topic carries per-provider bar delivery telemetry
    for SLA monitoring and ML training signals.
    """
    return f"{env_prefix(env_name)}market.data.quality"


# ---------------------------------------------------------------------------
# ML topics (Phase 56)
# ---------------------------------------------------------------------------


def topic_alert_requests(env_name: str) -> str:
    """Alert requests from any agent to AlertMonitor.

    Any agent can publish alert requests here via BaseDaemon._send_alert().
    AlertMonitor consumes and dispatches to Telegram (CRITICAL) or Discord (HIGH/MEDIUM).
    Consumer group: alerting_consumer
    """
    return f"{env_prefix(env_name)}alert.requests"


def topic_config_updates(env_name: str) -> str:
    """Kafka topic for OPS config change propagation (compacted).

    Topic configuration (created via rpk/admin tools):
      - cleanup.policy=compact
      - min.cleanable.dirty.ratio=0.1
      - partitions=1 (single-partition for global ordering; key is config_key)

    Partition key: config_key (TEXT) - ensures per-key ordering.

    Event contract (JSON payload):
      {
        "schema_version": 1,            # config update event schema version
        "config_key": "regime.prob_min",
        "config_value": "0.35",          # string-encoded; consumer parses by value_type
        "value_type": "float",            # int|float|bool|json|string
        "version": 7,                     # config_state.version after update
        "changed_at": "2026-05-29T12:00:00Z",
        "changed_by": "operator@example.com",
        "operation": "set" | "revert",
        "reason": "optional reason text",
        "redacted": false,
        "correlation_id": "uuid4"
      }

    Tombstone behavior: value=null deletes key from compacted log (not used currently;
    revert publishes a new value, never null). New consumers receive full latest state
    by reading from beginning of compacted topic.

    NOTE: This topic carries OPS config only (hot-reloadable).
    INFRA config (DATABASE_URL, secrets) lives in .env files.
    STRUCT config (plugin tiers, DAG order) lives in code and requires deployment.
    """
    return f"{env_prefix(env_name)}config.updates"


def topic_gap_fill_dlq(env_name: str) -> str:
    """DLQ for gap-fill requests that exhausted retries in bar_auditor_agent.

    BarAuditor routes to this topic after 3 failed retry attempts.
    Payload: {symbol, tf, start_ts, end_ts, retry_count, error}
    Consumer group: bar_auditor_gap_fill_consumer
    """
    return f"{env_prefix(env_name)}gap_fill.dlq"


# ---------------------------------------------------------------------------
# DLQ topics for all agents that parse payloads (Plan 067-07)
# ---------------------------------------------------------------------------


def topic_bar_aggregator_dlq(env_name: str) -> str:
    """Dead-letter queue for malformed bars in bar_aggregator_agent.

    bar_aggregator_agent routes unparseable 1m bar payloads here instead of
    silently dropping them. Enables investigation without data loss.
    Pattern: DLQ per domain (AGG-DLQ).
    """
    return f"{env_prefix(env_name)}bar.aggregator.dlq"


def topic_bar_writer_dlq(env_name: str) -> str:
    """Dead letter queue for BarWriter unparseable payloads."""
    return f"{env_prefix(env_name)}bar.writer.dlq"


def topic_feature_vectors_dlq(env_name: str) -> str:
    """Dead letter queue for feature_vector_writer unparseable FeatureVectorRecord payloads.

    Published by feature_vector_writer when a FeatureVectorRecord cannot be deserialized
    or inserted into feature_vectors. Enables investigation without data loss.
    """
    return f"{env_prefix(env_name)}intelligence.feature_vectors.dlq"


def topic_intelligence_pipeline_dlq(env_name: str) -> str:
    """Dead letter queue for IntelligencePipeline unparseable payloads."""
    return f"{env_prefix(env_name)}intelligence.pipeline.dlq"


def topic_macro_signals(env_name: str) -> str:
    """Kafka topic for macro factor signals.

    Published by: MacroAnalyzer
    Consumed by: IntelligencePipeline (frames["cross_asset"])
    DataWriterAgent writes to: macro_features hypertable

    Topic naming: <env>.macro_signals (dots only, no colons)
    """
    return f"{env_prefix(env_name)}macro_signals"


def message_key(symbol: str, timeframe: str | None = None) -> str:
    """Kafka partition routing key.

    Returns 'SYMBOL:TF' when timeframe is provided, or 'SYMBOL' for tick topics.
    """
    if timeframe:
        return f"{symbol}:{timeframe}"
    return symbol
