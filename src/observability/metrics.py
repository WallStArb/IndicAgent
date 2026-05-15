"""
Prometheus metrics registry for IndicAgent.

Legacy prometheus_client metrics coexist with OTel wrappers (OTelCounter,
OTelGauge, OTelHistogram) defined at the bottom. All metrics are exported
via the OTel Collector push pipeline — no HTTP scrape server.
"""

from __future__ import annotations

from opentelemetry import metrics as otel_metrics
from prometheus_client import Counter, Gauge, Histogram

# Helper function caches — used by services that create metrics dynamically.
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


# ---------------------------------------------------------------------------
# Plugin pipeline metrics
# ---------------------------------------------------------------------------

PLUGIN_FALLBACK_TOTAL = Counter(
    "plugin_fallbacks_total", "Plugin fallbacks to direct calculation", ["plugin_name", "reason"]
)
PLUGIN_EXECUTION_TOTAL = Counter(
    "plugin_executions_total",
    "Total plugin executions",
    ["plugin_name", "symbol", "timeframe", "status"],
)
PLUGIN_EXECUTION_TIME = Histogram(
    "plugin_execution_seconds", "Plugin execution time", ["plugin_name", "intelligence_tier"]
)
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

# ---------------------------------------------------------------------------
# Circuit breaker metrics
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_STATE = Gauge(
    "plugin_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    ["plugin_name"],
)
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

# ---------------------------------------------------------------------------
# Persistence metrics
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Provider metrics
# ---------------------------------------------------------------------------

PROVIDER_ACTIVE_SUBSCRIPTIONS = Gauge(
    "provider_active_subscriptions",
    "Active data subscriptions per provider",
    ["provider"],
)
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
    "Bars dropped at the provider edge, labeled by reason",
    ["provider", "agent", "reason"],
)
IBKR_ERROR_326_TOTAL = Counter(
    "ibkr_error_326_total",
    "Error 326 (clientId collision) detections and recovery actions",
    ["provider", "action"],
)
IBKR_CLIENT_ID_CURRENT = Gauge(
    "ibkr_client_id_current",
    "Current IBKR clientId in use (value > base signals rotation)",
    ["provider"],
)

# ---------------------------------------------------------------------------
# Merger metrics
# ---------------------------------------------------------------------------

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
# Shadow plugin metrics
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Agent liveness
# ---------------------------------------------------------------------------

AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS = Gauge(
    "agent_last_message_timestamp_seconds",
    "Unix timestamp of last successfully processed Kafka message per agent",
    ["agent"],
)

# ---------------------------------------------------------------------------
# Parity auditor metrics
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# ML observability metrics
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

# ---------------------------------------------------------------------------
# Service auditor & alerting metrics
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
# DLQ metrics
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
# Regime gate suppression metrics
# ---------------------------------------------------------------------------

REGIME_GATE_SUPPRESSIONS_TOTAL = Counter(
    "regime_gate_suppressions_total",
    "Signals suppressed by regime gate",
    labelnames=["reason", "plugin", "tf"],
)

# Signals flowing through the regime gate's three-band classifier
# (band in {suppressed, soft, full}). Phase 82 D-04.
# Registered via Counter directly (defined before _safe_counter helper below).
REGIME_SOFT_GATE_SIGNALS_TOTAL = Counter(
    "regime_soft_gate_signals_total",
    "Signals flowing through the regime gate's three-band classifier (band in {suppressed, soft, full}).",
    ["band"],
)

# ---------------------------------------------------------------------------
# Feature validation metrics (Phase 82 D-05)
# ---------------------------------------------------------------------------

FEATURE_VALIDATION_DECISIONS_TOTAL = Counter(
    "feature_validation_decisions_total",
    "Total validation decisions written to validation_results per decision label.",
    ["decision"],
)


def record_plugin_execution(
    plugin_name: str,
    symbol: str,
    timeframe: str,
    duration_seconds: float,
    status: str = "success",
    intelligence_tier: str = "I1",
) -> None:
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
    LANGGRAPH_WORKFLOW_EXECUTION_TOTAL.labels(workflow_name=workflow_name, status=status).inc()
    LANGGRAPH_WORKFLOW_DURATION.labels(
        workflow_name=workflow_name, intelligence_tier=intelligence_tier
    ).observe(duration_seconds)


# ---------------------------------------------------------------------------
# OTel metric wrapper classes
# ---------------------------------------------------------------------------


class _OTelLabeledCounter:
    def __init__(self, counter, labels: dict):
        self._counter = counter
        self._labels = labels
        self._total: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._total += amount
        self._counter.add(amount, self._labels)

    def get(self) -> float:
        return self._total


class OTelCounter:
    """Drop-in replacement for prometheus_client.Counter."""

    def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._counter = self._meter.create_counter(name, description=documentation)
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
        return self._last_value

    def inc(self, amount: float = 1.0) -> None:
        self._last_value += amount
        self._gauge.set(self._last_value, self._labels)


class OTelGauge:
    """Drop-in replacement for prometheus_client.Gauge."""

    def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._gauge = self._meter.create_gauge(name, description=documentation)
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
        return self._count


class OTelHistogram:
    """Drop-in replacement for prometheus_client.Histogram."""

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: list[str] | None = None,
        buckets: list[float] | None = None,
    ):
        self._name = name
        self._labelnames = labelnames or []
        self._meter = otel_metrics.get_meter("indicagent")
        self._histogram = self._meter.create_histogram(name, description=documentation)
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
        return getattr(self, "_count", 0)


# ---------------------------------------------------------------------------
# Signal quality metrics (Phase 79 — uses OTel wrapper)
# ---------------------------------------------------------------------------

SIGNAL_OUTCOME_TOTAL = OTelCounter(
    "signal_outcome_total",
    "Signal outcomes by plugin and result",
    labelnames=["setup_plugin", "outcome"],
)

# ---------------------------------------------------------------------------
# LLM infrastructure metrics
# ---------------------------------------------------------------------------

LLM_CALL_DURATION = OTelHistogram(
    "llm_call_duration_seconds",
    "LLM call latency per provider and call_type",
    labelnames=["provider", "call_type", "status"],
)

LLM_TOKENS_USED = OTelCounter(
    "llm_tokens_used_total",
    "Total tokens consumed per provider and call_type",
    labelnames=["provider", "call_type"],
)

LLM_CACHE_HITS = OTelCounter(
    "llm_cache_hit_total",
    "Semantic cache hits per call_type",
    labelnames=["call_type"],
)

LLM_GUARDRAILS_REJECTIONS = OTelCounter(
    "llm_guardrails_rejections_total",
    "LLM responses rejected by guardrails schema validation",
    labelnames=["call_type"],
)

LLM_RATE_LIMIT_WAIT = OTelHistogram(
    "llm_rate_limit_wait_seconds",
    "Time spent waiting for rate limit token bucket",
    labelnames=["provider"],
)

# ---------------------------------------------------------------------------
# AI agent execution metrics
# ---------------------------------------------------------------------------

AI_AGENT_INVOCATIONS_TOTAL = OTelCounter(
    "ai_agent_invocations_total",
    "Total AI agent invocations by agent, group, and status",
    labelnames=["agent_id", "group", "status"],
)

AI_AGENT_DURATION_MS = OTelHistogram(
    "ai_agent_duration_ms",
    "AI agent execution latency in ms",
    labelnames=["agent_id", "group"],
)


# ---------------------------------------------------------------------------
# Zone engine metrics — direct API (counter() helper lacks label support)
# ---------------------------------------------------------------------------

ZONE_TIER_USED = Counter(
    "zone_tier_used_total",
    "Zone engine resolution tier selected per call",
    ["tier"],
)
ZONE_CANDIDATE_COUNT = Histogram(
    "zone_candidate_count",
    "Structural candidates evaluated per zone resolution",
    buckets=[0, 1, 2, 3, 5, 8, 12, 20],
)
ZONE_CLUSTER_DENSITY = Histogram(
    "zone_cluster_density",
    "Cluster quality score (strength × diversity / width_atr)",
    buckets=[0.5, 1, 2, 5, 10, 20, 50],
)
ZONE_WIDTH_ATR = Histogram(
    "zone_width_atr",
    "Final zone width in ATR units",
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
)


def record_llm_call(
    provider: str,
    call_type: str,
    latency_s: float,
    status: str = "success",
    tokens: int = 0,
) -> None:
    LLM_CALL_DURATION.labels(
        provider=provider,
        call_type=call_type,
        status=status,
    ).observe(latency_s)
    if status == "success":
        LLM_TOKENS_USED.labels(provider=provider, call_type=call_type).inc(tokens)


# ---------------------------------------------------------------------------
# Swarm intelligence metrics (Phase 80)
# Duplicate-safe: module reload (e.g., in tests) must not raise ValueError.
# ---------------------------------------------------------------------------

from prometheus_client import REGISTRY as _REGISTRY  # noqa: E402


def _safe_counter(name: str, doc: str, labelnames: list[str]) -> Counter:
    """Register a prometheus_client Counter, returning existing if already registered."""
    try:
        return Counter(name, doc, labelnames)
    except ValueError:
        return _REGISTRY._names_to_collectors[f"{name}_total"]  # type: ignore[return-value]


def _safe_histogram(name: str, doc: str, labelnames: list[str], buckets: list[float]) -> Histogram:
    """Register a prometheus_client Histogram, returning existing if already registered."""
    try:
        return Histogram(name, doc, labelnames, buckets=buckets)
    except ValueError:
        return _REGISTRY._names_to_collectors[name]  # type: ignore[return-value]


def _safe_gauge(name: str, doc: str, labelnames: list[str]) -> Gauge:
    """Register a prometheus_client Gauge, returning existing if already registered."""
    try:
        return Gauge(name, doc, labelnames)
    except ValueError:
        return _REGISTRY._names_to_collectors[name]  # type: ignore[return-value]


_SWARM_BUCKETS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0]

SWARM_INVOCATIONS_TOTAL: Counter = _safe_counter(
    "swarm_invocations_total",
    "Per-agent swarm call rate, error rate, and capacity skips",
    ["agent_id", "timeframe", "status"],
)
SWARM_MULTIPLIER_DISTRIBUTION: Histogram = _safe_histogram(
    "swarm_multiplier_distribution",
    "Per-agent multiplier output distribution over time",
    ["agent_id"],
    _SWARM_BUCKETS,
)
SWARM_AGGREGATED_MULTIPLIER: Histogram = _safe_histogram(
    "swarm_aggregated_multiplier",
    "Final combined multiplier distribution per timeframe",
    ["timeframe"],
    _SWARM_BUCKETS,
)
SWARM_AGENT_WEIGHT: Gauge = _safe_gauge(
    "swarm_agent_weight",
    "Per-agent learned weight by timeframe — key Renaissance health signal",
    ["agent_id", "timeframe"],
)
SWARM_SIGNAL_LEDGER_UPDATE_TOTAL: Counter = _safe_counter(
    "swarm_signal_ledger_update_total",
    "Writer-owned signal_ledger materialization outcomes",
    ["status"],
)

# ---------------------------------------------------------------------------
# Intelligence pipeline publisher metrics (Phase 81)
# ---------------------------------------------------------------------------

INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL: Counter = _safe_counter(
    "intelligence_pipeline_backfill_signals_total",
    "Signals published to intelligence.i7.signals with is_backfill=True (catch-up payloads)",
    ["symbol", "timeframe"],
)

# ---------------------------------------------------------------------------
# Signal tracker intake metrics (Phase 81)
# ---------------------------------------------------------------------------

SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL: Counter = _safe_counter(
    "signal_tracker_invalid_signal_total",
    "Signals rejected by _load_signal() (missing/invalid required fields) and routed to DLQ",
    ["reason"],
)

SIGNAL_TRACKER_BACKFILL_FAST_PATH_TOTAL: Counter = _safe_counter(
    "signal_tracker_backfill_fast_path_total",
    "Backfill signals where TTL elapsed at ingest; published TTL-expired and skipped active index",
    ["symbol", "timeframe"],
)

# ---------------------------------------------------------------------------
# Bar replay provider metrics (Phase 81 — Plan 04)
# ---------------------------------------------------------------------------

BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL: Counter = _safe_counter(
    "bar_replay_provider_bars_published_total",
    "Bars published by BarReplayProviderAgent (progress tracking)",
    labelnames=("symbol", "timeframe"),
)

BAR_REPLAY_PROVIDER_LAG_SECONDS: Gauge = _safe_gauge(
    "bar_replay_provider_lag_seconds",
    "Seconds between last_replayed_ts and NOW(); drops to 0 on completion",
    [],
)

# ---------------------------------------------------------------------------
# Signal replay auditor metrics (Phase 81 — Plan 05)
# North-star metric: signal_replay_unresolved_gauge should converge to 0.
# ---------------------------------------------------------------------------

SIGNAL_REPLAY_UNRESOLVED_GAUGE: Gauge = _safe_gauge(
    "signal_replay_unresolved_gauge",
    "v1 signals with exit_at IS NULL past TTL (north star — target = 0)",
    [],
)

SIGNAL_REPLAY_ATTEMPTED_TOTAL: Counter = _safe_counter(
    "signal_replay_attempted_total",
    "Signals queried for replay each auditor cycle",
    [],
)

SIGNAL_REPLAY_RESOLVED_TOTAL: Counter = _safe_counter(
    "signal_replay_resolved_total",
    "Outcomes successfully computed and published by replay auditor",
    labelnames=("outcome",),
)

SIGNAL_REPLAY_OHLCV_GAP_TOTAL: Counter = _safe_counter(
    "signal_replay_ohlcv_gap_total",
    "Replay attempts where market_data_ohlcv had zero bars in the signal window",
    labelnames=("symbol", "timeframe"),
)

LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL: Counter = _safe_counter(
    "lifecycle_writer_idempotent_skip_total",
    "EXIT writes blocked by idempotency guard (WHERE exit_at IS NULL); validates two-path safety",
    [],
)

# ---------------------------------------------------------------------------
# Signal ledger quality KPI (Phase 81 — Plan 06)
# Updated periodically by SignalMetricsComputeAgent from signal_ledger query.
# ---------------------------------------------------------------------------

SIGNAL_LEDGER_BACKFILL_RATIO: Gauge = _safe_gauge(
    "signal_ledger_backfill_ratio",
    "Fraction of signal_ledger rows last 24h with is_backfill=TRUE (training set quality KPI)",
    [],
)

# ---------------------------------------------------------------------------
# Swarm dispatch latency (Phase 83)
# ---------------------------------------------------------------------------

SWARM_DISPATCH_SECONDS: Histogram = _safe_histogram(
    "swarm_dispatch_seconds",
    "Full swarm trigger-to-result cycle latency (context build + agent fan-out + aggregation)",
    ["symbol", "timeframe"],
    [0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# ---------------------------------------------------------------------------
# AI context cache (Phase 83)
# ---------------------------------------------------------------------------

AI_CONTEXT_CACHE_HITS_TOTAL: Counter = _safe_counter(
    "ai_context_cache_hits_total",
    "AIContextCache.build() returning a fresh context",
    ["group_id"],
)

AI_CONTEXT_CACHE_MISSES_TOTAL: Counter = _safe_counter(
    "ai_context_cache_misses_total",
    "AIContextCache.build() returning None (no entry or stale)",
    ["group_id"],
)

# ---------------------------------------------------------------------------
# DB connection pool (Phase 83)
# ---------------------------------------------------------------------------

DB_POOL_SIZE: Gauge = _safe_gauge(
    "db_pool_size",
    "Current asyncpg pool size (total connections)",
    ["pool"],
)

DB_POOL_IDLE: Gauge = _safe_gauge(
    "db_pool_idle",
    "Current asyncpg pool idle connections",
    ["pool"],
)

# ---------------------------------------------------------------------------
# Signal quality distributions (Phase 83)
# ---------------------------------------------------------------------------

SIGNAL_PNL_R_DISTRIBUTION: Histogram = _safe_histogram(
    "signal_pnl_r_distribution",
    "Realized PnL (R-multiple) distribution per setup plugin",
    ["setup_plugin"],
    [-2.0, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0],
)

SIGNAL_MAE_DISTRIBUTION: Histogram = _safe_histogram(
    "signal_mae_distribution",
    "Max adverse excursion distribution per setup plugin",
    ["setup_plugin"],
    [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0],
)

SIGNAL_MFE_DISTRIBUTION: Histogram = _safe_histogram(
    "signal_mfe_distribution",
    "Max favorable excursion distribution per setup plugin",
    ["setup_plugin"],
    [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
)

# ---------------------------------------------------------------------------
# Kafka publish latency (Phase 83)
# ---------------------------------------------------------------------------

KAFKA_PUBLISH_SECONDS: Histogram = _safe_histogram(
    "kafka_publish_seconds",
    "Kafka producer send_and_wait latency",
    ["topic"],
    [0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
)

# ---------------------------------------------------------------------------
# Per-tier feature computation (Phase 83)
# ---------------------------------------------------------------------------

FEATURES_COMPUTED_TOTAL: Counter = _safe_counter(
    "features_computed_total",
    "Feature rows computed and published per intelligence tier",
    ["tier"],
)

FEATURES_TIER_LATENCY_SECONDS: Histogram = _safe_histogram(
    "features_tier_latency_seconds",
    "Per-tier plugin batch execution latency",
    ["tier"],
    [0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# ---------------------------------------------------------------------------
# Narrative generation (Phase 83)
# ---------------------------------------------------------------------------

NARRATIVE_GENERATION_TOTAL: Counter = _safe_counter(
    "narrative_generation_total",
    "Narrative generation outcomes",
    ["status"],
)

# ---------------------------------------------------------------------------
# ML training (Phase 83)
# ---------------------------------------------------------------------------

ML_TRAINING_SECONDS: Histogram = _safe_histogram(
    "ml_training_seconds",
    "Full ML training cycle duration",
    [],
    [5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)
