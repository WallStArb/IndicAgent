"""
OTel SDK metrics registry for IndicAgent.

Single module-level _meter backed by the globally configured MeterProvider
(set via init_otel_providers() in otel.py). All instruments are direct OTel SDK
objects — no prometheus_client, no wrapper classes.

Call-site API:
  Counter:   METRIC.add(1, {"label_key": value})
  UpDownCounter (gauge): METRIC.add(delta, {"label_key": value})
  PointGauge:            METRIC.set(value, {"label_key": value})
  Histogram: METRIC.record(value, {"label_key": value})

Tier Labels: Metrics use both tier code (I1, I7) and functional name (technical_indicators, trading_signals)
             for external readability. Use format_tier_label() to generate dual labels.
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics


def _tier_to_functional(tier_code: str) -> str:
    # ring0-ok: lazy import to avoid circular import (src.core.__init__ -> database_manager -> metrics)
    from src.core.tier_aliases import tier_to_functional  # noqa: PLC0415

    return tier_to_functional(tier_code)


def flush_and_shutdown_metrics(timeout_millis: int = 5000) -> None:
    """Flush and shut down the OTel MeterProvider before oneshot process exit.

    Oneshot scripts (ml-training, shadow-auditor, roll-batch) MUST call this
    once at the end of main() so the OTLP exporter drains before the process
    exits.  Without this, JOB_COMPLETED_TOTAL increments never reach the
    collector.

    Safe to call on a NoOp provider (guard: hasattr force_flush).
    Wrapped in broad try/except so a flush failure cannot mask the real exit
    code.  Do NOT call from long-running daemon exit paths — only oneshots.
    """
    try:
        provider = otel_metrics.get_meter_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout_millis)
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass


_meter = otel_metrics.get_meter("indicagent")


def format_tier_label(tier_code: str) -> str:
    """
    Format tier label with both code and functional name for metrics.

    Args:
        tier_code: Internal tier code (I1, I7, etc.)

    Returns:
        Formatted label: "I1:technical_indicators" or "I7:trading_signals"

    Example:
        PLUGIN_DURATION_MS.record(42.5, {"plugin": "rsi", "tier": format_tier_label("I1")})
    """
    functional_name = _tier_to_functional(tier_code)
    return f"{tier_code}:{functional_name}"


def counter(name: str, documentation: str):
    """Create a named OTel counter. Used by services that create metrics dynamically."""
    return _meter.create_counter(name, description=documentation)


def gauge(name: str, documentation: str):
    """Create a named OTel up_down_counter. Use .add(delta) for cumulative tracking."""
    return _meter.create_up_down_counter(name, description=documentation)


def point_gauge(name: str, documentation: str):
    """Create a named OTel gauge for point-in-time absolute values. Use .set(value)."""
    return _meter.create_gauge(name, description=documentation)


# ---------------------------------------------------------------------------
# Plugin pipeline metrics
# ---------------------------------------------------------------------------

PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_fallback_total",
    description="Plugin fallbacks to direct calculation",
)
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
)
PLUGIN_ERRORS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_errors_total",
    description="Plugin execution errors",
)
THREAD_POOL_WORKERS = _meter.create_up_down_counter(
    "intelligence_pipeline_thread_pool_workers",
    description="Current thread pool worker count",
)

# ---------------------------------------------------------------------------
# New plugin observability metrics (Phase 100.5)
# ---------------------------------------------------------------------------

PLUGIN_WARMUP_SKIP_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_warmup_skip_total",
    description="Plugin executions skipped due to insufficient warmup bars (min_lookback not met)",
)
PLUGIN_OUTPUT_NULL_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_output_null_total",
    description="Plugin calls returning empty or None output (insufficient data bars)",
)
PLUGIN_STATE_VALIDATION_ERRORS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_state_validation_errors_total",
    description="Plugin state validation errors (missing _state key in incremental plugin output)",
)
PLUGIN_SIGNAL_EMIT_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_signal_emit_total",
    description="I7 signals emitted via emit_signal(), labeled by plugin and direction",
)
PLUGIN_CONFIDENCE_HISTOGRAM = _meter.create_histogram(
    "intelligence_pipeline_plugin_confidence",
    description="Distribution of signal confidence values at emission",
)

# ---------------------------------------------------------------------------
# Plugin validator metrics — absorbed from plugin_validator.py inline block (Task 2)
# ---------------------------------------------------------------------------


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

SHADOW_N_RESOLVED = point_gauge("shadow_n_resolved", "Resolved shadow signals")
SHADOW_WIN_RATE = point_gauge("shadow_win_rate", "Shadow plugin win rate")
SHADOW_EV_R = point_gauge("shadow_ev_r", "Shadow plugin E[PnL_R]")
SHADOW_EV_CI_LOWER = point_gauge("shadow_ev_ci_lower", "Shadow 95% CI lower bound on E[PnL_R]")
SHADOW_DAYS_TO_GATE = point_gauge("shadow_days_to_gate", "Estimated days to N=100 resolved")
SHADOW_PROMOTION_READY = point_gauge("shadow_promotion_ready", "1 when all gate conditions met")
SHADOW_TAIL_RISK_BLOCKED = _meter.create_counter(
    "shadow_tail_risk_blocked_total",
    description="Shadow promotions blocked by tail-risk gate (skewness or recovery_factor)",
)
SHADOW_TAIL_GATE_DB_ERROR = _meter.create_counter(
    "shadow_tail_gate_db_error_total",
    description="Shadow tail gate DB query failures (fail-open: gate skipped, _should_promote still authoritative)",
)

# ---------------------------------------------------------------------------
# Feature parity auditor (Phase 117)
# ---------------------------------------------------------------------------

FEATURE_PARITY_NULL_FIELDS_TOTAL = point_gauge(
    "feature_parity_null_fields_total",
    "Count of expected pattern fields that are 100% NULL in intelligence_features over the last hour",
)
FEATURE_PARITY_AUDITS_RUN_TOTAL = _meter.create_counter(
    "feature_parity_audits_run_total",
    description="Feature-parity audit runs completed",
)

# ---------------------------------------------------------------------------
# Agent liveness
# ---------------------------------------------------------------------------

AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS = _meter.create_gauge(
    "agent_last_message_timestamp_seconds",
    description="Unix timestamp of last successfully processed Kafka message per agent",
)

# ---------------------------------------------------------------------------
# Base agent hardening metrics (Phase 84)
# ---------------------------------------------------------------------------

AGENT_DLQ_TOTAL = _meter.create_counter(
    "agent_dlq_total",
    description="Per-agent DLQ event count (all paths, including log-only discard)",
)
AGENT_SETUP_RETRIES_TOTAL = _meter.create_counter(
    "agent_setup_retries_total",
    description="Setup retry attempts per agent (each retry loop iteration)",
)
AGENT_CIRCUIT_BREAKER_STATE = _meter.create_gauge(
    "agent_circuit_breaker_state",
    description="Agent setup circuit breaker state: 0=closed, 1=half-open, 2=open",
)

# ---------------------------------------------------------------------------
# ML observability metrics
# ---------------------------------------------------------------------------

FEATURE_IC_SCORE = _meter.create_up_down_counter(
    "feature_ic_score",
    description="Information coefficient per feature per regime (updated weekly by MLDiscoveryAnalyzer)",
)
DATA_QUALITY_SCORE = _meter.create_up_down_counter(
    "data_quality_score",
    description="Training data quality score 0-1 (updated by DataQualityAuditor)",
)

# ---------------------------------------------------------------------------
# Service auditor & alerting metrics
# ---------------------------------------------------------------------------

SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL = _meter.create_counter(
    "service_auditor_service_restarts_total",
    description="Total service restarts triggered by ServiceAuditor",
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
# DLQ quarantine metrics (Phase 108)
# ---------------------------------------------------------------------------

DLQ_QUARANTINE_TOTAL = _meter.create_counter(
    "dlq_quarantine_total",
    description="DLQ messages quarantined after DLQ_MAX_RETRIES identical errors in 24h",
)

# ---------------------------------------------------------------------------
# Consumer stall detection (Phase 108)
# ---------------------------------------------------------------------------

CONSUMER_STALL_DETECTED_TOTAL = _meter.create_counter(
    "consumer_stall_detected_total",
    description="Consumer stall events detected by ServiceAuditor before restart",
)

# ---------------------------------------------------------------------------
# Oneshot job completion counters (Phase 108)
# ---------------------------------------------------------------------------

# CONTRACT: Oneshot scripts that emit this counter MUST call provider.force_flush() /
# provider.shutdown() before process exit, otherwise the OTLP exporter will not drain
# and the counter will never reach the collector. See Plan 06 for the canonical call site.
JOB_COMPLETED_TOTAL = _meter.create_counter(
    "job_completed_total",
    description="Oneshot job completions by name and status",
)

# Buckets span 1s-32h -- the BaseBatch fleet ranges from quick per-symbol
# jobs to 30+ hour corpus rebuilds (e.g. ensemble_ic_engine). Default OTel
# buckets top out at 10s, which would collapse every long-running job into
# the +Inf bucket and make percentile queries meaningless for exactly the
# jobs most worth watching.
JOB_DURATION_SECONDS = _meter.create_histogram(
    "job_duration_seconds",
    description="Oneshot job (BaseBatch.execute()) wall-clock duration by name and status",
    unit="s",
    explicit_bucket_boundaries_advisory=[
        1,
        5,
        15,
        30,
        60,
        120,
        300,
        600,
        1800,
        3600,
        7200,
        14400,
        28800,
        57600,
        115200,
    ],
)

# Todo 387 staleness observability (phase 189 plan 04), recorded by the IBKR history fetcher
# at run end with attribute job.
OHLCV_COVERAGE_SLA_BREACHED_SERIES = point_gauge(
    "ohlcv_coverage_sla_breached_series",
    "In-scope (symbol, timeframe) series whose staleness exceeds "
    "infra.backfill.max_staleness_days_before_preempt, at fetcher run end",
)

# ---------------------------------------------------------------------------
# API health gauge (Phase 108)
# ---------------------------------------------------------------------------

API_HEALTH = _meter.create_gauge(
    "api_health",
    description="API DB connectivity: 1=reachable, 0=unreachable",
)

# ---------------------------------------------------------------------------
# Signal processor gate observability metrics (Phase 089 D-22)
# ---------------------------------------------------------------------------

SIGNAL_PROCESSOR_CIS_NULL_TOTAL = _meter.create_counter(
    "signal_processor_cis_null_total",
    description="CIS scoring returned None — no score available for signal pipeline",
)
SIGNAL_PROCESSOR_DLQ_TOTAL = _meter.create_counter(
    "signal_processor_dlq_total",
    description="Signals routed to DLQ by SignalProcessor, labeled by reason",
)
SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL = _meter.create_counter(
    "signal_processor_gate_rejections_total",
    description="Signals rejected by a named gate (regime, quality, tod, calibration)",
)
SIGNAL_PROCESSOR_WINNER_TOTAL = _meter.create_counter(
    "signal_processor_winner_total",
    description="Winner signals selected per bar, labeled by entry_type",
)
SIGNAL_PROCESSOR_SIGNALS_EVALUATED_TOTAL = _meter.create_counter(
    "signal_processor_signals_evaluated_total",
    description="Total raw signals entering the SignalProcessor pipeline per bar",
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

# ---------------------------------------------------------------------------
# Config metrics (Phase 109)
# ---------------------------------------------------------------------------

CONFIG_SET_TOTAL = _meter.create_counter(
    "config_set_total",
    description="Config set operations by key and outcome",
)
CONFIG_VALIDATION_FAILED_TOTAL = _meter.create_counter(
    "config_validation_failed_total",
    description="Config validation failures by key and reason",
)
CONFIG_REVERT_TOTAL = _meter.create_counter(
    "config_revert_total",
    description="Config revert operations by key",
)
CONFIG_OUTBOX_PENDING = _meter.create_up_down_counter(
    "config_outbox_pending",
    description="Pending config outbox entries awaiting Kafka publish",
)
CONFIG_OUTBOX_PUBLISH_LATENCY_SECONDS = _meter.create_histogram(
    "config_outbox_publish_latency_seconds",
    description="Config outbox to Kafka publish latency",
    unit="s",
)
CONFIG_RELOAD_TOTAL = _meter.create_counter(
    "config_reload_total",
    description="Config hot-reload events by agent and key",
)
CONFIG_RELOAD_LATENCY_SECONDS = _meter.create_histogram(
    "config_reload_latency_seconds",
    description="Time from Kafka receive to in-memory cache update (review feedback - Gemini suggestion)",
    unit="s",
)
CONFIG_AUTH_FAILED_TOTAL = _meter.create_counter(
    "config_auth_failed_total",
    description="Config API auth failures by reason",
)
CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS = _meter.create_gauge(
    "config_last_reload_timestamp_seconds",
    description="Timestamp of last successful config reload per agent",
)
CONFIG_STALE_TOTAL = _meter.create_counter(
    "config_stale_total",
    description="Config operations failed (DB/Kafka unavailable), using cached/default config",
)

# ---------------------------------------------------------------------------
# Self-healing metrics (Phase 109)
# ---------------------------------------------------------------------------

REMEDIATION_ATTEMPT_TOTAL = _meter.create_counter(
    "remediation_attempt_total",
    description="Remediation attempts by state_variable and action",
)
REMEDIATION_SUCCESS_TOTAL = _meter.create_counter(
    "remediation_success_total",
    description="Successful remediation outcomes",
)
REMEDIATION_DURATION_SECONDS = _meter.create_histogram(
    "remediation_duration_seconds",
    description="Remediation execution latency",
    unit="s",
)
REMEDIATION_SUCCESS_RATE = _meter.create_gauge(
    "remediation_success_rate",
    description="30-day rolling success rate per action",
)
REMEDIATION_MEASURE_FAILED_TOTAL = _meter.create_counter(
    "remediation_measure_failed_total",
    description="Prometheus measurement failures (fail-closed, no remediation triggered)",
)
WEBHOOK_RECEIVED_TOTAL = _meter.create_counter(
    "webhook_received_total",
    description="Alertmanager webhook requests received",
)
WEBHOOK_AUTH_FAILED_TOTAL = _meter.create_counter(
    "webhook_auth_failed_total",
    description="Webhook authentication failures by reason",
)
WEBHOOK_VALIDATION_FAILED_TOTAL = _meter.create_counter(
    "webhook_validation_failed_total",
    description="Webhook payload validation failures",
)
REMEDIATION_POOL_FLUSH_TOTAL = _meter.create_counter(
    "remediation_pool_flush_total",
    description="DB pool flush remediation attempts by outcome (success|failed)",
)
REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL = _meter.create_counter(
    "remediation_circuit_breaker_open_total",
    description="Circuit breaker open events (5-min failure rate > 50%)",
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


# ---------------------------------------------------------------------------
# Service-up gauge — named constant so service_auditor_agent imports it directly
# ---------------------------------------------------------------------------

SERVICE_UP_GAUGE = _meter.create_up_down_counter(
    "indicagent_service_up",
    description="Service-up gauge keyed by systemd unit",
)

# ---------------------------------------------------------------------------
# Intelligence pipeline publisher metrics (Phase 81)
# ---------------------------------------------------------------------------

INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_backfill_signals_total",
    description="Signals published to intelligence.i7.signals with is_backfill=True (catch-up payloads)",
)

# ---------------------------------------------------------------------------
# Bar replay provider metrics (Phase 81 — Plan 04)
# ---------------------------------------------------------------------------

BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL = _meter.create_counter(
    "bar_replay_provider_bars_published_total",
    description="Bars published by BarReplayProvider (progress tracking)",
)

BAR_REPLAY_PROVIDER_LAG_SECONDS = _meter.create_up_down_counter(
    "bar_replay_provider_lag_seconds",
    description="Seconds between last_replayed_ts and NOW(); drops to 0 on completion",
)

# ---------------------------------------------------------------------------
# Signal replay auditor metrics (Phase 81 — Plan 05)
# North-star metric: signal_replay_unresolved_gauge should converge to 0.
# ---------------------------------------------------------------------------


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
# Framing observability (Phase 115)
# ---------------------------------------------------------------------------

STOP_BUFFER_MULT_DISTRIBUTION = _meter.create_histogram(
    "stop_buffer_mult_distribution",
    description="Adaptive buffer multiplier at frame time by regime_type and stop_type — alerts on vol regime drift",
    unit="1",
)

FRAME_TRADE_STOP_CORRECTION_TOTAL = _meter.create_counter(
    "frame_trade_stop_correction_total",
    description="Stop placements corrected by frame_trade (stop_capped: structural too wide; zone_corrected: stop inside entry zone). Labels: correction_type, setup_type.",
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
# ML training (Phase 83)
# ---------------------------------------------------------------------------

ML_TRAINING_SECONDS = _meter.create_histogram(
    "ml_training_seconds",
    description="Full ML training cycle duration",
    unit="s",
)

# ---------------------------------------------------------------------------
# SSE delivery (Phase hardening)
# ---------------------------------------------------------------------------

SSE_MESSAGES_DROPPED_TOTAL = _meter.create_counter(
    "sse_messages_dropped_total",
    description="SSE messages dropped because the client queue was full",
)

# ---------------------------------------------------------------------------
# Contract hot-reload (Phase hardening)
# ---------------------------------------------------------------------------

CONTRACTS_RELOAD_TOTAL = _meter.create_counter(
    "contracts_reload_total",
    description="Contract hot-reload attempts labeled by status (success|failure)",
)

# ---------------------------------------------------------------------------
# Pipeline backpressure (Phase hardening)
# ---------------------------------------------------------------------------

PIPELINE_BACKPRESSURE_DROP_TOTAL = _meter.create_counter(
    "intelligence_pipeline_backpressure_drop_total",
    description="Bars dropped by backpressure circuit breaker (queue depth exceeded)",
)

# ---------------------------------------------------------------------------
# Phase 138 — Regime writer metrics
# ---------------------------------------------------------------------------

REGIME_WRITER_ROWS_UPDATED_TOTAL = _meter.create_counter(
    "regime_writer_rows_updated_total",
    description="feature_vectors rows a regime family wrote; labels symbol, tf, regime_column",
)
REGIME_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram(
    "regime_writer_run_latency_seconds",
    description="Full regime labeler run duration",
    unit="s",
)
REGIME_WRITER_NULL_REGIME_REMAINING = _meter.create_gauge(
    "regime_writer_null_regime_remaining",
    description="feature_vectors rows still NULL in the run's regime column; labels symbol, tf, regime_column",
)

# ---------------------------------------------------------------------------
# Feature lifecycle (data quality, 186-09), emitted by services/feature_lifecycle.py
# ---------------------------------------------------------------------------

FEATURE_QUALITY_FAILURES = counter(
    "feature_quality_failures_total",
    "Count of failing (feature, tf) data-quality checks per real feature_lifecycle run. "
    "Attribute check is coverage, non_finite or not_computed. Zero on a dry run.",
)
FEATURE_LIFECYCLE_TRANSITIONS = counter(
    "feature_lifecycle_transitions_total",
    "Count of concept_registry (domain='feature') transitions written by the "
    "feature_lifecycle node, by to_status and reason. Zero on a dry run.",
)
