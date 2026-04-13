"""
Stream key helpers and Kafka topic builders.

Version: 3.1.0
Last Updated: 2026-03-28
Status: v2.2 DAG complete — all pipeline stage topics are in-process audit snapshots.

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

Removed in v2.2 (dead after Phase 44.2 in-process consolidation + Phase 44.3):
  topic_intelligence_i7 — SSE now consumes intelligence.record
  topic_winner, topic_attribution — Phase 40 6-stage microservice DAG retired
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
    """Kafka topic for 1m OHLCV bars from TWS daemon (raw, immutable ground truth)."""
    return f"{env_prefix(env_name)}market.bars"


def topic_market_bars_htf(env_name: str) -> str:
    """Kafka topic for aggregated higher-timeframe bars (5m–1d) from timeframe builder.

    Separate from topic_market_bars (1m only from TWS) to make the DAG acyclic:
    timeframe builder reads market.bars, writes market.bars.htf — no self-reference.
    """
    return f"{env_prefix(env_name)}market.bars.htf"


def topic_roll_events(env_name: str) -> str:
    """Kafka topic for typed RollEvent messages from RollComputeAgent."""
    return f"{env_prefix(env_name)}market.events.roll"


def topic_gap_requests(env_name: str) -> str:
    """Kafka topic for BarGapRequest gap-fill events from BarAuditorAgent."""
    return f"{env_prefix(env_name)}market.events.gap_requests"


def topic_contract_updates(env_name: str) -> str:
    """Kafka topic for ContractUpdateEvent messages from ContractMetadataWriterAgent.

    Published after each successful front-month promotion.
    Consumers (e.g. BarAuditorAgent) use this to invalidate contract caches.
    Purpose: latency optimization — live services flush contract cache on receipt.
    NOT required for correctness; services converge within TTL cache cycle (60s).
    """
    return f"{env_prefix(env_name)}market.events.contract_update"


def topic_roll_dlq(env_name: str) -> str:
    """Kafka DLQ topic for malformed RollEvent payloads.

    ContractMetadataWriterAgent routes unprocessable roll events here instead of
    crashing. Enables investigation without data loss. Pattern: DLQ per domain.
    """
    return f"{env_prefix(env_name)}market.events.roll.dlq"


def topic_indicators(env_name: str) -> str:
    """Kafka topic for I1 technical indicator output."""
    return f"{env_prefix(env_name)}indicators"


def topic_intelligence(env_name: str) -> str:
    """Kafka topic for I3–I6 intelligence pipeline output (IntelligenceEvent)."""
    return f"{env_prefix(env_name)}intelligence"


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


def topic_quality_gated(env_name: str) -> str:
    """Kafka topic for QualityGate stage output."""
    return f"{env_prefix(env_name)}pipeline.quality_gated"


def topic_regime_gated(env_name: str) -> str:
    """Kafka topic for RegimeGate stage output."""
    return f"{env_prefix(env_name)}pipeline.regime_gated"


def topic_tod_adjusted(env_name: str) -> str:
    """Kafka topic for TODAdjuster stage output."""
    return f"{env_prefix(env_name)}pipeline.tod_adjusted"


def topic_calibrated(env_name: str) -> str:
    """Kafka topic for Calibrator stage output."""
    return f"{env_prefix(env_name)}pipeline.calibrated"


def topic_ranked(env_name: str) -> str:
    """Kafka topic for Ranker stage output."""
    return f"{env_prefix(env_name)}pipeline.ranked"


def topic_data_quality(env_name: str) -> str:
    """Kafka topic for data quality monitoring side channel."""
    return f"{env_prefix(env_name)}pipeline.data_quality"


def topic_intelligence_journal(env_name: str) -> str:
    """Kafka topic for atomic IntelligenceJournal records (all provenance/audit/state)."""
    return f"{env_prefix(env_name)}intelligence.journal"


def topic_intelligence_i7_signals(env_name: str) -> str:
    """Kafka topic carrying all ranked I7 signals per bar (pre-ledger write).

    Published by IntelligencePipelineComputeAgent after each bar's I7 run.
    Consumed by SignalWriterAgent for signal_ledger persistence.
    Payload schema: {symbol, tf, bar_ts, computed_at, signals: list[dict]}
    """
    return f"{env_prefix(env_name)}intelligence.i7.signals"


def topic_intelligence_pipeline_state(env_name: str) -> str:
    """Kafka compacted topic for IntelligencePipelineComputeAgent state checkpoints.

    Key format: {agent_version}:{symbol}:{tf} (e.g. 'v1:ESM6:1m')
    Value: msgpack-encoded state dict (plugin_state, kalman_state, tod_priors,
           bar_history, last_bar_offset).
    Topic config: cleanup.policy=compact, min.cleanable.dirty.ratio=0.1,
                  segment.ms=3600000 — set on topic creation, not in code.
    """
    return f"{env_prefix(env_name)}intelligence.pipeline.state"


def topic_intelligence_shadow(env_name: str) -> str:
    """Kafka topic for shadow rollout output from IntelligencePipelineComputeAgent.

    Used during Plan 4 shadow validation only. The new agent publishes to this
    topic (instead of the canonical intelligence topic) while running in shadow
    mode with consumer group 'intelligence_pipeline_shadow'. After cutover
    validation passes, this topic is deleted and this function is removed.

    NOTE: Do not add consumers for this topic — it is for manual inspection only.
    """
    return f"{env_prefix(env_name)}intelligence.shadow"


def topic_audit(env_name: str) -> str:
    """Kafka topic for structured audit events (parity violations, certification events)."""
    return f"{env_prefix(env_name)}audit"


def topic_market_bars_raw(env_name: str, provider: str) -> str:
    """Raw bars from a single provider before merger routing.

    Each provider publishes to its own isolated topic so the MergerAgent can
    consume all providers and apply quality-gating + primary selection logic.
    Topic pattern: <env>.market.bars.raw.<provider>
    """
    return f"{env_prefix(env_name)}market.bars.raw.{provider}"


def topic_health_events(env_name: str) -> str:
    """Service health state transitions published by ServiceAuditorAgent."""
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
    """Kafka topic for SignalMetricsComputeAgent output events.

    Consumed by SignalMetricsWriterAgent to upsert signal_metrics,
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

    Published by IntelligencePipelineComputeAgent on each signal state change
    (activation, exit, MAE/MFE update, shadow outcome, chandelier update).
    Consumed by LifecycleWriterAgent for atomic persistence to signal_ledger.
    """
    return f"{env_prefix(env_name)}lifecycle.transitions"


# ---------------------------------------------------------------------------
# Swarm topics (Phase 56)
# ---------------------------------------------------------------------------


def topic_swarm_results(env_name: str) -> str:
    """Per-AgentResult fan-out topic. SwarmWriterAgent subscribes here.
    One message = one AgentResult from one contributor for one signal.
    """
    return f"{env_prefix(env_name)}intelligence.swarm"


def topic_swarm_alpha_path_a(env_name: str) -> str:
    """Assembled AlphaMultiplier from deterministic (Path A) contributors."""
    return f"{env_prefix(env_name)}swarm.alpha.path_a"


def topic_swarm_alpha_path_b(env_name: str) -> str:
    """Assembled AlphaMultiplier from LLM swarm (Path B) contributors."""
    return f"{env_prefix(env_name)}swarm.alpha.path_b"


def topic_swarm_world_state(env_name: str) -> str:
    """Compacted world state topic (cleanup.policy=compact).
    Create manually: rpk topic create dev.swarm.world_state --topic-config cleanup.policy=compact
    """
    return f"{env_prefix(env_name)}swarm.world_state"


def topic_swarm_orchestrator_dlq(env_name: str) -> str:
    """DLQ for SwarmOrchestratorComputeAgent — unresolvable contexts."""
    return f"{env_prefix(env_name)}swarm.orchestrator.dlq"


def topic_swarm_writer_dlq(env_name: str) -> str:
    """DLQ for SwarmWriterAgent — malformed payloads or DB insert failures."""
    return f"{env_prefix(env_name)}swarm.writer.dlq"


# ---------------------------------------------------------------------------
# ML topics (Phase 56)
# ---------------------------------------------------------------------------


def topic_ml_data_quality_alerts(env_name: str) -> str:
    """MLDataQualityAuditorAgent publishes here when score < DATA_QUALITY_MIN_SCORE."""
    return f"{env_prefix(env_name)}ml.data_quality.alerts"


def topic_ml_discovery_results(env_name: str) -> str:
    """MLDiscoveryComputeAgent publishes top-IC feature summaries here."""
    return f"{env_prefix(env_name)}ml.discovery.results"


def topic_ml_orchestrator_dlq(env_name: str) -> str:
    """DLQ for MLOrchestratorComputeAgent — node failures."""
    return f"{env_prefix(env_name)}ml.orchestrator.dlq"


def topic_alert_requests(env_name: str) -> str:
    """Alert requests from any agent to AlertingAgent.

    Any agent can publish alert requests here via BaseAgent._send_alert().
    AlertingAgent consumes and dispatches to Telegram (CRITICAL) or Discord (HIGH/MEDIUM).
    Consumer group: alerting_consumer
    """
    return f"{env_prefix(env_name)}alert.requests"


def topic_gap_fill_dlq(env_name: str) -> str:
    """DLQ for gap-fill requests that exhausted retries in bar_auditor_agent.

    BarAuditorAgent routes to this topic after 3 failed retry attempts.
    Payload: {symbol, tf, start_ts, end_ts, retry_count, error}
    Consumer group: bar_auditor_gap_fill_consumer
    """
    return f"{env_prefix(env_name)}gap_fill.dlq"


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
