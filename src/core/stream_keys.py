"""
Stream key helpers and Kafka topic builders.

Version: 3.2.0
Last Updated: 2026-05-07

Kafka topic builder functions (topic_*) are the primary API.
Legacy Redis key helpers retained for sse.py backward compat:
  live_tick, market, indicators, intelligence, intelligence_i8,
  signals, signals_aggregated, narratives, narratives_group, system_events,
  llm_calls_stream, llm_outcomes_stream, prefix, patterns_pattern

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


def topic_market_ticks(env_name: str) -> str:
    """Kafka topic for raw tick data from TWS daemon."""
    return f"{env_prefix(env_name)}market.ticks"


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


def topic_contracts_updated(env_name: str) -> str:
    """Kafka topic for contract hot-reload events broadcast by roll-batch.

    Published by roll_batch.py after a successful front-month promotion.
    Daemons that cache get_active_contracts() at startup subscribe here to
    self-heal on futures rolls without a manual service restart.
    """
    return f"{env_prefix(env_name)}contracts.updated"


def topic_intelligence(env_name: str) -> str:
    """Kafka topic for I3–I6 intelligence pipeline output (IntelligenceEvent)."""
    return f"{env_prefix(env_name)}intelligence"


def topic_intelligence_i8(env_name: str) -> str:
    """Kafka topic for I8 AI narrative metadata per bar."""
    return f"{env_prefix(env_name)}intelligence.i8"


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


def topic_intelligence_journal(env_name: str) -> str:
    """Kafka topic for atomic IntelligenceJournal records (all provenance/audit/state)."""
    return f"{env_prefix(env_name)}intelligence.journal"


def topic_feature_vectors(env_name: str) -> str:
    """Kafka topic for FeatureVectorRecord per bar.

    Published by IntelligencePipeline after FeatureFactory.compute().
    Consumed by feature_writer for persistence to feature_vectors hypertable.
    """
    return f"{env_prefix(env_name)}intelligence.feature_vectors"


def topic_intelligence_i7_signals(env_name: str) -> str:
    """Kafka topic carrying all ranked I7 signals per bar (pre-ledger write).

    Published by IntelligencePipeline after each bar's I7 run.
    Consumed by SignalWriter for signal_ledger persistence.
    Payload schema: {symbol, tf, bar_ts, computed_at, signals: list[dict]}
    """
    return f"{env_prefix(env_name)}intelligence.i7.signals"


def topic_alpha_events(env_name: str) -> str:
    """Kafka topic for alpha emission events from AlphaEngine v3.0.

    Published by AlphaPublisher (services/alpha_publisher.py) when ensemble alpha score
    crosses the per-TF emission threshold (alpha.quant.threshold.{tf} APR key) and
    the effective_N gate is met (alpha.ensemble.effective_n_gate).

    Payload schema: see alpha_events DB table (production/migrations/168_ensemble_tables.sql).
    topic pattern: <env>.alpha.events (dots only, via stream_keys.py).
    """
    return f"{env_prefix(env_name)}alpha.events"


def topic_intelligence_shadow(env_name: str) -> str:
    """Kafka topic for shadow rollout output from IntelligencePipeline.

    Activated via INTELLIGENCE_PIPELINE_SHADOW=1 env var. The agent publishes
    here instead of the canonical intelligence topic while running in shadow mode.
    Consumer group: intelligence_pipeline_shadow (manual inspection only).
    """
    return f"{env_prefix(env_name)}intelligence.shadow"


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
    """DLQ for signals that fail CIS assertion before publish.

    Published by intelligence_pipeline_agent when a ranked signal has
    raw_cis_score IS None or filtered_cis_score IS None — indicates a
    regression in the CIS stamping path. Never lets null-CIS signals
    enter intelligence.i7.signals.
    """
    return f"{env_prefix(env_name)}intelligence.signal.dlq"


def topic_signal_audit(env_name: str) -> str:
    """Audit events from signal_auditor_agent.

    Receives SignalCoverageGapEvent payloads when a (symbol, tf) pair had
    zero signals in the last completed trading session. Future: intelligence
    pipeline subscribes to trigger bar replay for covered symbols.
    """
    return f"{env_prefix(env_name)}intelligence.signal.audit"


def topic_signal_metrics(env_name: str) -> str:
    """Kafka topic for SignalMetricsAnalyzer output events.

    Consumed by SignalMetricsWriter to upsert signal_metrics,
    signal_metrics_ic, and signal_metrics_dq_failures tables.
    """
    return f"{env_prefix(env_name)}intelligence.signal_metrics"


def topic_market_data_quality(env_name: str) -> str:
    """ProviderQualityEvent side-channel: provider latency, gaps, failovers.

    Distinct from topic_data_quality (pipeline.data_quality — pipeline-level
    signal gate events). This topic carries per-provider bar delivery telemetry
    for SLA monitoring and ML training signals.
    """
    return f"{env_prefix(env_name)}market.data.quality"


def topic_lifecycle_transitions(env_name: str) -> str:
    """Kafka topic for signal lifecycle transition events.

    Published by IntelligencePipeline on each signal state change
    (activation, exit, MAE/MFE update, shadow outcome, chandelier update).
    Consumed by LifecycleWriter for atomic persistence to signal_ledger.
    """
    return f"{env_prefix(env_name)}lifecycle.transitions"


def topic_transform_graduation(env_name: str) -> str:
    """Kafka topic for transform graduation evaluation results.

    Published by GraduationAnalyzer on each evaluation event.
    Consumed by GraduationWriter for upsert into transform_graduation table.
    """
    return f"{env_prefix(env_name)}intelligence.transform.graduation"


# ---------------------------------------------------------------------------
# Swarm topics
# ---------------------------------------------------------------------------


def topic_swarm_alpha(env_name: str) -> str:
    """Unified alpha multiplier topic. Published by AlphaSwarm."""
    return f"{env_prefix(env_name)}swarm.alpha"


def topic_signal_lineage(env_name: str) -> str:
    """Unified signal lineage events (transform, agent_prediction, lifecycle).

    Published by LineageRecorder on hot path (Kafka-first DAG).
    Consumed by LineageWriter for TimescaleDB persistence.
    """
    return f"{env_prefix(env_name)}intelligence.signal_lineage"


def topic_signal_lineage_dlq(env_name: str) -> str:
    """DLQ for LineageWriter — failed lineage event persistence."""
    return f"{env_prefix(env_name)}intelligence.signal_lineage.dlq"


# ---------------------------------------------------------------------------
# ML topics (Phase 56)
# ---------------------------------------------------------------------------


def topic_ml_data_quality_alerts(env_name: str) -> str:
    """DataQualityAuditor publishes here when score < DATA_QUALITY_MIN_SCORE."""
    return f"{env_prefix(env_name)}ml.data_quality.alerts"


def topic_ml_discovery_results(env_name: str) -> str:
    """MLDiscoveryAnalyzer publishes top-IC feature summaries here."""
    return f"{env_prefix(env_name)}ml.discovery.results"


def topic_ml_orchestrator_dlq(env_name: str) -> str:
    """DLQ for MLOrchestrator — node failures."""
    return f"{env_prefix(env_name)}ml.orchestrator.dlq"


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


def topic_feature_writer_dlq(env_name: str) -> str:
    """Dead letter queue for FeatureWriter unparseable payloads."""
    return f"{env_prefix(env_name)}feature.writer.dlq"


def topic_feature_vectors_dlq(env_name: str) -> str:
    """Dead letter queue for feature_writer unparseable FeatureVectorRecord payloads.

    Published by feature_writer when a FeatureVectorRecord cannot be deserialized
    or inserted into feature_vectors. Enables investigation without data loss.
    """
    return f"{env_prefix(env_name)}intelligence.feature_vectors.dlq"


def topic_signal_writer_dlq(env_name: str) -> str:
    """Dead letter queue for SignalWriter unparseable payloads."""
    return f"{env_prefix(env_name)}intelligence.signal.writer.dlq"


def topic_lifecycle_writer_dlq(env_name: str) -> str:
    """Dead letter queue for LifecycleWriter unparseable payloads."""
    return f"{env_prefix(env_name)}lifecycle.writer.dlq"


def topic_roll_dlq(env_name: str) -> str:
    """Dead letter queue for roll-batch failures."""
    return f"{env_prefix(env_name)}roll.batch.dlq"


def topic_intelligence_pipeline_dlq(env_name: str) -> str:
    """Dead letter queue for IntelligencePipeline unparseable payloads."""
    return f"{env_prefix(env_name)}intelligence.pipeline.dlq"


def topic_signal_tracker_dlq(env_name: str) -> str:
    """Dead letter queue for SignalTracker unparseable payloads."""
    return f"{env_prefix(env_name)}signal.tracker.dlq"


def topic_llm_writer_dlq(env_name: str) -> str:
    """Dead letter queue for LLMWriter unparseable payloads."""
    return f"{env_prefix(env_name)}llm.writer.dlq"


def topic_transform_graduation_dlq(env_name: str) -> str:
    """Dead letter queue for GraduationWriter unparseable payloads."""
    return f"{env_prefix(env_name)}intelligence.transform.graduation.dlq"


def topic_ctx_snapshot(env_name: str) -> str:
    """Kafka topic for CTX qualitative context snapshot events.

    Published by external CTX providers (earnings, macro, news lanes — Phase 83+).
    Consumed by ContextWriter which persists to ctx_events + ctx_snapshots tables.
    Topic naming: <env>.ctx.snapshot (dots only, no colons — CLAUDE.md rule).
    """
    return f"{env_prefix(env_name)}ctx.snapshot"


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
