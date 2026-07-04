# Observability Hardening Design

**Date:** 2026-05-15  
**Status:** Approved  
**Scope:** Unify metrics on OTel SDK, enrich spans, eliminate dead code, close alert gaps

---

## Guiding Principle

Observability is infrastructure, not business logic. Signal code owns signal logic. Base classes own instrumentation. Business logic imports named metrics — never the OTel SDK directly.

---

## Audit Findings

Six gaps identified across the current stack:

| # | Gap | Location |
|---|-----|----------|
| 1 | Two services call `init_tracing()` directly, bypassing `BaseAgent` — logs never reach Loki | `signal_metrics_compute_agent.py`, `signal_metrics_writer_agent.py` |
| 2 | Spans have sparse attributes — no `plugin_name`, `tier`, `signal_id`; can't filter in Tempo | All `start_as_current_span` call sites |
| 3 | No error status on spans — exceptions are logged but spans show OK | All `start_as_current_span` call sites |
| 4 | Dual metrics system — 53 `prometheus_client` + 13 `OTelCounter/Gauge/Histogram` wrappers; wrappers create a new meter per instance (bug); no exemplars | `metrics.py` throughout |
| 5 | No `service.instance.id` in OTel resource — multiple instances indistinguishable in Tempo | `otel.py` |
| 6 | Alert gaps — LLM circuit breaker, swarm degradation, EV[R] decay, pipeline P95 regression | `alertmanager-rules.yml` |

---

## Architecture

```
Business Logic
    │  imports named constants only
    ▼
src/observability/          ← The observability fabric
    metrics.py              ← All metrics as named OTel SDK constants; single _meter
    spans.py                ← ATTR_* constants + observed_span() context manager
    otel.py                 ← init_otel_providers() — called only by BaseAgent.start()
    log_bridge.py           ← OTLP log export — called only by BaseAgent.start()

Base Classes (auto-instrument)
    BaseAgent               ← owns OTel init + service.instance.id
    BaseWriter              ← owns writer.flush / writer.process_message spans
    BaseGroupService        ← owns group.handle_trigger / group.bar_cache_update spans
    BaseAIAgent             ← owns ai.compute / ai.llm_generate spans
    BaseProviderAgent       ← owns provider.process_bar / provider.gap_fill spans

OTel Collector              ← receives OTLP push (metrics + traces + logs)
    │
    ├── Prometheus exporter :8889  ← Grafana/PromQL dashboards unchanged
    ├── Tempo                      ← traces, 7d retention
    └── Loki                       ← logs, 7d retention
```

Exemplar flow: every histogram `.record(value)` call while a span is active automatically embeds the active trace ID. In Grafana, a P99 latency spike becomes a clickable link to the exact trace.

---

## Change 1: OTel SDK Metrics Unification

### What changes

Replace all `prometheus_client` and `OTelCounter/OTelGauge/OTelHistogram` wrapper metrics with direct OTel SDK instruments. All 66 metrics live in `metrics.py` backed by a single module-level `_meter`.

### What is deleted

- `prometheus_client` import and all `Counter`, `Gauge`, `Histogram` usages from `metrics.py`
- `OTelCounter`, `OTelGauge`, `OTelHistogram` wrapper classes (entire class definitions)
- `_OTelLabeledCounter`, `_OTelLabeledGauge`, `_OTelLabeledHistogram` helper classes
- `_safe_counter`, `_safe_gauge`, `_safe_histogram` helpers (OTel meters are idempotent; no duplicate-registration problem)
- `_counter_helpers`, `_gauge_helpers` dicts
- `from prometheus_client import REGISTRY as _REGISTRY` import
- `_SWARM_BUCKETS` list (inlined where used)

### What stays / is updated

```python
# metrics.py — structure after migration
from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("indicagent")  # single shared meter

# All metrics become direct OTel SDK instruments:
PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "plugin_fallbacks_total",
    description="Plugin fallbacks to direct calculation",
)
PLUGIN_EXECUTION_TIME = _meter.create_histogram(
    "plugin_execution_seconds",
    description="Plugin execution time",
    unit="s",
)
# ... all 66 metrics follow this pattern

# counter() / gauge() helpers — same interface, OTel implementation:
def counter(name: str, documentation: str):
    return _meter.create_counter(name, description=documentation)

def gauge(name: str, documentation: str):
    return _meter.create_up_down_counter(name, description=documentation)
```

No UI is currently connected to gauge-type metrics, so `create_up_down_counter` is used for all prometheus `Gauge` replacements. One instrument type, one call pattern — simpler migration, no behavioral difference.

### Call site migration table

| prometheus_client | OTel instrument | Call site |
|---|---|---|
| `Counter.labels(...).inc()` | `create_counter` | `.add(1, {...})` |
| `Counter.labels(...).inc(n)` | `create_counter` | `.add(n, {...})` |
| `Gauge.labels(...).set(v)` | `create_up_down_counter` | `.add(v, {...})` |
| `Gauge.labels(...).inc(n)` | `create_up_down_counter` | `.add(n, {...})` |
| `Histogram.labels(...).observe(v)` | `create_histogram` | `.record(v, {...})` |

### otel.py changes

Remove `OTLPMetricExporter` and `PeriodicExportingMetricReader` setup — the `_meter` in `metrics.py` uses whatever `MeterProvider` is set globally. `otel.py` continues to set the global `MeterProvider` (with OTLP push at 15s intervals) before any metric is recorded. Ordering guarantee: `BaseAgent.start()` calls `init_otel_providers()` before any message processing begins.

### Prometheus compatibility

The OTel Collector's `prometheus` exporter at `:8889` continues serving all metrics in PromQL format. Grafana dashboards, alertmanager rules, and PromQL expressions are untouched. The scrape path changes from pull to push-then-expose, invisibly.

---

## Change 2: `spans.py` — Standard Attribute Schema + Error Recording

### New file: `src/observability/spans.py`

```python
from contextlib import asynccontextmanager
from opentelemetry import trace
from opentelemetry.trace import StatusCode

# Standard attribute keys — used by all span sites to ensure consistent naming
ATTR_SYMBOL    = "symbol"
ATTR_TF        = "tf"
ATTR_PLUGIN    = "plugin_name"
ATTR_TIER      = "intelligence_tier"
ATTR_AGENT_ID  = "agent_id"
ATTR_SIGNAL_ID = "signal_id"
ATTR_GROUP_ID  = "group_id"
ATTR_BATCH_SZ  = "batch_size"
ATTR_FLUSH_MS  = "flush_ms"

@asynccontextmanager
async def observed_span(name: str, tracer=None, **attrs):
    """Async context manager: creates a span, records exceptions, sets ERROR status.

    For use only in the two pipeline span sites in intelligence_pipeline_agent.py.
    All other spans are owned by base classes.
    """
    _tracer = tracer or trace.get_tracer("indicagent")
    with _tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
```

### Base class span enrichment

Every existing `start_as_current_span` block in base classes gets:
1. `except` block updated: `span.set_status(StatusCode.ERROR, str(exc))` + `span.record_exception(exc)`
2. Attributes enriched using `ATTR_*` constants
3. `span.set_attribute(ATTR_FLUSH_MS, ...)` etc. replaced with constant references

Files updated: `base_writer.py`, `base_group_service.py`, `base_agent.py` (AI), `base_provider_agent.py`, `intelligence_pipeline_agent.py` (2 spans → use `observed_span`), `src/core/llm/chain.py`.

### What is deleted from business logic

- `signal_metrics_compute_agent.py`: remove `from src.observability.otel import init_tracing` + `init_tracing(...)` call
- `signal_metrics_writer_agent.py`: same
- `service_auditor_agent.py`: remove `OTelGauge` import; move `SERVICE_UP_GAUGE` definition into `metrics.py` as a named constant

---

## Change 3: `service.instance.id` in OTel Resource

`otel.py` — one line addition:

```python
import os, socket

resource = Resource.create({
    "service.name": service_name,
    "service.version": os.getenv("APP_VERSION", "dev"),
    "deployment.environment": os.getenv("INDICAGENT_ENV", "dev"),
    "service.instance.id": f"{socket.gethostname()}:{os.getpid()}",  # NEW
})
```

---

## Change 4: Alert Gap Coverage

Four new rules added to `production/alertmanager-rules.yml`:

```yaml
- alert: LLMCircuitBreakerOpen
  expr: increase(circuit_breaker_state_transitions_total{to_state="open"}[5m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "LLM/IBKR circuit breaker tripped to OPEN ({{ $labels.plugin_name }})"

- alert: SwarmCapacitySkipRateHigh
  expr: >
    rate(swarm_invocations_total{status="capacity_skip"}[5m])
    / rate(swarm_invocations_total[5m]) > 0.5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Swarm agents skipping >50% of invocations — signal quality degraded"

- alert: ShadowPluginEVDecayed
  expr: shadow_ev_r < -0.05
  for: 30m
  labels:
    severity: warning
  annotations:
    summary: "Shadow plugin {{ $labels.plugin }} EV[R] < -0.05 sustained 30m"

- alert: PipelineP95LatencyRegression
  expr: >
    histogram_quantile(0.95,
      rate(intelligence_pipeline_plugin_duration_ms_bucket[10m])
    ) > 500
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pipeline P95 plugin latency > 500ms sustained 5m"
```

---

## What is Removed (Complete List)

### `src/observability/metrics.py`
- `from prometheus_client import Counter, Gauge, Histogram`
- `from prometheus_client import REGISTRY as _REGISTRY`
- Classes: `OTelCounter`, `_OTelLabeledCounter`, `OTelGauge`, `_OTelLabeledGauge`, `OTelHistogram`, `_OTelLabeledHistogram`
- Functions: `_safe_counter`, `_safe_gauge`, `_safe_histogram`
- Dicts: `_counter_helpers`, `_gauge_helpers`
- Variable: `_SWARM_BUCKETS`

### `services/signal_metrics_compute_agent.py`
- `from src.observability.otel import init_tracing`
- `init_tracing("signal-metrics-compute")` call

### `services/signal_metrics_writer_agent.py`
- `from src.observability.otel import init_tracing`
- `init_tracing("signal-metrics-writer")` call

### `services/service_auditor_agent.py`
- `OTelGauge` from import list
- Inline `SERVICE_UP_GAUGE = OTelGauge(...)` construction (moves to `metrics.py`)

### `requirements.txt`
- `prometheus-client` package — removed entirely once all call sites migrated

---

## What is NOT Changed

- All `from src.observability.metrics import X` imports in business logic — correct pattern, stays
- `src/core/kafka_utils.py` W3C trace propagation — correct, stays  
- OTel Collector config, Tempo config, Loki config, Grafana dashboards — unchanged
- `production/alertmanager-rules.yml` existing rules — additive only
- All service business logic, plugin logic, signal logic — zero changes

---

---

## Change 5: DLQ Hardening

### Problem

DLQ is currently a write-only black hole. 18 topic functions defined, 5 topics exist in Redpanda, 0 topics have a consumer. Messages are published and permanently lost to investigation. 24-hour retention means a Friday night incident has no evidence by Monday.

### Architecture

```
All DLQ topics (15 active)
    │  publish
    ▼
dlq_drain_agent (L9, alongside signal_auditor, parity_auditor)
    │
    ├── writes to dlq_events (TimescaleDB) — queryable history
    └── structured log to Loki — real-time searchability
```

One drain consumer for all DLQ topics. DLQ traffic is low by design — these are contract violations, not normal flow. One service, one responsibility.

### `dlq_events` table

```sql
CREATE TABLE dlq_events (
    id          BIGSERIAL,
    routed_at   TIMESTAMPTZ NOT NULL,
    agent       TEXT NOT NULL,
    source_topic TEXT NOT NULL,
    dlq_topic   TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    error_message TEXT NOT NULL,
    payload     JSONB NOT NULL,
    retry_count INT NOT NULL DEFAULT 0
);
SELECT create_hypertable('dlq_events', 'routed_at');
```

Retention: 30 days (matches signal_ledger). Queryable: "show me all parse failures from bar_writer in the last 7 days."

### Topic retention

All DLQ topics set to 7-day retention (`retention.ms=604800000`). Configured via `scripts/infrastructure/kafka/infrastructure_ensure_topics.sh` — idempotent, run at deploy. Non-DLQ topics retain their current settings.

### `_get_producer()` — eliminate `_kafka_producer`/`_producer` ambiguity

Add to `BaseAgent`:

```python
def _get_producer(self):
    """Return the agent's Kafka producer. Override in subclasses that use a different attribute."""
    if hasattr(self, "_kafka_producer") and self._kafka_producer is not None:
        return self._kafka_producer
    if hasattr(self, "_producer") and self._producer is not None:
        return self._producer
    return None
```

`BaseWriter` overrides to return `self._producer`. `_send_to_dlq` calls `self._get_producer()` — no more dual `hasattr` branch in the routing logic.

### Consolidate three stray inline DLQ implementations

| Agent | Current approach | After |
|---|---|---|
| `bar_aggregator_agent` | Dedicated `_dlq_producer`, inline `produce()` call, manual lifecycle | Override `_dlq_topic()`, call `_send_to_dlq()`. Remove `_dlq_producer` field + start/stop lifecycle. |
| `graduation_compute_agent` | Inline dict construction + raw `publish()` | Override `_dlq_topic()`, call `_send_to_dlq()`. |
| `llm_writer_service` | Own `_send_to_dlq` method, own `_dlq_producer`, duplicates base logic | Remove `_send_to_dlq` override + `_dlq_producer`. Use inherited `BaseAgent._send_to_dlq()`. |

### Remove `DLQ_DEPTH` metric

`DLQ_DEPTH` is a monotonic counter named "depth" — it never decrements. It duplicates `DLQ_MESSAGES_TOTAL`. Removed from:
- `src/observability/metrics.py` — definition deleted
- `src/core/agent/base.py` — import + two `.inc()` calls deleted
- `services/llm_writer_service.py` — import + `.inc()` call deleted

`DLQ_MESSAGES_TOTAL` is the canonical DLQ counter and stays.

### DLQ alert

```yaml
- alert: DLQActivity
  expr: increase(dlq_messages_total[5m]) > 0
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "DLQ activity detected — {{ $labels.agent }} routing to {{ $labels.topic }}"
    description: "{{ $value }} messages routed to DLQ in last 5m. Every DLQ message is a contract violation."
```

### `dlq_drain_agent` implementation

~150 lines following `parity_auditor_agent` pattern exactly:
- Subscribes to all 15 active DLQ topics via `topic_*_dlq()` functions
- Parses `DLQPayload` schema; logs raw payload if schema parse fails
- Writes to `dlq_events` via asyncpg upsert (idempotent on `(agent, source_topic, routed_at)`)
- Emits structured log per event: `agent`, `source_topic`, `error_type`, `error_message` — Loki-searchable
- Registered in `_DAG_ORDER` at L9 in `service_auditor_agent.py`

---

## Change 6: Dead Code and Infrastructure Cleanup

Full inventory of code, metrics, topics, and Redpanda state to be removed or corrected.

### Dead DLQ topic functions — delete from `stream_keys.py`

Three functions with zero callers anywhere in the codebase:

| Function | Topic string | Action |
|---|---|---|
| `topic_bar_audit_dlq` | `bar.audit.dlq` | Delete function; topic never created |
| `topic_cross_asset_dlq` | `cross.asset.dlq` | Delete function; topic never created |
| `topic_signal_audit_dlq` | `signal.audit.dlq` | Delete function; topic never created |

### Dead metrics — delete from `metrics.py` and all call sites

| Metric | Why dead | Action |
|---|---|---|
| `PLUGIN_EXECUTION_TOTAL` | Called only via `record_plugin_execution()` which is itself only called by `plugin_circuit_breaker.py`. `PLUGIN_DURATION_MS` is the canonical pipeline metric. Overlapping coverage, different cardinality. | Delete metric + `record_plugin_execution()` helper. Update `plugin_circuit_breaker.py` to call `PLUGIN_DURATION_MS` directly. |
| `PLUGIN_EXECUTION_TIME` | Same as above — second histogram for the same data as `PLUGIN_DURATION_MS`. | Delete. |
| `FEATURES_TIER_LATENCY_SECONDS` | Defined, never observed anywhere. | Delete. |
| `DLQ_DEPTH` | Monotonic counter misnamed as depth. Replaced by `DLQ_MESSAGES_TOTAL`. | Delete (covered in Change 5). |

`LANGGRAPH_WORKFLOW_DURATION`, `LANGGRAPH_WORKFLOW_EXECUTION_TOTAL`, `LLM_CALL_DURATION`, and `LLM_RATE_LIMIT_WAIT` are called via `record_langgraph_workflow()` / `record_llm_call()` helpers — not dead, scanner false positive.

### Orphaned Redpanda topics — no active consumer group

These topics exist in Redpanda and have publishers but no consumer has ever subscribed:

| Topic | Publisher | Assessment | Action |
|---|---|---|---|
| `intelligence.shadow.transitions` | `shadow_auditor_agent` | Published but never consumed. Shadow drain is handled via DB writes directly. | Delete topic; remove `topic_shadow_transitions` from `stream_keys.py` and publish call from `shadow_auditor_agent.py`. |
| `intelligence.signal.audit` | No code references found | Orphaned — created at some point, never used. | Delete topic from Redpanda. |
| `market.data.quality` | No code references found | Orphaned. | Delete topic from Redpanda. |
| `ml.data_quality.alerts` | No code references found | Orphaned. | Delete topic from Redpanda. |
| `pipeline.data_quality` | No code references found | Orphaned. | Delete topic from Redpanda. |
| `system.health.events` | No code references found | Orphaned. | Delete topic from Redpanda. |
| `market.ticks` | SSE API reads it | Consumed by SSE (`src/api/routes/sse.py`) — not a Kafka consumer group. Keep. | No action. |
| `ctx.snapshot` | `ctx_writer_agent` consumes | Active consumer (`ctx_writer_group`) with zero lag. | No action. |

Topics to delete from Redpanda (6): `intelligence.shadow.transitions`, `intelligence.signal.audit`, `market.data.quality`, `ml.data_quality.alerts`, `pipeline.data_quality`, `system.health.events`.

All topic deletes must be confirmed empty (`rpk topic describe <name>` shows zero messages) before deletion.

### `record_plugin_execution()` helper — delete

Once `PLUGIN_EXECUTION_TOTAL` and `PLUGIN_EXECUTION_TIME` are removed, `record_plugin_execution()` in `metrics.py` has no body. Delete the function. Update `plugin_circuit_breaker.py` to observe `PLUGIN_DURATION_MS` directly.

### `_safe_counter` / `_safe_gauge` / `_safe_histogram` — already covered in Change 1

Deleted as part of the OTel SDK migration (these exist only because `prometheus_client` raises on duplicate registration).

---

## Implementation Order (updated)

1. **`spans.py`** — new file, ATTR_* constants + `observed_span()`
2. **`otel.py`** — add `service.instance.id`
3. **Base class span enrichment** — error status/recording in all existing span blocks
4. **`metrics.py` OTel migration** — replace all metrics; delete dead metrics and wrappers; update all call sites
5. **Business logic cleanup** — remove `init_tracing` calls, `OTelGauge` import in service_auditor
6. **`BaseAgent._get_producer()`** — eliminate `_kafka_producer`/`_producer` ambiguity
7. **DLQ consolidation** — replace inline DLQ implementations in bar_aggregator, graduation_compute, llm_writer
8. **`dlq_drain_agent`** — new service; `dlq_events` table migration; 7-day retention on DLQ topics
9. **Dead topic / stream_keys cleanup** — delete 3 dead DLQ functions, remove shadow transitions publish, delete 6 orphaned Redpanda topics
10. **Alert rules** — 4 observability alerts + 1 DLQ alert in `alertmanager-rules.yml`
11. **`requirements.txt`** — remove `prometheus-client`
12. **`scripts/infrastructure/kafka/infrastructure_ensure_topics.sh`** — idempotent topic provisioning script

Each step is independently testable and committable. Steps 1-3 are purely additive.

---

## Testing

- `pytest tests/unit/` green after every step
- Metric emission: `curl localhost:8889/metrics | grep <metric_name>`
- Trace exemplar: histogram observation during active span embeds `trace_id` in Prometheus exposition
- Alert rules: `promtool check rules production/alertmanager-rules.yml`
- DLQ drain: publish a test `DLQPayload` to any DLQ topic; verify row appears in `dlq_events` within 10s
- Topic cleanup: `rpk topic list | grep -E "signal.audit|data.quality|shadow.transitions"` returns empty
