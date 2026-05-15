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

## Implementation Order

Ordered to maintain a working system at each step:

1. **`spans.py`** — new file, no dependencies broken
2. **`otel.py`** — add `service.instance.id`, remove old metric init
3. **Base class span enrichment** — add error status/recording + ATTR_* constants to all existing spans
4. **`metrics.py` migration** — replace all metrics with OTel SDK; update all call sites in same commit
5. **Business logic cleanup** — remove 3 violations (init_tracing calls, OTelGauge import)
6. **Alert rules** — add 4 new rules to `alertmanager-rules.yml`
7. **`requirements.txt`** — remove `prometheus-client`

Each step is independently testable. Steps 1-3 are additive. Steps 4-5 are the only breaking changes (to internal call sites only — no external interface changes).

---

## Testing

- `pytest tests/unit/` must remain green after each step
- Metric emission verified via `curl localhost:8889/metrics | grep <metric_name>`
- Trace exemplar verified: after step 4, a histogram observation during an active span should produce an exemplar with `trace_id` in the Prometheus exposition format
- Alert rules verified via `promtool check rules production/alertmanager-rules.yml`
