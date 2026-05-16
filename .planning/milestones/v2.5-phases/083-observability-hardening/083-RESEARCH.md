# Phase 83: Observability Hardening - Research

**Researched:** 2026-05-15
**Domain:** OTel SDK, Prometheus metrics migration, span enrichment, DLQ hardening, dead code removal
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All decisions are locked - sourced directly from the approved design doc.

1. OTel SDK metrics unification: single `_meter = otel_metrics.get_meter("indicagent")` in metrics.py, all 66 metrics become direct OTel SDK instruments, wrapper classes deleted, prometheus-client removed from requirements.txt
2. New `src/observability/spans.py` with ATTR_* constants + `observed_span()` async context manager; base class span enrichment with error status + exception recording
3. `service.instance.id = f"{socket.gethostname()}:{os.getpid()}"` added to OTel Resource in otel.py
4. 5 new alert rules in production/alertmanager-rules.yml (additive only)
5. DLQ hardening: `dlq_drain_agent` (new L9), `dlq_events` hypertable (30d retention), 7-day DLQ topic retention, `BaseAgent._get_producer()`, consolidate 3 inline DLQ implementations, remove `DLQ_DEPTH` metric
6. Dead code cleanup: 3 dead DLQ topic functions in stream_keys.py, 4 dead metrics, `record_plugin_execution()`, 6 orphaned Redpanda topics, shadow transitions publish removed

### Claude's Discretion
- Wave/plan breakdown for parallel execution
- DB migration numbering (next after 087)
- Exact systemd unit file content for dlq_drain_agent (follow existing pattern)
- Order of metric constant definitions in metrics.py

### Deferred Ideas (OUT OF SCOPE)
None - design doc covers full phase scope.
</user_constraints>

---

## Summary

Phase 83 is a pure infrastructure cleanup with six independent workstreams. The codebase is in a transitional state: 53 metrics use raw `prometheus_client` (Counter/Gauge/Histogram), 13 use OTel wrapper classes (OTelCounter/OTelGauge/OTelHistogram defined in metrics.py), and the wrappers themselves have a bug (each creates its own `_meter` via `get_meter()` instead of sharing one). The OTel migration replaces all 66 metrics with direct OTel SDK instruments backed by a single module-level `_meter`, then removes the wrapper classes, the prometheus-client package, and four dead metrics.

Span enrichment is additive only: the two base classes that have spans (`BaseAIAgent` at lines 82 and 192, `intelligence_pipeline_agent.py` at lines 841 and 1267, `llm/chain.py` at line 93) currently have no error status recording or ATTR_* constants. The new `spans.py` file provides both. `BaseProviderAgent` and `base_writer.py` do not exist as standalone files in their expected paths - the writer base is embedded in the writer service pattern.

DLQ consolidation has three distinct patterns to unify: `bar_aggregator_agent` has a fully separate `_dlq_producer` with its own lifecycle; `graduation_compute_agent` has inline dict construction published via `self._producer`; `llm_writer_service` has its own `_send_to_dlq` method override and its own `_dlq_producer`. The `BaseAgent._send_to_dlq` already handles both `_kafka_producer` and `_producer` via dual `hasattr` branches - the `_get_producer()` refactor consolidates that into a single method.

**Primary recommendation:** Follow the 12-step implementation order from the design doc exactly. Steps 1-5 are pure adds/enrichments with no call site changes. Steps 6-12 are the consolidation and deletion work that requires careful grep verification before removing.

---

## Standard Stack

### Core OTel SDK (already in requirements.txt - confirmed in otel.py imports)
| Library | Purpose | Call Pattern After Migration |
|---------|---------|------------------------------|
| `opentelemetry-sdk` | MeterProvider, TracerProvider, Resource | `_meter.create_counter()`, `.create_histogram()`, `.create_up_down_counter()` |
| `opentelemetry-api` | `otel_metrics.get_meter()`, `trace.get_tracer()` | Module-level `_meter` in metrics.py |
| `opentelemetry-exporter-otlp-proto-grpc` | OTLP push to Collector | Already configured in otel.py |

### OTel SDK Instrument Call Patterns (HIGH confidence - verified in design doc and otel.py)
| Instrument | Create | Record Value | Add Labels |
|------------|--------|--------------|------------|
| Counter | `_meter.create_counter(name, description=...)` | `.add(n, {label_dict})` | Pass dict to `.add()` |
| UpDownCounter (gauge replacement) | `_meter.create_up_down_counter(name, description=...)` | `.add(v, {label_dict})` | Pass dict to `.add()` |
| Histogram | `_meter.create_histogram(name, description=..., unit=...)` | `.record(v, {label_dict})` | Pass dict to `.record()` |

### prometheus_client Migration Table
| prometheus_client pattern | OTel equivalent |
|---------------------------|-----------------|
| `METRIC.labels(k=v).inc()` | `METRIC.add(1, {"k": v})` |
| `METRIC.labels(k=v).inc(n)` | `METRIC.add(n, {"k": v})` |
| `METRIC.labels(k=v).set(v)` | `METRIC.add(v, {"k": v})` |
| `METRIC.labels(k=v).observe(v)` | `METRIC.record(v, {"k": v})` |

---

## Architecture Patterns

### Current metrics.py Structure (VERIFIED by reading file)

The file has three sections that each need different treatment:

**Section 1 (lines 1-331): Raw prometheus_client metrics** - 53 metrics using `Counter()`, `Gauge()`, `Histogram()` directly. These all get migrated to direct OTel SDK instruments.

**Section 2 (lines 333-348): `record_plugin_execution()` helper** - Calls `PLUGIN_EXECUTION_TOTAL` and `PLUGIN_EXECUTION_TIME` which are both dead metrics being deleted. The helper itself is deleted once those metrics are gone. `plugin_circuit_breaker.py` calls this at lines 328 and 413.

**Section 3 (lines 362-596): OTel wrapper classes** - `OTelCounter`, `_OTelLabeledCounter`, `OTelGauge`, `_OTelLabeledGauge`, `OTelHistogram`, `_OTelLabeledHistogram` classes plus `_safe_counter`, `_safe_histogram`, `_safe_gauge` helpers and `_SWARM_BUCKETS`. All deleted.

**Section 4 (lines 494-858): Metrics using wrapper classes** - 13 metrics use `OTelCounter`, `OTelHistogram` wrapper classes (SIGNAL_OUTCOME_TOTAL, LLM_CALL_DURATION, LLM_TOKENS_USED, LLM_CACHE_HITS, LLM_GUARDRAILS_REJECTIONS, LLM_RATE_LIMIT_WAIT, AI_AGENT_INVOCATIONS_TOTAL, AI_AGENT_DURATION_MS). Many later metrics use `_safe_counter`, `_safe_gauge`, `_safe_histogram` helpers. All migrate to direct `_meter.create_*()` calls.

**Section 5 (lines 597-858): `_safe_*` helper metrics** - SWARM_*, INTELLIGENCE_PIPELINE_*, SIGNAL_TRACKER_*, BAR_REPLAY_*, SIGNAL_REPLAY_*, ML_TRAINING_*, etc. All use `_safe_counter`, `_safe_histogram`, `_safe_gauge` wrappers for duplicate-registration safety. These are only needed because `prometheus_client` raises on duplicate registration. OTel meters are idempotent - no protection needed.

### Dead Metrics to Delete (VERIFIED by grep and design doc)

| Metric | Lines in metrics.py | Call sites |
|--------|---------------------|------------|
| `PLUGIN_EXECUTION_TOTAL` | 46-48 | `record_plugin_execution()` only (line 341) |
| `PLUGIN_EXECUTION_TIME` | 47-49 | `record_plugin_execution()` only (line 344) |
| `FEATURES_TIER_LATENCY_SECONDS` | 832-838 | Defined, zero `.record()` calls anywhere |
| `DLQ_DEPTH` | 292-296 | `base.py` lines 379, 394; `llm_writer_service.py` line 40 |

### Dead DLQ Functions in stream_keys.py (VERIFIED by reading file)

| Function | Line | Topic string | Status |
|----------|------|--------------|--------|
| `topic_bar_audit_dlq` | 363 | `bar.audit.dlq` | Zero callers in codebase |
| `topic_signal_audit_dlq` | 369 | `signal.audit.dlq` | Zero callers in codebase |
| `topic_cross_asset_dlq` | 383 | `cross.asset.dlq` | Zero callers in codebase |

`topic_shadow_transitions` exists at line 176 - imported in `shadow_auditor_agent.py` line 27.

### Base Class Span Sites (VERIFIED)

| File | Line | Span name | Has error recording? | Has ATTR_* ? |
|------|------|-----------|---------------------|--------------|
| `src/core/ai/base_agent.py` | 82 | unknown (need to read) | No | No |
| `src/core/ai/base_agent.py` | 192 | unknown (need to read) | No | No |
| `services/intelligence_pipeline_agent.py` | 841 | `pipeline.process_bar` | No | Has `symbol`, `tf` as raw strings |
| `services/intelligence_pipeline_agent.py` | 1267 | `pipeline.run_i7` | No | Has `symbol`, `tf` as raw strings |
| `src/core/llm/chain.py` | 93 | unknown | No | Unknown |

Note: `src/core/base_writer.py` and `src/core/base_provider_agent.py` do NOT exist at those paths. The grep confirmed base_provider_agent.py is missing. Writers likely embed span logic in their specific service files.

### `_send_to_dlq` Current State in BaseAgent (VERIFIED - lines 339-416)

Current implementation already does the dual-producer check via `hasattr(self, "_kafka_producer")` and `hasattr(self, "_producer")` - but as two sequential if/elif blocks. The `_get_producer()` refactor extracts this into a single method that `_send_to_dlq` calls once.

Current `_send_to_dlq` also:
- Imports `DLQ_DEPTH` and calls `.inc()` twice (once per producer branch) - these calls are deleted
- Imports `DLQ_MESSAGES_TOTAL` - stays
- The DLQ_DEPTH removal touches lines 349 (import), 379, 394 (two `.inc()` calls)

### Three Inline DLQ Implementations to Consolidate (VERIFIED)

**`bar_aggregator_agent.py`:**
- Line 123: `self._dlq_producer: KafkaProducerClient | None = None`
- Line 124: `self._dlq_topic: str = ""`  (note: naming conflict - same name as the `_dlq_topic()` method in BaseAgent)
- Lines 224-229: Dedicated DLQ producer setup in `_setup()`
- Lines 254, 261: Teardown in stop logic
- Lines 396-397: Additional stop call
- Lines 467-471: Inline `.produce()` call
- After: Override `_dlq_topic()` method to return `topic_bar_aggregator_dlq(self.env_name)`, call `_send_to_dlq()`. Remove all `_dlq_producer` field references.

**`graduation_compute_agent.py`:**
- Lines 291-308: Inline dict construction + `self._producer.publish()` to `topic_transform_graduation_dlq`
- After: Override `_dlq_topic()` to return `topic_transform_graduation_dlq(self.env_name)`, call `_send_to_dlq(payload, exc)`. `self._producer` is already available.

**`llm_writer_service.py`:**
- Line 416: `self._dlq_producer: KafkaProducerClient | None = None`
- Line 497-499: Own `_dlq_topic()` method override (already correct pattern)
- Lines 565-567: Starts own `_dlq_producer`
- Lines 617-620: Stops own `_dlq_producer`
- Line 40: Imports `DLQ_DEPTH`, `DLQ_MESSAGES_TOTAL`
- Lines 687, 705: Calls `self._send_to_dlq(payload, source_topic, error)` - but this is the OVERRIDE method, not inherited
- After: Remove `_send_to_dlq` override method, remove `_dlq_producer` field + lifecycle. `_dlq_topic()` override stays. Use inherited `BaseAgent._send_to_dlq()`.

### `plugin_circuit_breaker.py` Change (VERIFIED)

Two call sites for `record_plugin_execution()`:
- Line 328: `_record_success()` - success path
- Line 413: `_record_failure()` - failure path

Both need to call `PLUGIN_DURATION_MS.record(execution_time_ms, {"plugin_name": plugin_name, "tier": intelligence_tier})` directly. The import at line 43 (`record_plugin_execution`) is removed; `PLUGIN_DURATION_MS` added to import list.

Note: `PLUGIN_DURATION_MS` takes `{"plugin_name": ..., "tier": ...}` labels (confirmed from metrics.py line 53-55). The current `record_plugin_execution` signature passes `symbol` and `timeframe` to `PLUGIN_EXECUTION_TOTAL` which is being deleted - those labels are not needed for `PLUGIN_DURATION_MS`.

### `service_auditor_agent.py` Change (VERIFIED)

- Line 35: `from src.observability.metrics import SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL, OTelGauge`
- Lines 152-156: `SERVICE_UP_GAUGE = OTelGauge("indicagent_service_up", ..., ["unit"])`
- Line 322: `SERVICE_UP_GAUGE.labels(unit=unit).set(1 if has_metrics else 0)`

After migration:
- `SERVICE_UP_GAUGE` defined in `metrics.py` as `_meter.create_up_down_counter("indicagent_service_up", ...)`
- Import in service_auditor changes to include `SERVICE_UP_GAUGE` from metrics, remove `OTelGauge`
- `.labels(unit=unit).set(v)` becomes `.add(v, {"unit": unit})`

### DB Migration (VERIFIED)

Last migration: `087_llm_calls_agent_attrs.sql`. Next available: **088**.

New file: `production/migrations/088_dlq_events.sql`

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
SELECT add_retention_policy('dlq_events', INTERVAL '30 days');
```

### Systemd Unit Pattern (VERIFIED from `indicagent-alerting-agent.service`)

```ini
[Unit]
Description=IndicAgent DLQ Drain — consumes all DLQ topics, writes to dlq_events
After=network-online.target redpanda.service
Wants=network-online.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/dlq_drain_agent.py
Restart=always
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-dlq-drain
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

No `METRICS_PORT` needed (no scrape endpoint; metrics via OTLP).

### `parity_auditor_agent.py` Reference Pattern (VERIFIED)

`dlq_drain_agent` should follow this exact structure:
- `__init__`: sets `self._pool`, `self._repo`, `self._producer = None`
- `_run()`: creates pool, starts producer, enters timer loop with `asyncio.wait_for(self._stop_event.wait(), timeout=INTERVAL)`
- `stop()`: sets stop event, stops producer, closes pool, calls `super().stop()`
- `_compare_cycle()` equivalent: the drain logic per message batch

Key difference: dlq_drain_agent is a Kafka consumer (not timer-based). It subscribes to all 15 DLQ topics and processes messages as they arrive. More like a writer agent than the parity auditor timer pattern. Use `KafkaConsumerClient` consuming from all 15 topics.

### DLQ Topics (Active - 15 total, to enumerate for dlq_drain_agent subscription)

From `stream_keys.py` (confirmed active, have callers):
1. `topic_roll_dlq` - `market.events.roll.dlq`
2. `topic_signal_dlq` - `intelligence.signal.dlq`
3. `topic_bar_aggregator_dlq` - `bar.aggregator.dlq`
4. `topic_bar_writer_dlq` - `bar.writer.dlq`
5. `topic_feature_writer_dlq` - `feature.writer.dlq`
6. `topic_signal_writer_dlq` - `intelligence.signal.writer.dlq`
7. `topic_lifecycle_writer_dlq` - `lifecycle.writer.dlq`
8. `topic_intelligence_pipeline_dlq` - `intelligence.pipeline.dlq`
9. `topic_signal_tracker_dlq` - `signal.tracker.dlq`
10. `topic_llm_writer_dlq` - `llm.writer.dlq`
11. `topic_transform_graduation_dlq` - `intelligence.transform.graduation.dlq`
12. `topic_signal_lineage_dlq` - `intelligence.signal_lineage.dlq`
13. `topic_ml_orchestrator_dlq` - `ml.orchestrator.dlq`
14. `topic_gap_fill_dlq` - `gap_fill.dlq`
15. `topic_health_events_dlq` - `intelligence.service_auditor.journal.dlq`

To delete (zero callers): `topic_bar_audit_dlq`, `topic_signal_audit_dlq`, `topic_cross_asset_dlq`

### Alert Rules Current State (VERIFIED - production/alertmanager-rules.yml)

Two existing rule groups:
1. `indicagent_pipeline`: ProviderDataStoppage, ServiceDown, ConsumerLagHigh
2. `phase81-signal-lifecycle`: P81_SignalTrackerInvalidSignals, P81_SignalReplayOhlcvGap, P81_SignalReplayUnresolvedGrowing, P81_LifecycleWriterIdempotentSkipHigh

New rules (5 total) go in a new group, e.g. `phase83-observability`:
- LLMCircuitBreakerOpen
- SwarmCapacitySkipRateHigh
- ShadowPluginEVDecayed
- PipelineP95LatencyRegression
- DLQActivity

### `shadow_auditor_agent.py` Cleanup (VERIFIED - lines 27 and import)

- Line 27: `from src.core.stream_keys import topic_shadow_transitions`
- Line 28: `from src.intelligence.schemas import ShadowTransitionEvent`
- The file uses `producer` parameter in `_run_audit()` and passes to `_check_promotion()` / `_check_demotion()`
- Need to read further to find the actual `.publish(topic_shadow_transitions(...), ...)` call
- After: remove `topic_shadow_transitions` import, remove `ShadowTransitionEvent` import (if unused), remove the publish call; the DB write (shadow_transition_log INSERT at line 171) stays

---

## Don't Hand-Roll

| Problem | Use Instead | Why |
|---------|-------------|-----|
| OTel meter per-class instantiation | Single module-level `_meter` in metrics.py | OTel meters are idempotent; current wrapper classes each call `get_meter()` creating separate meter references per instance - this is a bug, not a feature |
| Custom duplicate-registration guards (`_safe_counter` etc.) | Remove entirely | Only needed for prometheus_client's non-idempotent registration; OTel has no such problem |
| Span context manager with error handling | `observed_span()` in spans.py | Avoids repeating try/except/set_status/record_exception at every span site |

---

## Common Pitfalls

### Pitfall 1: OTelGauge uses `create_gauge()` not `create_up_down_counter()`
**What goes wrong:** The existing `OTelGauge` wrapper calls `self._meter.create_gauge()` (line 429 in metrics.py). The OTel Python SDK does not have `create_gauge()` as a first-class method - it has `create_up_down_counter()` for bidirectional values. The design spec says use `create_up_down_counter` for all gauge replacements.
**How to avoid:** Always use `_meter.create_up_down_counter()` for every existing `Gauge` metric.

### Pitfall 2: Label dicts vs `.labels()` chaining
**What goes wrong:** prometheus_client uses `.labels(k=v).inc()` chaining. OTel uses `.add(value, {"k": v})` - the dict goes in the second argument, not via method chaining. Every call site across ~20 service files needs updating.
**How to avoid:** Global grep for `.labels(` after migration to catch any missed call sites. Pattern: `grep -rn "\.labels(" services/ src/` should return zero results after migration.

### Pitfall 3: `bar_aggregator_agent` `_dlq_topic` attribute conflicts with BaseAgent method
**What goes wrong:** `bar_aggregator_agent` has `self._dlq_topic: str = ""` as an instance attribute (line 124). This shadows the `_dlq_topic()` method inherited from BaseAgent. When converting, the instance attribute must be fully removed; the method override must replace it.
**How to avoid:** Remove `self._dlq_topic = ""` assignment entirely. Add `def _dlq_topic(self) -> str | None: return topic_bar_aggregator_dlq(self.env_name)` method.

### Pitfall 4: `llm_writer_service._send_to_dlq` has a different signature than BaseAgent
**What goes wrong:** The override in llm_writer_service has signature `_send_to_dlq(self, payload, source_topic, error_type)` - three args. BaseAgent has `_send_to_dlq(self, payload, error)` - two args. Removing the override means the inherited method is used, which calls `self.topics_consumed[0]` for the source topic. Verify `topics_consumed` is correct in llm_writer.
**How to avoid:** Check `topics_consumed` property in llm_writer before removing override.

### Pitfall 5: Prometheus metric names change from `_total` suffix convention
**What goes wrong:** prometheus_client auto-appends `_total` to Counter names. OTel SDK does not. Existing Grafana dashboards and alert rules query `metric_name_total`. If the OTel Collector's prometheus exporter exposes names differently, dashboards break.
**How to avoid:** The OTel Collector prometheus exporter preserves the `_total` suffix convention for counters. Metric names in metrics.py already include `_total` where appropriate. Verify with `curl localhost:8889/metrics | grep plugin_fallbacks_total` after step 4.

### Pitfall 6: `FEATURES_TIER_LATENCY_SECONDS` is defined at line 832 using `_safe_histogram`
**What goes wrong:** It's near the bottom of the file in the Phase 83 metrics section (added recently). Easy to miss when grepping for "dead" metrics.
**How to avoid:** The design doc explicitly lists it. It has no `.record()` call sites. Confirm with `grep -rn "FEATURES_TIER_LATENCY_SECONDS" .` before deleting.

---

## Code Examples

### OTel SDK metrics.py structure after migration
```python
# Source: design doc + otel.py current pattern
from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("indicagent")  # single shared meter

PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "plugin_fallbacks_total",
    description="Plugin fallbacks to direct calculation",
)
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
    unit="ms",
)
THREAD_POOL_WORKERS = _meter.create_up_down_counter(
    "intelligence_pipeline_thread_pool_workers",
    description="Current thread pool worker count",
)
```

### Call site after migration
```python
# Counter (was: METRIC.labels(plugin_name=name, reason=r).inc())
PLUGIN_FALLBACK_TOTAL.add(1, {"plugin_name": name, "reason": reason})

# UpDownCounter/gauge (was: METRIC.labels(agent=a).set(v))
THREAD_POOL_WORKERS.add(v, {"agent": agent})

# Histogram (was: METRIC.labels(plugin_name=p, tier=t).observe(v))
PLUGIN_DURATION_MS.record(v, {"plugin_name": p, "tier": t})
```

### spans.py (from design doc - exact content)
```python
from contextlib import asynccontextmanager
from opentelemetry import trace
from opentelemetry.trace import StatusCode

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
    _tracer = tracer or trace.get_tracer("indicagent")
    with _tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
```

### BaseAgent._get_producer() (from design doc)
```python
def _get_producer(self):
    if hasattr(self, "_kafka_producer") and self._kafka_producer is not None:
        return self._kafka_producer
    if hasattr(self, "_producer") and self._producer is not None:
        return self._producer
    return None
```

### dlq_drain_agent shell (150 lines, Kafka consumer pattern)
```python
# Subscribes to all 15 DLQ topics
# consumer group: dlq_drain_consumer
# Parses DLQPayload, writes to dlq_events via asyncpg upsert
# Conflict key: (agent, source_topic, routed_at)
# Emits structured log per event
```

### otel.py resource addition (exact line)
```python
import os, socket

resource = Resource.create({
    "service.name": service_name,
    "service.version": os.getenv("APP_VERSION", "dev"),
    "deployment.environment": os.getenv("INDICAGENT_ENV", os.getenv("ENV", "dev")),
    "service.instance.id": f"{socket.gethostname()}:{os.getpid()}",  # NEW
})
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| prometheus_client scrape | OTel OTLP push → Collector → prometheus exporter at :8889 | Already partially migrated; completing the migration removes the dual-system |
| OTelCounter/OTelGauge wrapper classes | Direct `_meter.create_*()` instruments | Wrappers were drop-in replacements; now replace with native SDK |
| Per-instance `get_meter()` calls | Single module-level `_meter` | Bug fix: wrappers created separate meter references per instance |

---

## Open Questions

1. **`src/core/base_writer.py` and `src/core/base_provider_agent.py` do not exist at expected paths**
   - What we know: grep confirmed `base_provider_agent.py` missing. `base_writer.py` also missing as standalone file.
   - What's unclear: Are these embedded in other files, or is the design doc referring to the wrong paths?
   - Recommendation: `grep -rn "start_as_current_span" src/core/` to find all actual span sites in base classes before step 3. The AI base agent spans at lines 82 and 192 are confirmed.

2. **shadow_auditor_agent.py producer lifecycle**
   - What we know: `topic_shadow_transitions` imported at line 27. `_run_audit()` receives a `producer` parameter.
   - What's unclear: Whether the producer needs to remain for other publishes (e.g. demotion events).
   - Recommendation: Read the full `_check_promotion()` and `_check_demotion()` to confirm `topic_shadow_transitions` is the ONLY topic published to. If so, the producer can be removed entirely from the agent. If other topics remain, keep the producer but remove only the shadow_transitions publish.

3. **15 active DLQ topics vs ensure_topics.sh**
   - What we know: 15 DLQ topic functions with callers exist in stream_keys.py.
   - What's unclear: Which of these 15 topics actually exist in Redpanda today vs. which are defined but never provisioned.
   - Recommendation: `docker exec redpanda rpk topic list | grep dlq` before writing ensure_topics.sh to get ground truth.

---

## Sources

### Primary (HIGH confidence)
- `src/observability/metrics.py` - read fully, all 66 metrics identified and categorized
- `src/core/agent/base.py` - read fully, `_send_to_dlq` exact implementation at lines 339-416 confirmed
- `src/observability/otel.py` - read fully, Resource.create() structure at lines 32-38 confirmed
- `src/core/stream_keys.py` - read fully, 3 dead DLQ functions at lines 363-385 confirmed
- `services/parity_auditor_agent.py` - read fully, dlq_drain_agent reference pattern confirmed
- `services/service_auditor_agent.py` - lines 1-157 read, OTelGauge import at line 35, SERVICE_UP_GAUGE at 152, _DAG_ORDER confirmed
- `production/alertmanager-rules.yml` - read fully, existing 7 rules confirmed
- `production/migrations/` - directory listed, next migration is 088
- `production/systemd/indicagent-alerting-agent.service` - read fully, unit file pattern confirmed
- `src/core/plugin_circuit_breaker.py` - read fully, `record_plugin_execution` call sites at lines 328 and 413 confirmed

### Secondary (MEDIUM confidence)
- `services/shadow_auditor_agent.py` lines 1-179 - shadow transitions import confirmed at line 27; full publish call not yet read
- `services/bar_aggregator_agent.py` grep - DLQ producer pattern confirmed via grep
- `services/graduation_compute_agent.py` lines 285-310 - inline DLQ pattern confirmed
- `services/llm_writer_service.py` grep - own `_send_to_dlq` override confirmed

---

## Metadata

**Confidence breakdown:**
- Standard stack (OTel SDK): HIGH - confirmed from otel.py imports and design doc
- metrics.py current state: HIGH - read fully
- Dead metrics identification: HIGH - verified by grep + file read
- Dead DLQ functions: HIGH - verified by reading stream_keys.py
- Base class span sites: MEDIUM - AI base agent confirmed; base_writer and base_provider paths uncertain
- DB migration numbering: HIGH - directory listing confirmed 088 is next
- Systemd unit pattern: HIGH - read reference file

**Research date:** 2026-05-15
**Valid until:** 2026-06-15 (stable infrastructure domain)
