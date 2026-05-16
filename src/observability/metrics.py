"""
OTel SDK metrics registry for IndicAgent.

Single module-level _meter backed by the globally configured MeterProvider
(set via init_otel_providers() in otel.py). All instruments are direct OTel SDK
objects — no prometheus_client, no wrapper classes.

Call-site API:
  Counter:   METRIC.add(1, {"label_key": value})
  Gauge:     METRIC.add(value, {"label_key": value})  (up_down_counter)
  Histogram: METRIC.record(value, {"label_key": value})
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("indicagent")


def counter(name: str, documentation: str):
    """Create a named OTel counter. Used by services that create metrics dynamically."""
    return _meter.create_counter(name, description=documentation)


def gauge(name: str, documentation: str):
    """Create a named OTel up_down_counter (gauge semantics). Used by services dynamically."""
    return _meter.create_up_down_counter(name, description=documentation)


# ---------------------------------------------------------------------------
# Plugin pipeline metrics
# ---------------------------------------------------------------------------

PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "plugin_fallbacks_total",
    description="Plugin fallbacks to direct calculation",
)
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
    unit="ms",
)
PLUGIN_ERRORS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_errors_total",
    description="Plugin execution errors",
)
THREAD_POOL_WORKERS = _meter.create_up_down_counter(
    "intelligence_pipeline_thread_pool_workers",
    description="Current thread pool worker count",
)

LANGGRAPH_WORKFLOW_EXECUTION_TOTAL = _meter.create_counter(
    "langgraph_workflow_executions_total",
    description="Total LangGraph workflow executions",
)
LANGGRAPH_WORKFLOW_DURATION = _meter.create_histogram(
    "langgraph_workflow_duration_seconds",
    description="LangGraph workflow execution time",
    unit="s",
)

# ---------------------------------------------------------------------------
# Circuit breaker metrics
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_STATE = _meter.create_gauge(
    "plugin_circuit_breaker_state",
    description="Circuit breaker state (0=closed, 1=open, 2=half-open)",
)
CIRCUIT_BREAKER_FAILURES_TOTAL = _meter.create_counter(
    "circuit_breaker_failures_total",
    description="Total circuit breaker failures",
)
CIRCUIT_BREAKER_SUCCESSES_TOTAL = _meter.create_counter(
    "circuit_breaker_successes_total",
    description="Total circuit breaker successes",
)
CIRCUIT_BREAKER_TRANSITIONS_TOTAL = _meter.create_counter(
    "circuit_breaker_state_transitions_total",
    description="Total circuit breaker state transitions",
)
CIRCUIT_BREAKER_OPEN_SECONDS = _meter.create_histogram(
    "circuit_breaker_open_duration_seconds",
    description="Time spent in OPEN state per recovery cycle",
    unit="s",
)

# ---------------------------------------------------------------------------
# Persistence metrics
# ---------------------------------------------------------------------------

PERSISTENCE_BATCH_LATENCY = _meter.create_histogram(
    "persistence_batch_latency_seconds",
    description="Time taken to persist batch to database in seconds",
    unit="s",
)
PERSISTENCE_CONSUMER_LAG = _meter.create_gauge(
    "persistence_consumer_lag_records",
    description="Current consumer lag in records",
)

# ---------------------------------------------------------------------------
# Provider metrics
# ---------------------------------------------------------------------------

PROVIDER_ACTIVE_SUBSCRIPTIONS = _meter.create_up_down_counter(
    "provider_active_subscriptions",
    description="Active data subscriptions per provider",
)
PROVIDER_BARS_PRODUCED_TOTAL = _meter.create_counter(
    "provider_bars_produced_total",
    description="Total bars produced and published to raw topic per provider",
)
PROVIDER_RECONNECTS_ATTEMPTED_TOTAL = _meter.create_counter(
    "provider_reconnects_attempted_total",
    description="Total reconnection attempts started per provider",
)
PROVIDER_RECONNECTS_SUCCEEDED_TOTAL = _meter.create_counter(
    "provider_reconnects_succeeded_total",
    description="Total reconnection attempts that successfully reestablished the connection",
)
PROVIDER_CONNECTED = _meter.create_up_down_counter(
    "provider_connected",
    description="1 when provider is connected, 0 otherwise",
)
PROVIDER_GAPS_FILLED_TOTAL = _meter.create_counter(
    "provider_gaps_filled_total",
    description="Total gap-fill bars fetched and published per provider",
)
PROVIDER_BARS_DROPPED_TOTAL = _meter.create_counter(
    "provider_bars_dropped_total",
    description="Bars dropped at the provider edge, labeled by reason",
)
IBKR_ERROR_326_TOTAL = _meter.create_counter(
    "ibkr_error_326_total",
    description="Error 326 (clientId collision) detections and recovery actions",
)
IBKR_CLIENT_ID_CURRENT = _meter.create_up_down_counter(
    "ibkr_client_id_current",
    description="Current IBKR clientId in use (value > base signals rotation)",
)

# ---------------------------------------------------------------------------
# Merger metrics
# ---------------------------------------------------------------------------

MERGER_BARS_ROUTED_TOTAL = _meter.create_counter(
    "merger_bars_routed_total",
    description="Total bars routed by MergerAgent to canonical market.bars topic",
)
MERGER_BARS_DROPPED_TOTAL = _meter.create_counter(
    "merger_bars_dropped_total",
    description="Total bars dropped by MergerAgent (duplicate, stale, or non-primary)",
)
MERGER_FAILOVERS_TOTAL = _meter.create_counter(
    "merger_failovers_total",
    description="Total provider failovers executed by MergerAgent",
)
MERGER_BAR_LATENCY_SECONDS = _meter.create_histogram(
    "merger_bar_latency_seconds",
    description="Seconds between provider publish_ts and MergerAgent consume_ts",
    unit="s",
)

# ---------------------------------------------------------------------------
# Shadow plugin metrics
# ---------------------------------------------------------------------------

SHADOW_N_RESOLVED = _meter.create_up_down_counter(
    "shadow_n_resolved",
    description="Resolved shadow signals",
)
SHADOW_WIN_RATE = _meter.create_up_down_counter(
    "shadow_win_rate",
    description="Shadow plugin win rate",
)
SHADOW_EV_R = _meter.create_up_down_counter(
    "shadow_ev_r",
    description="Shadow plugin E[PnL_R]",
)
SHADOW_EV_CI_LOWER = _meter.create_up_down_counter(
    "shadow_ev_ci_lower",
    description="Shadow 95% CI lower bound on E[PnL_R]",
)
SHADOW_DAYS_TO_GATE = _meter.create_up_down_counter(
    "shadow_days_to_gate",
    description="Estimated days to N=100 resolved",
)
SHADOW_PROMOTION_READY = _meter.create_up_down_counter(
    "shadow_promotion_ready",
    description="1 when all gate conditions met",
)

# ---------------------------------------------------------------------------
# Agent liveness
# ---------------------------------------------------------------------------

AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS = _meter.create_gauge(
    "agent_last_message_timestamp_seconds",
    description="Unix timestamp of last successfully processed Kafka message per agent",
)

# ---------------------------------------------------------------------------
# Parity auditor metrics
# ---------------------------------------------------------------------------

PARITY_MATCH_RATE = _meter.create_up_down_counter(
    "parity_match_rate",
    description="Fraction of rows matching between primary and shadow (0.0-1.0)",
)
SHADOW_AHEAD_ROWS_TOTAL = _meter.create_counter(
    "shadow_ahead_rows_total",
    description="Rows present in shadow but not yet in primary (timing race)",
)
PARITY_VIOLATIONS_TOTAL = _meter.create_counter(
    "parity_violations_total",
    description="Total field-level parity violations detected",
)
PARITY_CYCLES_TOTAL = _meter.create_counter(
    "parity_cycles_total",
    description="Total comparison cycles executed by ParityAuditorAgent",
)

# ---------------------------------------------------------------------------
# ML observability metrics
# ---------------------------------------------------------------------------

FEATURE_IC_SCORE = _meter.create_up_down_counter(
    "feature_ic_score",
    description="Information coefficient per feature per regime (updated weekly by MLDiscoveryComputeAgent)",
)
DATA_QUALITY_SCORE = _meter.create_up_down_counter(
    "data_quality_score",
    description="Training data quality score 0-1 (updated by MLDataQualityAuditorAgent)",
)

# ---------------------------------------------------------------------------
# Service auditor & alerting metrics
# ---------------------------------------------------------------------------

SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL = _meter.create_counter(
    "service_auditor_service_restarts_total",
    description="Total service restarts triggered by ServiceAuditorAgent",
)
BAR_AUDITOR_GAP_FILL_DLQ_DEPTH = _meter.create_counter(
    "bar_auditor_gap_fill_dlq_depth",
    description="Total gap-fill requests routed to DLQ after retry exhaustion",
)
ALERTING_DISPATCH_TOTAL = _meter.create_counter(
    "alerting_dispatch_total",
    description="Alerts dispatched by channel and status",
)
ALERTING_LATENCY_SECONDS = _meter.create_histogram(
    "alerting_latency_seconds",
    description="Alert dispatch latency in seconds",
    unit="s",
)

# ---------------------------------------------------------------------------
# DLQ metrics
# ---------------------------------------------------------------------------

DLQ_MESSAGES_TOTAL = _meter.create_counter(
    "dlq_messages_total",
    description="Total messages routed to Dead Letter Queue",
)

# ---------------------------------------------------------------------------
# Regime gate suppression metrics
# ---------------------------------------------------------------------------

REGIME_GATE_SUPPRESSIONS_TOTAL = _meter.create_counter(
    "regime_gate_suppressions_total",
    description="Signals suppressed by regime gate",
)

REGIME_SOFT_GATE_SIGNALS_TOTAL = _meter.create_counter(
    "regime_soft_gate_signals_total",
    description="Signals flowing through the regime gate's three-band classifier (band in {suppressed, soft, full}).",
)

# ---------------------------------------------------------------------------
# Feature validation metrics (Phase 82 D-05)
# ---------------------------------------------------------------------------

FEATURE_VALIDATION_DECISIONS_TOTAL = _meter.create_counter(
    "feature_validation_decisions_total",
    description="Total validation decisions written to validation_results per decision label.",
)


def record_langgraph_workflow(
    workflow_name: str,
    duration_seconds: float,
    status: str = "success",
    intelligence_tier: str = "I5",
) -> None:
    LANGGRAPH_WORKFLOW_EXECUTION_TOTAL.add(1, {"workflow_name": workflow_name, "status": status})
    LANGGRAPH_WORKFLOW_DURATION.record(
        duration_seconds,
        {"workflow_name": workflow_name, "intelligence_tier": intelligence_tier},
    )


# ---------------------------------------------------------------------------
# Signal quality metrics
# ---------------------------------------------------------------------------

SIGNAL_OUTCOME_TOTAL = _meter.create_counter(
    "signal_outcome_total",
    description="Signal outcomes by plugin and result",
)

# ---------------------------------------------------------------------------
# LLM infrastructure metrics
# ---------------------------------------------------------------------------

LLM_CALL_DURATION = _meter.create_histogram(
    "llm_call_duration_seconds",
    description="LLM call latency per provider and call_type",
    unit="s",
)

LLM_TOKENS_USED = _meter.create_counter(
    "llm_tokens_used_total",
    description="Total tokens consumed per provider and call_type",
)

LLM_CACHE_HITS = _meter.create_counter(
    "llm_cache_hit_total",
    description="Semantic cache hits per call_type",
)

LLM_GUARDRAILS_REJECTIONS = _meter.create_counter(
    "llm_guardrails_rejections_total",
    description="LLM responses rejected by guardrails schema validation",
)

LLM_RATE_LIMIT_WAIT = _meter.create_histogram(
    "llm_rate_limit_wait_seconds",
    description="Time spent waiting for rate limit token bucket",
    unit="s",
)

# ---------------------------------------------------------------------------
# AI agent execution metrics
# ---------------------------------------------------------------------------

AI_AGENT_INVOCATIONS_TOTAL = _meter.create_counter(
    "ai_agent_invocations_total",
    description="Total AI agent invocations by agent, group, and status",
)

AI_AGENT_DURATION_MS = _meter.create_histogram(
    "ai_agent_duration_ms",
    description="AI agent execution latency in ms",
    unit="ms",
)


# ---------------------------------------------------------------------------
# Zone engine metrics
# ---------------------------------------------------------------------------

ZONE_TIER_USED = _meter.create_counter(
    "zone_tier_used_total",
    description="Zone engine resolution tier selected per call",
)
ZONE_CANDIDATE_COUNT = _meter.create_histogram(
    "zone_candidate_count",
    description="Structural candidates evaluated per zone resolution",
)
ZONE_CLUSTER_DENSITY = _meter.create_histogram(
    "zone_cluster_density",
    description="Cluster quality score (strength x diversity / width_atr)",
)
ZONE_WIDTH_ATR = _meter.create_histogram(
    "zone_width_atr",
    description="Final zone width in ATR units",
)


def record_llm_call(
    provider: str,
    call_type: str,
    latency_s: float,
    status: str = "success",
    tokens: int = 0,
) -> None:
    LLM_CALL_DURATION.record(
        latency_s,
        {"provider": provider, "call_type": call_type, "status": status},
    )
    if status == "success":
        LLM_TOKENS_USED.add(tokens, {"provider": provider, "call_type": call_type})


# ---------------------------------------------------------------------------
# Service-up gauge — named constant so service_auditor_agent imports it directly
# ---------------------------------------------------------------------------

SERVICE_UP_GAUGE = _meter.create_up_down_counter(
    "indicagent_service_up",
    description="Service-up gauge keyed by systemd unit",
)

# ---------------------------------------------------------------------------
# Swarm intelligence metrics (Phase 80)
# ---------------------------------------------------------------------------

SWARM_INVOCATIONS_TOTAL = _meter.create_counter(
    "swarm_invocations_total",
    description="Per-agent swarm call rate, error rate, and capacity skips",
)
SWARM_MULTIPLIER_DISTRIBUTION = _meter.create_histogram(
    "swarm_multiplier_distribution",
    description="Per-agent multiplier output distribution over time",
)
SWARM_AGGREGATED_MULTIPLIER = _meter.create_histogram(
    "swarm_aggregated_multiplier",
    description="Final combined multiplier distribution per timeframe",
)
SWARM_AGENT_WEIGHT = _meter.create_up_down_counter(
    "swarm_agent_weight",
    description="Per-agent learned weight by timeframe — key Renaissance health signal",
)
SWARM_SIGNAL_LEDGER_UPDATE_TOTAL = _meter.create_counter(
    "swarm_signal_ledger_update_total",
    description="Writer-owned signal_ledger materialization outcomes",
)

# ---------------------------------------------------------------------------
# Intelligence pipeline publisher metrics (Phase 81)
# ---------------------------------------------------------------------------

INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_backfill_signals_total",
    description="Signals published to intelligence.i7.signals with is_backfill=True (catch-up payloads)",
)

# ---------------------------------------------------------------------------
# Signal tracker intake metrics (Phase 81)
# ---------------------------------------------------------------------------

SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL = _meter.create_counter(
    "signal_tracker_invalid_signal_total",
    description="Signals rejected by _load_signal() (missing/invalid required fields) and routed to DLQ",
)

SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL = _meter.create_counter(
    "signal_tracker_backfill_fast_path_total",
    description="Backfill signals where TTL elapsed at ingest; published TTL-expired and skipped active index",
)

# ---------------------------------------------------------------------------
# Bar replay provider metrics (Phase 81 — Plan 04)
# ---------------------------------------------------------------------------

BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL = _meter.create_counter(
    "bar_replay_provider_bars_published_total",
    description="Bars published by BarReplayProviderAgent (progress tracking)",
)

BAR_REPLAY_PROVIDER_LAG_SECONDS = _meter.create_up_down_counter(
    "bar_replay_provider_lag_seconds",
    description="Seconds between last_replayed_ts and NOW(); drops to 0 on completion",
)

# ---------------------------------------------------------------------------
# Signal replay auditor metrics (Phase 81 — Plan 05)
# North-star metric: signal_replay_unresolved_gauge should converge to 0.
# ---------------------------------------------------------------------------

SIGNAL_REPLAY_UNRESOLVED_GAUGE = _meter.create_up_down_counter(
    "signal_replay_unresolved_gauge",
    description="v1 signals with exit_at IS NULL past TTL (north star — target = 0)",
)

SIGNAL_REPLAY_ATTEMPTED_TOTAL = _meter.create_counter(
    "signal_replay_attempted_total",
    description="Signals queried for replay each auditor cycle",
)

SIGNAL_REPLAY_RESOLVED_TOTAL = _meter.create_counter(
    "signal_replay_resolved_total",
    description="Outcomes successfully computed and published by replay auditor",
)

SIGNAL_REPLAY_OHLCV_GAP_TOTAL = _meter.create_counter(
    "signal_replay_ohlcv_gap_total",
    description="Replay attempts where market_data_ohlcv had zero bars in the signal window",
)

LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL = _meter.create_counter(
    "lifecycle_writer_idempotent_skip_total",
    description="EXIT writes blocked by idempotency guard (WHERE exit_at IS NULL); validates two-path safety",
)

# ---------------------------------------------------------------------------
# Signal ledger quality KPI (Phase 81 — Plan 06)
# ---------------------------------------------------------------------------

SIGNAL_LEDGER_BACKFILL_RATIO = _meter.create_up_down_counter(
    "signal_ledger_backfill_ratio",
    description="Fraction of signal_ledger rows last 24h with is_backfill=TRUE (training set quality KPI)",
)

# ---------------------------------------------------------------------------
# Swarm dispatch latency (Phase 83)
# ---------------------------------------------------------------------------

SWARM_DISPATCH_SECONDS = _meter.create_histogram(
    "swarm_dispatch_seconds",
    description="Full swarm trigger-to-result cycle latency (context build + agent fan-out + aggregation)",
    unit="s",
)

# ---------------------------------------------------------------------------
# AI context cache (Phase 83)
# ---------------------------------------------------------------------------

AI_CONTEXT_CACHE_HITS_TOTAL = _meter.create_counter(
    "ai_context_cache_hits_total",
    description="AIContextCache.build() returning a fresh context",
)

AI_CONTEXT_CACHE_MISSES_TOTAL = _meter.create_counter(
    "ai_context_cache_misses_total",
    description="AIContextCache.build() returning None (no entry or stale)",
)

# ---------------------------------------------------------------------------
# DB connection pool (Phase 83)
# ---------------------------------------------------------------------------

DB_POOL_SIZE = _meter.create_up_down_counter(
    "db_pool_size",
    description="Current asyncpg pool size (total connections)",
)

DB_POOL_IDLE = _meter.create_up_down_counter(
    "db_pool_idle",
    description="Current asyncpg pool idle connections",
)

# ---------------------------------------------------------------------------
# Signal quality distributions (Phase 83)
# ---------------------------------------------------------------------------

SIGNAL_PNL_R_DISTRIBUTION = _meter.create_histogram(
    "signal_pnl_r_distribution",
    description="Realized PnL (R-multiple) distribution per setup plugin",
)

SIGNAL_MAE_DISTRIBUTION = _meter.create_histogram(
    "signal_mae_distribution",
    description="Max adverse excursion distribution per setup plugin",
)

SIGNAL_MFE_DISTRIBUTION = _meter.create_histogram(
    "signal_mfe_distribution",
    description="Max favorable excursion distribution per setup plugin",
)

# ---------------------------------------------------------------------------
# Kafka publish latency (Phase 83)
# ---------------------------------------------------------------------------

KAFKA_PUBLISH_SECONDS = _meter.create_histogram(
    "kafka_publish_seconds",
    description="Kafka producer send_and_wait latency",
    unit="s",
)

# ---------------------------------------------------------------------------
# Per-tier feature computation (Phase 83)
# ---------------------------------------------------------------------------

FEATURES_COMPUTED_TOTAL = _meter.create_counter(
    "features_computed_total",
    description="Feature rows computed and published per intelligence tier",
)

# ---------------------------------------------------------------------------
# Narrative generation (Phase 83)
# ---------------------------------------------------------------------------

NARRATIVE_GENERATION_TOTAL = _meter.create_counter(
    "narrative_generation_total",
    description="Narrative generation outcomes",
)

# ---------------------------------------------------------------------------
# ML training (Phase 83)
# ---------------------------------------------------------------------------

ML_TRAINING_SECONDS = _meter.create_histogram(
    "ml_training_seconds",
    description="Full ML training cycle duration",
    unit="s",
)
