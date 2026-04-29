"""
Prometheus metrics registry for IndicAgent.

Version: 1.1.0
Last Updated: 2026-04-29
Status: Current ✅

MIGRATION NOTE: The prometheus_client metric definitions below are preserved for
incremental migration. They will be migrated to OTelCounter/OTelGauge/OTelHistogram
wrappers in follow-up work. The HTTP scrape server has been removed — all metrics
are now exported via the OTel Collector push pipeline.

New metrics added in Phase 67+ use OTelCounter/OTelGauge/OTelHistogram wrappers
(defined at the bottom of this file). Base class metrics (base.py, base_writer.py)
have already been migrated to OTel wrappers.
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics
from prometheus_client import Counter, Gauge, Histogram

# Helper function caches — preserved for callers that use counter()/gauge() helpers.
# TODO: migrate callers to OTelCounter/OTelGauge in follow-up work.
_counter_helpers: dict[str, Counter] = {}
_gauge_helpers: dict[str, Gauge] = {}


def counter(name: str, documentation: str) -> Counter:
    if name in _counter_helpers:
        return _counter_helpers[name]
    c = Counter(name, documentation)
    _counter_helpers[name] = c
    return c


def gauge(name: str, documentation: str) -> Gauge:
    if name in _gauge_helpers:
        return _gauge_helpers[name]
    g = Gauge(name, documentation)
    _gauge_helpers[name] = g
    return g


# Core engine metrics
STREAM_READ_TOTAL = Counter("stream_messages_read_total", "Messages read", ["stream", "group"])
STREAM_READ_LAT = Histogram("stream_read_seconds", "XREADGROUP time", ["stream", "group"])
DB_BATCH_WRITE = Histogram("db_batch_write_seconds", "Timescale batch write time")
ENGINE_THROUGHPUT = Gauge("engine_bars_processed", "Bars processed total")
ENGINE_THROUGHPUT_RATE = Gauge("engine_throughput_per_sec", "Bars per second")

# Service orchestrator metrics
SERVICE_HEALTH_GAUGE = Gauge("indicagent_service_health", "Service health status", ["service"])
SERVICE_START_TOTAL = Counter(
    "indicagent_service_starts_total", "Total service starts", ["service"]
)
SERVICE_STOP_TOTAL = Counter("indicagent_service_stops_total", "Total service stops", ["service"])
SERVICE_RESTART_TOTAL = Counter(
    "indicagent_service_restarts_total", "Total service restarts", ["service"]
)

# Plugin execution metrics
PLUGIN_EXECUTION_TOTAL = Counter(
    "plugin_executions_total",
    "Total plugin executions",
    ["plugin_name", "symbol", "timeframe", "status"],
)
PLUGIN_EXECUTION_TIME = Histogram(
    "plugin_execution_seconds", "Plugin execution time", ["plugin_name", "intelligence_tier"]
)
PLUGIN_FALLBACK_TOTAL = Counter(
    "plugin_fallbacks_total", "Plugin fallbacks to direct calculation", ["plugin_name", "reason"]
)
PLUGIN_ACCURACY_GAUGE = Gauge(
    "plugin_accuracy_percentage",
    "Plugin vs direct calculation accuracy",
    ["plugin_name", "symbol", "timeframe"],
)
PLUGIN_STATE_SIZE_GAUGE = Gauge(
    "plugin_state_size_bytes", "Plugin state size in bytes", ["plugin_name", "symbol", "timeframe"]
)

# Per-plugin pipeline metrics
PLUGIN_DURATION_MS = Histogram(
    "intelligence_pipeline_plugin_duration_ms",
    "Per-plugin execution latency",
    ["plugin_name", "tier"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100],
)
PLUGIN_ERRORS_TOTAL = Counter(
    "intelligence_pipeline_plugin_errors_total",
    "Plugin execution errors",
    ["plugin_name", "tier"],
)
THREAD_POOL_WORKERS = Gauge(
    "intelligence_pipeline_thread_pool_workers",
    "Current thread pool worker count",
)

# LangGraph workflow metrics
LANGGRAPH_WORKFLOW_EXECUTION_TOTAL = Counter(
    "langgraph_workflow_executions_total",
    "Total LangGraph workflow executions",
    ["workflow_name", "status"],
)
LANGGRAPH_WORKFLOW_DURATION = Histogram(
    "langgraph_workflow_duration_seconds",
    "LangGraph workflow execution time",
    ["workflow_name", "intelligence_tier"],
)
LANGGRAPH_NODE_EXECUTION_TOTAL = Counter(
    "langgraph_node_executions_total",
    "Total LangGraph node executions",
    ["workflow_name", "node_name", "status"],
)
LANGGRAPH_NODE_DURATION = Histogram(
    "langgraph_node_duration_seconds",
    "LangGraph node execution time",
    ["workflow_name", "node_name"],
)
LANGGRAPH_AGENT_INVOCATIONS_TOTAL = Counter(
    "langgraph_agent_invocations_total",
    "Total agent invocations in LangGraph workflows",
    ["agent_name", "workflow_name", "status"],
)
LANGGRAPH_EVENT_ROUTING_TOTAL = Counter(
    "langgraph_event_routing_total",
    "Total events routed by LangGraph conditional edges",
    ["workflow_name", "source_node", "target_node", "condition"],
)
LANGGRAPH_STATE_SIZE_GAUGE = Gauge(
    "langgraph_workflow_state_size_bytes",
    "LangGraph workflow state size in bytes",
    ["workflow_name", "symbol", "timeframe"],
)
LANGGRAPH_PARALLEL_EXECUTION_GAUGE = Gauge(
    "langgraph_parallel_executions_active",
    "Number of parallel workflow executions active",
    ["workflow_name"],
)

# Hybrid processing metrics
HYBRID_MODE_GAUGE = Gauge(
    "hybrid_processing_active", "Whether hybrid mode is active", ["service", "symbol", "timeframe"]
)
CIRCUIT_BREAKER_STATE = Gauge(
    "plugin_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["plugin_name"],
)

# Circuit breaker additional metrics
CIRCUIT_BREAKER_FAILURES_TOTAL = Counter(
    "circuit_breaker_failures_total",
    "Total circuit breaker failures",
    ["plugin_name", "error_type"],
)
CIRCUIT_BREAKER_SUCCESSES_TOTAL = Counter(
    "circuit_breaker_successes_total",
    "Total circuit breaker successes",
    ["plugin_name"],
)
CIRCUIT_BREAKER_TRANSITIONS_TOTAL = Counter(
    "circuit_breaker_state_transitions_total",
    "Total circuit breaker state transitions",
    ["plugin_name", "from_state", "to_state"],
)
CIRCUIT_BREAKER_OPEN_SECONDS = Histogram(
    "circuit_breaker_open_duration_seconds",
    "Time spent in OPEN state per recovery cycle",
    ["plugin_name"],
    buckets=[1.0, 5.0, 10.0, 60.0, 300.0, 600.0, 1800.0],
)

# Event-driven processing metrics
REDIS_STREAM_EVENT_TOTAL = Counter(
    "redis_stream_events_total",
    "Total Redis Stream events processed",
    ["stream_name", "consumer_group", "status"],
)
REDIS_STREAM_LAG_GAUGE = Gauge(
    "redis_stream_consumer_lag_messages",
    "Redis Stream consumer lag in messages",
    ["stream_name", "consumer_group"],
)

# Persistence Agent Metrics
PERSISTENCE_BATCH_LATENCY = Histogram(
    "persistence_batch_latency_seconds",
    "Time taken to persist batch to database in seconds",
    ["agent_id"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

PERSISTENCE_CONSUMER_LAG = Gauge(
    "persistence_consumer_lag_records",
    "Current consumer lag in records",
    ["agent_id"],
)

EVENT_PROCESSING_DURATION = Histogram(
    "event_processing_duration_seconds",
    "Time to process Redis Stream events",
    ["event_type", "workflow_name"],
)
MARKET_CONDITIONS_GAUGE = Gauge(
    "market_conditions_detected",
    "Current market condition classification (0=ranging, 1=trending, 2=volatile)",
    ["symbol", "timeframe"],
)
PROVIDER_ACTIVE_SUBSCRIPTIONS = Gauge(
    "provider_active_subscriptions",
    "Active data subscriptions per provider",
    ["provider"],
)

# Asset-class filtering metrics
PLUGIN_SKIPPED_TOTAL = Counter(
    "plugin_skipped_total",
    "Total plugin invocations skipped due to asset class",
    ["plugin_name", "asset_class"],
)

# Per-symbol/timeframe bar processing counters (labeled)
INDICATOR_BARS_PROCESSED_LABELED_TOTAL = Counter(
    "indicator_bars_processed_labeled_total",
    "Bars processed by indicator service (labeled by symbol and tf)",
    ["symbol", "tf"],
)
MARKET_ANALYSIS_BARS_PROCESSED_LABELED_TOTAL = Counter(
    "market_analysis_bars_processed_labeled_total",
    "Bars processed by market analysis service (labeled by symbol and tf)",
    ["symbol", "tf"],
)

# Pipeline timing — bar-close to each stage latency (live events only)
BAR_TO_I1_LATENCY = Histogram(
    "indic_bar_to_i1_latency_seconds",
    "Seconds from bar close to I1 computation complete",
    ["symbol", "tf"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
BAR_TO_INTELLIGENCE_LATENCY = Histogram(
    "indic_bar_to_intelligence_latency_seconds",
    "Seconds from bar close to I3-I6 intelligence event published",
    ["symbol", "tf"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)
BAR_TO_SIGNAL_LATENCY = Histogram(
    "indic_bar_to_signal_latency_seconds",
    "Seconds from bar close to I7 signal generated",
    ["symbol", "tf"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)


# Shadow plugin monitoring (Phase 47 — SHADOW-04)
SHADOW_N_RESOLVED = Gauge("shadow_n_resolved", "Resolved shadow signals", ["plugin"])
SHADOW_WIN_RATE = Gauge("shadow_win_rate", "Shadow plugin win rate", ["plugin"])
SHADOW_EV_R = Gauge("shadow_ev_r", "Shadow plugin E[PnL_R]", ["plugin"])
SHADOW_EV_CI_LOWER = Gauge(
    "shadow_ev_ci_lower", "Shadow 95% CI lower bound on E[PnL_R]", ["plugin"]
)
SHADOW_DAYS_TO_GATE = Gauge("shadow_days_to_gate", "Estimated days to N=100 resolved", ["plugin"])
SHADOW_PROMOTION_READY = Gauge(
    "shadow_promotion_ready", "1 when all gate conditions met", ["plugin"]
)


# Agent liveness — last message timestamp per agent (stall detection)
AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS = Gauge(
    "agent_last_message_timestamp_seconds",
    "Unix timestamp of last successfully processed Kafka message per agent",
    ["agent"],
)

# Parity Auditor metrics (Phase 52.5)
PARITY_MATCH_RATE = Gauge(
    "parity_match_rate",
    "Fraction of rows matching between primary and shadow (0.0-1.0)",
    ["symbol", "tf"],
)
SHADOW_AHEAD_ROWS_TOTAL = Counter(
    "shadow_ahead_rows_total",
    "Rows present in shadow but not yet in primary (timing race)",
    ["symbol", "tf"],
)
PARITY_VIOLATIONS_TOTAL = Counter(
    "parity_violations_total",
    "Total field-level parity violations detected",
    ["symbol", "tf"],
)
PARITY_CYCLES_TOTAL = Counter(
    "parity_cycles_total",
    "Total comparison cycles executed by ParityAuditorAgent",
)


# Provider abstraction layer metrics (Phase 54)
# Golden Signals for DataProviderAdapter implementations and MergerAgent.
PROVIDER_BARS_PRODUCED_TOTAL = Counter(
    "provider_bars_produced_total",
    "Total bars produced and published to raw topic per provider",
    ["provider", "agent"],
)
PROVIDER_RECONNECTS_ATTEMPTED_TOTAL = Counter(
    "provider_reconnects_attempted_total",
    "Total reconnection attempts started per provider",
    ["provider", "agent"],
)
PROVIDER_RECONNECTS_SUCCEEDED_TOTAL = Counter(
    "provider_reconnects_succeeded_total",
    "Total reconnection attempts that successfully reestablished the connection",
    ["provider", "agent"],
)
PROVIDER_CONNECTED = Gauge(
    "provider_connected",
    "1 when provider is connected, 0 otherwise",
    ["provider", "agent"],
)
PROVIDER_GAPS_FILLED_TOTAL = Counter(
    "provider_gaps_filled_total",
    "Total gap-fill bars fetched and published per provider",
    ["provider", "agent"],
)
PROVIDER_BARS_DROPPED_TOTAL = Counter(
    "provider_bars_dropped_total",
    "Bars dropped at the provider edge, labeled by reason (queue full, "
    "duplicate, callback error)",
    ["provider", "agent", "reason"],
)
MERGER_BARS_ROUTED_TOTAL = Counter(
    "merger_bars_routed_total",
    "Total bars routed by MergerAgent to canonical market.bars topic",
    ["provider"],
)
MERGER_BARS_DROPPED_TOTAL = Counter(
    "merger_bars_dropped_total",
    "Total bars dropped by MergerAgent (duplicate, stale, or non-primary)",
    ["provider"],
)
MERGER_FAILOVERS_TOTAL = Counter(
    "merger_failovers_total",
    "Total provider failovers executed by MergerAgent",
    ["from_provider", "to_provider"],
)
MERGER_BAR_LATENCY_SECONDS = Histogram(
    "merger_bar_latency_seconds",
    "Seconds between provider publish_ts and MergerAgent consume_ts",
    ["provider"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)


# ---------------------------------------------------------------------------
# LLM Infrastructure Metrics (Phase 56-01)
# ---------------------------------------------------------------------------

LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "LLM call latency per provider and call_type",
    ["provider", "call_type", "status"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

LLM_TOKENS_USED = Counter(
    "llm_tokens_used_total",
    "Total tokens consumed per provider and call_type",
    ["provider", "call_type"],
)

LLM_CACHE_HITS = Counter(
    "llm_cache_hit_total",
    "Semantic cache hits per call_type",
    ["call_type"],
)

LLM_GUARDRAILS_REJECTIONS = Counter(
    "llm_guardrails_rejections_total",
    "LLM responses rejected by guardrails schema validation",
    ["call_type"],
)

LLM_RATE_LIMIT_WAIT = Histogram(
    "llm_rate_limit_wait_seconds",
    "Time spent waiting for rate limit token bucket",
    ["provider"],
    buckets=[0.01, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0],
)


# ---------------------------------------------------------------------------
# ML Observability Metrics (Phase 56-04)
# ---------------------------------------------------------------------------

FEATURE_IC_SCORE = Gauge(
    "feature_ic_score",
    "Information coefficient per feature per regime (updated weekly by MLDiscoveryComputeAgent)",
    ["feature_name", "regime"],
)

DATA_QUALITY_SCORE = Gauge(
    "data_quality_score",
    "Training data quality score 0-1 (updated by MLDataQualityAuditorAgent)",
)

ML_DISCOVERY_FEATURES_EXTRACTED = Gauge(
    "ml_discovery_features_extracted",
    "Number of tsfresh features extracted in last discovery run",
)


# ---------------------------------------------------------------------------
# Observability & Alerting Metrics (Phase 67)
# ---------------------------------------------------------------------------

SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL = Counter(
    "service_auditor_service_restarts_total",
    "Total service restarts triggered by ServiceAuditorAgent",
    ["service_name"],
)

BAR_AUDITOR_GAP_FILL_DLQ_DEPTH = Counter(
    "bar_auditor_gap_fill_dlq_depth",
    "Total gap-fill requests routed to DLQ after retry exhaustion",
)

ALERTING_DISPATCH_TOTAL = Counter(
    "alerting_dispatch_total",
    "Alerts dispatched by channel and status",
    ["channel", "severity", "status"],
)

ALERTING_LATENCY_SECONDS = Histogram(
    "alerting_latency_seconds",
    "Alert dispatch latency in seconds",
    ["channel"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
)


# ---------------------------------------------------------------------------
# DLQ Metrics (Phase 067-07)
# ---------------------------------------------------------------------------

DLQ_DEPTH = Gauge(
    "dlq_depth",
    "Number of messages in Dead Letter Queue",
    ["agent", "topic"],
)

DLQ_MESSAGES_TOTAL = Counter(
    "dlq_messages_total",
    "Total messages routed to Dead Letter Queue",
    ["agent", "topic", "error_type"],
)


# ---------------------------------------------------------------------------
# Regime gate suppression metrics (Phase 68-01)
# ---------------------------------------------------------------------------

REGIME_GATE_SUPPRESSIONS_TOTAL = Counter(
    "regime_gate_suppressions_total",
    "Signals suppressed by regime gate",
    labelnames=["reason", "plugin", "tf"],
)


# ---------------------------------------------------------------------------
# OTel metric wrapper classes (Phase 77-02)
# Drop-in replacements for prometheus_client.Counter/Gauge/Histogram.
# Preserve the .labels(**kwargs).inc()/.set()/.observe() API while delegating
# to the OTel SDK internally.
# ---------------------------------------------------------------------------


class _OTelLabeledCounter:
    def __init__(self, counter, labels: dict):
        self._counter = counter
        self._labels = labels
        # Cumulative value tracker — used by tests that inspect counter increments.
        # Not exported; the real export goes through self._counter.add().
        self._total: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._total += amount
        self._counter.add(amount, self._labels)

    def get(self) -> float:
        """Return the accumulated total. Mirrors prometheus_client Child.get() for tests."""
        return self._total


class OTelCounter:
    """Drop-in replacement for prometheus_client.Counter.

    Preserves .labels(x="y").inc() API while delegating to OTel SDK Counter.add().
    """

    def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._counter = self._meter.create_counter(
            name, description=documentation,
        )
        self._labeled: dict[tuple, _OTelLabeledCounter] = {}

    def labels(self, **kwargs) -> _OTelLabeledCounter:
        key = tuple(sorted(kwargs.items()))
        if key not in self._labeled:
            self._labeled[key] = _OTelLabeledCounter(self._counter, kwargs)
        return self._labeled[key]

    def inc(self, amount: float = 1.0) -> None:
        self._total = getattr(self, "_total", 0.0) + amount
        self._counter.add(amount, {})

    def get(self) -> float:
        """Return accumulated total for unlabeled counter. Used by tests."""
        return getattr(self, "_total", 0.0)


class _OTelLabeledGauge:
    def __init__(self, gauge, labels: dict):
        self._gauge = gauge
        self._labels = labels
        self._last_value: float = 0.0

    def set(self, value: float) -> None:
        self._last_value = value
        self._gauge.set(value, self._labels)

    def get(self) -> float:
        """Return the last set value. Used by tests that inspect gauge state."""
        return self._last_value

    def inc(self, amount: float = 1.0) -> None:
        # Gauge.inc() pattern -- set to amount (OTel gauge does not support increment)
        self._last_value = amount
        self._gauge.set(amount, self._labels)


class OTelGauge:
    """Drop-in replacement for prometheus_client.Gauge.

    Preserves .labels(x="y").set(v) API while delegating to OTel SDK Gauge.set().
    """

    def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._gauge = self._meter.create_gauge(
            name, description=documentation,
        )
        self._labeled: dict[tuple, _OTelLabeledGauge] = {}

    def labels(self, **kwargs) -> _OTelLabeledGauge:
        key = tuple(sorted(kwargs.items()))
        if key not in self._labeled:
            self._labeled[key] = _OTelLabeledGauge(self._gauge, kwargs)
        return self._labeled[key]

    def set(self, value: float) -> None:
        self._last_value = value
        self._gauge.set(value, {})

    def get(self) -> float:
        """Return the last set value. Used by tests."""
        return getattr(self, "_last_value", 0.0)


class _OTelLabeledHistogram:
    def __init__(self, histogram, labels: dict):
        self._histogram = histogram
        self._labels = labels
        self._count: int = 0

    def observe(self, value: float) -> None:
        self._count += 1
        self._histogram.record(value, self._labels)

    def get_count(self) -> int:
        """Return number of observations. Used by tests inspecting histogram activity."""
        return self._count


class OTelHistogram:
    """Drop-in replacement for prometheus_client.Histogram.

    Preserves .labels(x="y").observe(v) API while delegating to OTel SDK Histogram.record().
    """

    def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None,
                 buckets: list[float] | None = None):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._histogram = self._meter.create_histogram(
            name, description=documentation,
        )
        self._labeled: dict[tuple, _OTelLabeledHistogram] = {}

    def labels(self, **kwargs) -> _OTelLabeledHistogram:
        key = tuple(sorted(kwargs.items()))
        if key not in self._labeled:
            self._labeled[key] = _OTelLabeledHistogram(self._histogram, kwargs)
        return self._labeled[key]

    def observe(self, value: float) -> None:
        self._count = getattr(self, "_count", 0) + 1
        self._histogram.record(value, {})

    def get_count(self) -> int:
        """Return number of observations. Used by tests."""
        return getattr(self, "_count", 0)


def record_plugin_execution(
    plugin_name: str,
    symbol: str,
    timeframe: str,
    duration_seconds: float,
    status: str = "success",
    intelligence_tier: str = "I1",
) -> None:
    """Record plugin execution metrics."""
    PLUGIN_EXECUTION_TOTAL.labels(
        plugin_name=plugin_name, symbol=symbol, timeframe=timeframe, status=status
    ).inc()

    PLUGIN_EXECUTION_TIME.labels(
        plugin_name=plugin_name, intelligence_tier=intelligence_tier
    ).observe(duration_seconds)


def record_langgraph_workflow(
    workflow_name: str,
    duration_seconds: float,
    status: str = "success",
    intelligence_tier: str = "I5",
) -> None:
    """Record LangGraph workflow execution metrics."""
    LANGGRAPH_WORKFLOW_EXECUTION_TOTAL.labels(workflow_name=workflow_name, status=status).inc()

    LANGGRAPH_WORKFLOW_DURATION.labels(
        workflow_name=workflow_name, intelligence_tier=intelligence_tier
    ).observe(duration_seconds)


def record_langgraph_node(
    workflow_name: str, node_name: str, duration_seconds: float, status: str = "success"
) -> None:
    """Record LangGraph node execution metrics."""
    LANGGRAPH_NODE_EXECUTION_TOTAL.labels(
        workflow_name=workflow_name, node_name=node_name, status=status
    ).inc()

    LANGGRAPH_NODE_DURATION.labels(workflow_name=workflow_name, node_name=node_name).observe(
        duration_seconds
    )


def record_event_routing(
    workflow_name: str, source_node: str, target_node: str, condition: str
) -> None:
    """Record LangGraph conditional edge routing."""
    LANGGRAPH_EVENT_ROUTING_TOTAL.labels(
        workflow_name=workflow_name,
        source_node=source_node,
        target_node=target_node,
        condition=condition,
    ).inc()


def record_redis_stream_event(
    stream_name: str, consumer_group: str, processing_time: float, status: str = "success"
) -> None:
    """Record Redis Stream event processing metrics."""
    REDIS_STREAM_EVENT_TOTAL.labels(
        stream_name=stream_name, consumer_group=consumer_group, status=status
    ).inc()

    # Determine event type from stream name
    if "market:" in stream_name:
        event_type = "market_data"
    elif "indicators:" in stream_name:
        event_type = "indicators"
    elif "patterns:" in stream_name:
        event_type = "patterns"
    else:
        event_type = "unknown"

    EVENT_PROCESSING_DURATION.labels(event_type=event_type, workflow_name="redis_streams").observe(
        processing_time
    )
