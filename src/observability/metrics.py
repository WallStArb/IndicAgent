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

PLUGIN_VALIDATOR_REGISTERED_PLUGINS = _meter.create_up_down_counter(
    "plugin_validator_registered_plugins_total",
    description="Total registered plugins per tier",
)
PLUGIN_VALIDATOR_VALIDATION_STATUS = _meter.create_up_down_counter(
    "plugin_validator_validation_status",
    description="Validation result status",
)
PLUGIN_VALIDATOR_ERRORS = _meter.create_counter(
    "plugin_validator_validation_errors_total",
    description="Total validation errors",
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
# Shadow validation metrics (Phase 120)
# ---------------------------------------------------------------------------

SHADOW_VALIDATION_N = point_gauge(
    "shadow_validation_n",
    "Resolved shadow outcome count per setup (weekly validator run)",
)
SHADOW_VALIDATION_WIN_RATE = point_gauge(
    "shadow_validation_win_rate",
    "Fraction of resolved shadow outcomes with pnl_r > 0",
)
SHADOW_VALIDATION_P_VALUE = point_gauge(
    "shadow_validation_p_value",
    "Binomial test p-value (win rate vs 50% baseline, one-sided)",
)
SHADOW_VALIDATION_AVG_PNL_R = point_gauge(
    "shadow_validation_avg_pnl_r",
    "Average pnl_r across resolved shadow outcomes",
)
SHADOW_VALIDATION_CALIBRATION = point_gauge(
    "shadow_validation_calibration",
    "CORR(cis_score, (pnl_r > 0)::int) — confidence predicts profitable outcomes",
)
SHADOW_VALIDATION_PROMOTED = point_gauge(
    "shadow_validation_promoted",
    "1=promoted to live this run, 0=still in shadow",
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
# Confidence calibration monitor (Phase 117)
# ---------------------------------------------------------------------------

SIGNAL_CONFIDENCE_CALIBRATION = point_gauge(
    "signal_confidence_calibration",
    "Per-setup correlation between cis_score and aggregator selection (was_selected)",
)
CONFIDENCE_CALIBRATION_ALERTS_TOTAL = _meter.create_counter(
    "confidence_calibration_alerts_total",
    description="Per-setup low-calibration alerts (correlation < 0.3 at N>=100)",
)

# ---------------------------------------------------------------------------
# Signal probe auditor (Phase 117)
# ---------------------------------------------------------------------------

SIGNAL_PROBE_ACTIVATIONS_TOTAL = _meter.create_counter(
    "signal_probe_activations_total",
    description="Simulated activations from SignalProbeAuditor, labeled by setup_plugin",
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
AI_AGENT_ERRORS_TOTAL = _meter.create_counter(
    "ai_agent_errors_total",
    description="AI agent _compute() errors by agent_id and error_type",
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

LLM_EMPTY_RESPONSES = _meter.create_counter(
    "llm_empty_responses_total",
    description="LLM calls that returned no response (all providers failed or circuits open)",
)

LLM_PARSE_FAILURES = _meter.create_counter(
    "llm_parse_failures_total",
    description="LLM responses that passed guardrails but failed JSON parsing in the agent",
)

LLM_RESPONSE_CHARS = _meter.create_histogram(
    "llm_response_chars",
    description="Character length of successful LLM responses per provider and call_type",
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
SWARM_AGENT_WEIGHT = point_gauge(
    "swarm_agent_weight",
    "Per-agent learned weight by timeframe — key Renaissance health signal",
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

SIGNAL_REPLAY_NULL_ZONE_TOTAL = _meter.create_counter(
    "signal_replay_null_zone_total",
    description="Replay signals skipped due to NULL entry_zone_low or entry_zone_high (data integrity error)",
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
    description="SignalContextCache.build() returning a fresh context",
)

AI_CONTEXT_CACHE_MISSES_TOTAL = _meter.create_counter(
    "ai_context_cache_misses_total",
    description="SignalContextCache.build() returning None (no entry or stale)",
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
# Agent memory metrics (Phase 097)
# ---------------------------------------------------------------------------

MEMORY_RECALL_LATENCY_MS = _meter.create_histogram(
    "memory_recall_latency_ms",
    description="MemoryClient.recall() end-to-end latency per memory tier (labels: tier, symbol)",
    unit="ms",
)

MEMORY_RECALL_RESULTS_TOTAL = _meter.create_counter(
    "memory_recall_results_total",
    description="Memory recall outcomes per tier (labels: tier, result={hit,miss,timeout})",
)

MEMORY_CALIBRATION_APPLIED = _meter.create_counter(
    "memory_calibration_applied",
    description="CalibrationStats applied to agent output (labels: agent_id, stable={true,false})",
)

MEMORY_WRITE_QUEUE_DEPTH = _meter.create_gauge(
    "memory_write_queue_depth",
    description="Current MemoryEpisodeWriter asyncio.Queue depth (absolute, use .set())",
)

MEMORY_WRITE_DROPPED_TOTAL = _meter.create_counter(
    "memory_write_dropped_total",
    description="Episode writes dropped because the write queue was full (D-13)",
)

MEMORY_EMBED_LATENCY_MS = _meter.create_histogram(
    "memory_embed_latency_ms",
    description="EmbeddingService latency per call (labels: batch={true,false})",
    unit="ms",
)

MEMORY_EMBED_STALL_SECONDS = _meter.create_gauge(
    "memory_embed_stall_seconds",
    description=(
        "Seconds since last successful embedding queue drain. "
        "Alert threshold: > 30s (F1 — embedding pipeline stall)."
    ),
)

MEMORY_EPISODES_LABELED = _meter.create_gauge(
    "memory_episodes_labeled",
    description=(
        "Total labeled episode count in memory_episodes_labeled (post-run from BackfillJob). "
        "North-star for MEM-03 shadow gate: must reach N>=200 before AGENT_MEMORY_ENABLED."
    ),
)

MEMORY_COHORTS_PROMOTED_TOTAL = _meter.create_counter(
    "memory_cohorts_promoted_total",
    description="Calibration cohorts promoted to memory_calibration_promoted (labels: agent_id)",
)

MEMORY_COHORTS_QUARANTINED_TOTAL = _meter.create_counter(
    "memory_cohorts_quarantined_total",
    description="Cohorts quarantined for feedback loop detection (C-04; labels: agent_id)",
)

MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE = _meter.create_counter(
    "memory_promotion_skipped_n_eligible",
    description=(
        "Cohorts skipped by promotion job because n_eligible is still NULL "
        "(nightly backfill not yet run; F6; labels: agent_id)"
    ),
)

# ---------------------------------------------------------------------------
# Phase 138 — Regime writer metrics
# ---------------------------------------------------------------------------

REGIME_WRITER_ROWS_UPDATED_TOTAL = _meter.create_counter(
    "regime_writer_rows_updated_total",
    description="feature_vectors rows with regime set; labels symbol, tf",
)
REGIME_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram(
    "regime_writer_run_latency_seconds",
    description="Full regime labeler run duration",
    unit="s",
)
REGIME_WRITER_NULL_REGIME_REMAINING = _meter.create_gauge(
    "regime_writer_null_regime_remaining",
    description="feature_vectors rows still regime=NULL after run; labels symbol, tf",
)

# ---------------------------------------------------------------------------
# forward_return_writer (P5)
# ---------------------------------------------------------------------------

FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL = _meter.create_counter(
    "forward_return_writer_rows_written_total",
    description="rows inserted into forward_returns; labels symbol, tf",
)
FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram(
    "forward_return_writer_run_latency_seconds",
    description="Full outcome labeler run duration",
    unit="s",
)
OUTCOME_LABELS_COVERAGE = _meter.create_gauge(
    "forward_returns_coverage",
    description="fraction of feature_vectors rows with labeled forward returns; labels lookahead, symbol, tf",
)

# ---------------------------------------------------------------------------
# ic_engine (P6) — IC measurement substrate for v3.0 AlphaEngine
# ---------------------------------------------------------------------------

IC_ENGINE_CELLS_COMPLETED_TOTAL = _meter.create_counter(
    "ic_engine_cells_completed_total",
    description=(
        "Cells with committed feature_ic_scores row; labels symbol, tf, regime. "
        "skip_reason values: insufficient_n, already_present, missing_regime, degenerate_feature"
    ),
)
IC_ENGINE_CELLS_SKIPPED_TOTAL = _meter.create_counter(
    "ic_engine_cells_skipped_total",
    description=(
        "Cells skipped before IC computation; labels symbol, tf, "
        "skip_reason in {insufficient_n, already_present, missing_regime, degenerate_feature}"
    ),
)
IC_ENGINE_RUN_LATENCY_SECONDS = _meter.create_histogram(
    "ic_engine_run_latency_seconds",
    description="Full IC Engine run duration",
    unit="s",
)
IC_ENGINE_SYMBOLS_COMPLETED_TOTAL = _meter.create_counter(
    "ic_engine_symbols_completed_total",
    description=(
        "Symbols with all TFs computed this run, whether freshly computed or "
        "resumed from an on-disk checkpoint; label source in {fresh, checkpoint}. "
        "Real progress signal -- unlike grepping logs.ic_engine.log, this does not "
        "get confused by pool.map's submission-order result buffering."
    ),
)
IC_ENGINE_RUN_SYMBOLS_TOTAL = _meter.create_gauge(
    "ic_engine_run_symbols_total",
    description="Total symbols in this run -- denominator for symbols_completed_total progress.",
)
FEATURE_IC_PASSING_FDR_TOTAL = _meter.create_gauge(
    "feature_ic_passing_fdr_total",
    description="Count of features passing BH-FDR gate per (symbol, tf)",
)
FEATURE_IC_PASSING_WALKFORWARD_TOTAL = _meter.create_gauge(
    "feature_ic_passing_walkforward_total",
    description="Count of features passing walk-forward gate per (symbol, tf)",
)

# IC health gauges — emitted after each full run (§XIX observability mandate)
IC_SCORE_GAUGE = _meter.create_gauge(
    "ic_engine_ic_score",
    description="Spearman IC per feature x tf x regime; labels feature_name, tf, regime, lookahead",
)
EFFECTIVE_N_GAUGE = _meter.create_gauge(
    "ic_engine_effective_n",
    description="Effective independent observations per (tf, regime); labels tf, regime",
)
FEATURES_SURVIVING_FDR_GAUGE = _meter.create_gauge(
    "ic_engine_features_surviving_fdr",
    description="Count of features surviving BH-FDR per (tf, regime); labels tf, regime",
)
IC_SHARPE_GAUGE = _meter.create_gauge(
    "ic_engine_ic_sharpe",
    description="IC Sharpe per feature x tf x regime; labels feature_name, tf, regime, lookahead",
)
IC_SORTINO_GAUGE = _meter.create_gauge(
    "ic_engine_ic_sortino",
    description=(
        "IC Sortino per feature x tf x regime (mean/semi-deviation from 0). "
        "NULL when all windows positive or sharpe gate not met; labels feature_name, tf, regime, lookahead"
    ),
)
IC_WIN_RATE_GAUGE = _meter.create_gauge(
    "ic_engine_ic_win_rate",
    description=(
        "Fraction of rolling windows where IC > 0 per feature x tf x regime. "
        "NULL when sharpe gate not met; labels feature_name, tf, regime, lookahead"
    ),
)

# ---------------------------------------------------------------------------
# Phase 139 Ensemble + Alpha Emission metrics
# ---------------------------------------------------------------------------

# Ensemble weight gauges — emitted by EnsembleTrainer after each weight solve
ENSEMBLE_FEATURE_WEIGHT_GAUGE = _meter.create_gauge(
    "ensemble_feature_weight",
    description=(
        "Post-cap post-deflation weight per feature in the ensemble. "
        "Labels: feature, symbol, tf, weight_version"
    ),
)
ENSEMBLE_EFFECTIVE_N_GAUGE = _meter.create_gauge(
    "ensemble_effective_n",
    description=(
        "Effective N (inverse HHI = 1/sum(w^2)) of ensemble weights per stratum. "
        "Labels: symbol, tf, weight_version"
    ),
)
ENSEMBLE_SHRINKAGE_INTENSITY_GAUGE = _meter.create_gauge(
    "ensemble_shrinkage_intensity",
    description=(
        "Ledoit-Wolf shrinkage coefficient in [0,1] for the feature covariance estimate. "
        "0 = pure sample covariance; 1 = full shrinkage to scaled identity. "
        "Labels: symbol, tf, weight_version"
    ),
)
ENSEMBLE_FEATURES_ZERO_WEIGHT_GAUGE = _meter.create_gauge(
    "ensemble_features_zero_weight_total",
    description=(
        "Count of features with zero weight after cap + cluster deflation. "
        "Labels: symbol, tf, weight_version"
    ),
)

# Alpha publisher counters — emitted by AlphaPublisher after each batch run
ALPHA_PUBLISHER_EMISSIONS_TOTAL = _meter.create_up_down_counter(
    "alpha_publisher_emissions_total",
    description=(
        "Total alpha events emitted (cumulative per batch run). "
        "Labels: symbol, tf, direction, regime"
    ),
)
ALPHA_PUBLISHER_BARS_SCORED_TOTAL = _meter.create_up_down_counter(
    "alpha_publisher_bars_scored_total",
    description=(
        "Total bars scored by the ensemble alpha computation (cumulative per batch run). "
        "Labels: symbol, tf"
    ),
)
ALPHA_PUBLISHER_REJECTIONS_TOTAL = _meter.create_up_down_counter(
    "alpha_publisher_rejections_total",
    description=(
        "Total bars rejected before emission (below threshold or failed effective_N gate). "
        "Labels: symbol, tf, rejection_reason"
    ),
)

# Phase 142B: CounterfactualTracker IC-decay trigger staleness (D-08/D-10). The IC-decay
# exit trigger reads the most-recent alpha_ensemble_ic row for a frame's (symbol, tf, regime)
# regardless of its age -- no freshness gate blocks the read (D-08), and no recurring
# ensemble_ic_engine cadence exists yet (D-09, follow-on todo 089). This point gauge makes
# that staleness observable instead of silent, per this project's "instrument everything"
# principle (D-10).
COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS = _meter.create_gauge(
    "counterfactual_tracker_ic_row_age_seconds",
    description=(
        "Age in seconds (now - scored_at) of the most-recent alpha_ensemble_ic row consumed "
        "by CounterfactualTracker's IC-decay exit trigger. Never freshness-gated (D-08); a "
        "stale read degrades gracefully (the early IC-decay exit simply fires later than "
        "ideal). Labels: symbol, tf, regime."
    ),
)

# ---------------------------------------------------------------------------
# Phase 143 Plan 03: ic_engine post-run lifecycle hook (LIFECYCLE-03/04/05)
# ---------------------------------------------------------------------------

ALPHA_DECAY_CELLS_FLAGGED = counter(
    "alpha_decay_cells_flagged",
    "Count of (feature, tf, regime) cells this run whose material-fail condition "
    "(standing_weight x |ic_ci_lower| > alpha.decay.materiality_threshold, AND failed) "
    "was true. Incremented per material-fail cell by ic_engine's post-run lifecycle hook.",
)
ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL = counter(
    "alpha_decay_ensemble_rebuild_total",
    "Count of real concept_registry (domain='feature') transitions "
    "(active->shadow_only demotion, shadow_only->active promotion) written by "
    "ic_engine's post-run lifecycle hook. Zero on a regime-shift hold or "
    "idempotency short-circuit.",
)
IC_ENGINE_LAST_RUN_AGE_DAYS = point_gauge(
    "ic_engine_last_run_age_days",
    "Days since the prior successful ic_engine run's completion, set once per run by the "
    "post-run lifecycle hook. In-run diagnostic only (Fable N6) -- detects a too-long gap "
    "retroactively at the start of the NEXT run, not while the gap is ongoing. 0 when no "
    "prior run is found (first run / missing manifest, no alert fires in that case).",
)
