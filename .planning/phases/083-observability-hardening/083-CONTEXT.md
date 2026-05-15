# Phase 83: Observability Hardening - Context

**Gathered:** 2026-05-15
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-05-15-observability-hardening-design.md)

<domain>
## Phase Boundary

Six audit findings resolved across the observability stack. Changes are additive or simplifying — zero business logic changes. All changes are independently testable and committable per the implementation order in the design doc.

**In scope:**
1. OTel SDK metrics unification — replace all prometheus_client and OTelCounter/OTelGauge/OTelHistogram wrappers with direct OTel SDK instruments backed by a single `_meter` in `metrics.py`
2. `spans.py` — new file with ATTR_* constants and `observed_span()` async context manager; base class span enrichment with error status + exception recording
3. `otel.py` — add `service.instance.id` = `hostname:pid` to OTel Resource
4. Alert rules — 5 new rules in `production/alertmanager-rules.yml` (4 observability + 1 DLQ)
5. DLQ hardening — `dlq_drain_agent` (new L9 service), `dlq_events` hypertable (30d retention), 7-day retention on DLQ topics, `BaseAgent._get_producer()`, consolidate 3 inline DLQ implementations, remove `DLQ_DEPTH` metric
6. Dead code cleanup — 3 dead DLQ topic functions in `stream_keys.py`, 4 dead metrics (`PLUGIN_EXECUTION_TOTAL`, `PLUGIN_EXECUTION_TIME`, `FEATURES_TIER_LATENCY_SECONDS`, `DLQ_DEPTH`), `record_plugin_execution()` helper, 6 orphaned Redpanda topics deleted, shadow transitions publish removed

**Out of scope:** Any business logic, plugin logic, signal logic, OTel Collector config, Tempo config, Loki config, Grafana dashboards, existing alert rules.

</domain>

<decisions>
## Implementation Decisions

All decisions are locked — sourced directly from the approved design doc.

### Change 1: OTel SDK Metrics Unification (`metrics.py`)
- Single module-level `_meter = otel_metrics.get_meter("indicagent")` — no per-instance meter creation
- All 66 metrics become direct OTel SDK instruments (`create_counter`, `create_histogram`, `create_up_down_counter`)
- `counter()` / `gauge()` helper functions updated to return OTel instruments (same interface, OTel impl)
- prometheus_client call site migration: `Counter.labels().inc()` → `.add(1, {...})`, `Gauge.labels().set(v)` → `.add(v, {...})`, `Histogram.labels().observe(v)` → `.record(v, {...})`
- `create_up_down_counter` used for all Gauge replacements (no UI connected to gauges)
- `OTLPMetricExporter` and `PeriodicExportingMetricReader` setup removed from `otel.py` — `_meter` uses globally set MeterProvider
- Remove from `metrics.py`: `prometheus_client` imports, `OTelCounter`, `_OTelLabeledCounter`, `OTelGauge`, `_OTelLabeledGauge`, `OTelHistogram`, `_OTelLabeledHistogram`, `_safe_counter`, `_safe_gauge`, `_safe_histogram`, `_counter_helpers`, `_gauge_helpers`, `_SWARM_BUCKETS`
- Remove from `requirements.txt`: `prometheus-client` package (after all call sites migrated)
- OTel Collector prometheus exporter at `:8889` continues serving PromQL — Grafana dashboards unchanged

### Change 2: `spans.py` — New File + Base Class Enrichment
- New file `src/observability/spans.py` with ATTR_* constants: `ATTR_SYMBOL`, `ATTR_TF`, `ATTR_PLUGIN`, `ATTR_TIER`, `ATTR_AGENT_ID`, `ATTR_SIGNAL_ID`, `ATTR_GROUP_ID`, `ATTR_BATCH_SZ`, `ATTR_FLUSH_MS`
- `observed_span(name, tracer=None, **attrs)` — async context manager, records exceptions, sets `StatusCode.ERROR`
- For use only in the two pipeline span sites in `intelligence_pipeline_agent.py`
- Base class enrichment: every existing `start_as_current_span` block in base classes gets error status + exception recording + ATTR_* constants
- Files updated: `src/core/agent/base.py`, `src/core/base_writer.py`, `src/core/base_group_service.py`, `src/core/ai/base_agent.py`, `src/core/base_provider_agent.py`, `intelligence_pipeline_agent.py` (2 spans → use `observed_span`), `src/core/llm/chain.py`
- Remove `init_tracing` calls from `signal_metrics_compute_agent.py` and `signal_metrics_writer_agent.py`
- Move `SERVICE_UP_GAUGE` from inline `OTelGauge` construction in `service_auditor_agent.py` to named constant in `metrics.py`

### Change 3: `service.instance.id` in OTel Resource (`otel.py`)
- Add `"service.instance.id": f"{socket.gethostname()}:{os.getpid()}"` to Resource.create()
- Imports needed: `import os, socket`

### Change 4: Alert Rules
- Add 5 rules to `production/alertmanager-rules.yml` (additive only, no existing rules touched):
  - `LLMCircuitBreakerOpen`: `increase(circuit_breaker_state_transitions_total{to_state="open"}[5m]) > 0`, for 1m, severity warning
  - `SwarmCapacitySkipRateHigh`: skip rate > 0.5, for 5m, severity warning
  - `ShadowPluginEVDecayed`: `shadow_ev_r < -0.05`, for 30m, severity warning
  - `PipelineP95LatencyRegression`: histogram_quantile(0.95) > 500ms, for 5m, severity warning
  - `DLQActivity`: `increase(dlq_messages_total[5m]) > 0`, for 1m, severity warning
- Run `promtool check rules` after adding

### Change 5: DLQ Hardening
- `dlq_events` table: `id BIGSERIAL`, `routed_at TIMESTAMPTZ`, `agent TEXT`, `source_topic TEXT`, `dlq_topic TEXT`, `error_type TEXT`, `error_message TEXT`, `payload JSONB`, `retry_count INT DEFAULT 0`. Hypertable on `routed_at`, 30d retention. DB migration file.
- `dlq_drain_agent` (~150 lines, L9 in DAG): subscribes to all 15 active DLQ topics via `topic_*_dlq()` functions, parses `DLQPayload` schema, writes to `dlq_events` via asyncpg upsert on `(agent, source_topic, routed_at)`, emits structured log per event
- DLQ topic retention: 7 days (`retention.ms=604800000`) configured in `production/scripts/ensure_topics.sh` (idempotent)
- `BaseAgent._get_producer()`: checks `_kafka_producer` then `_producer`, returns None if neither. `BaseWriter` overrides to return `self._producer`. `_send_to_dlq` calls `self._get_producer()`.
- Consolidate 3 inline DLQ implementations: `bar_aggregator_agent` (remove `_dlq_producer` field + start/stop + inline produce, use `_dlq_topic()` + `_send_to_dlq()`), `graduation_compute_agent` (same), `llm_writer_service` (remove `_send_to_dlq` override + `_dlq_producer`, use inherited)
- Remove `DLQ_DEPTH` metric from `metrics.py`, `src/core/agent/base.py`, `services/llm_writer_service.py`
- Register `dlq_drain_agent` in `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `service_auditor_agent.py`
- Add systemd unit `indicagent-dlq-drain.service`

### Change 6: Dead Code Cleanup
- Delete from `stream_keys.py`: `topic_bar_audit_dlq`, `topic_cross_asset_dlq`, `topic_signal_audit_dlq` (zero callers)
- Delete from `metrics.py` and call sites: `PLUGIN_EXECUTION_TOTAL`, `PLUGIN_EXECUTION_TIME`, `FEATURES_TIER_LATENCY_SECONDS`, `record_plugin_execution()` helper
- Update `plugin_circuit_breaker.py` to call `PLUGIN_DURATION_MS` directly (was called via `record_plugin_execution()`)
- Delete from Redpanda (confirm empty first): `intelligence.shadow.transitions`, `intelligence.signal.audit`, `market.data.quality`, `ml.data_quality.alerts`, `pipeline.data_quality`, `system.health.events`
- Remove `topic_shadow_transitions` from `stream_keys.py` and shadow transitions publish call from `shadow_auditor_agent.py`

### Implementation Order (from design doc — each step independently committable)
1. `spans.py` — new file (purely additive)
2. `otel.py` — add `service.instance.id`
3. Base class span enrichment — error status/recording + ATTR_* constants
4. `metrics.py` OTel migration — replace all metrics, delete dead ones and wrappers, update all call sites
5. Business logic cleanup — remove `init_tracing` calls, `OTelGauge` import in service_auditor
6. `BaseAgent._get_producer()`
7. DLQ consolidation — replace inline DLQ implementations
8. `dlq_drain_agent` — new service + `dlq_events` table migration + 7-day DLQ topic retention
9. Dead topic / stream_keys cleanup — delete 3 dead DLQ functions, shadow transitions, 6 orphaned Redpanda topics
10. Alert rules — 5 rules in alertmanager-rules.yml
11. `requirements.txt` — remove prometheus-client
12. `production/scripts/ensure_topics.sh` — idempotent topic provisioning

### Testing Strategy
- `pytest tests/unit/ -q` green after every step
- Metric emission: `curl localhost:8889/metrics | grep <metric_name>`
- Alert rules: `promtool check rules production/alertmanager-rules.yml`
- DLQ drain: publish test `DLQPayload` → verify row in `dlq_events` within 10s
- Topic cleanup: `rpk topic list | grep -E "signal.audit|data.quality|shadow.transitions"` returns empty

### Claude's Discretion
- Wave/plan breakdown for parallel execution
- DB migration numbering (next after 086)
- Exact systemd unit file content for dlq_drain_agent (follow existing pattern)
- Order of metric constant definitions in metrics.py

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Spec (primary)
- `docs/plans/2026-05-15-observability-hardening-design.md` — full design: all 6 changes, call site migration tables, what is deleted, what stays

### Observability Infrastructure
- `src/observability/metrics.py` — all current metrics (66 to migrate), wrapper classes to delete
- `src/observability/otel.py` — init_otel_providers, Resource.create — add service.instance.id here
- `src/core/stream_keys.py` — DLQ topic functions, shadow_transitions — delete dead ones here

### Base Classes (span enrichment targets)
- `src/core/agent/base.py` — BaseAgent, _send_to_dlq, _get_producer to add
- `src/core/base_writer.py` — BaseWriter, writer span sites
- `src/core/base_group_service.py` — BaseGroupService, group span sites
- `src/core/ai/base_agent.py` — BaseAIAgent, ai.compute span sites
- `src/core/base_provider_agent.py` — BaseProviderAgent, provider span sites

### Services with inline DLQ (consolidation targets)
- `services/bar_aggregator_agent.py` — has dedicated _dlq_producer, inline produce
- `services/graduation_compute_agent.py` — inline dict construction + raw publish
- `services/llm_writer_service.py` — own _send_to_dlq override to remove
- `services/signal_metrics_compute_agent.py` — init_tracing call to remove
- `services/signal_metrics_writer_agent.py` — init_tracing call to remove
- `services/service_auditor_agent.py` — OTelGauge import + SERVICE_UP_GAUGE inline, _DAG_ORDER
- `services/shadow_auditor_agent.py` — shadow transitions publish to remove

### Infrastructure
- `production/alertmanager-rules.yml` — existing rules (additive only)
- `production/systemd/` — reference for dlq_drain systemd unit pattern
- `src/core/plugin_circuit_breaker.py` — update to call PLUGIN_DURATION_MS directly

### Parity Reference (follow same pattern as dlq_drain_agent)
- `services/parity_auditor_agent.py` — dlq_drain_agent follows this pattern exactly

</canonical_refs>

<specifics>
## Specific Ideas

- `observed_span` is for use only in `intelligence_pipeline_agent.py` (2 span sites) — all other spans owned by base classes
- DLQ upsert key: `(agent, source_topic, routed_at)` — idempotent
- `shadow_ev_r` is the metric name for the ShadowPluginEVDecayed alert
- `dlq_drain_agent` is L9 alongside `signal_auditor`, `parity_auditor`, `alerting_agent`
- Topics to confirm empty before deletion: `intelligence.shadow.transitions`, `intelligence.signal.audit`, `market.data.quality`, `ml.data_quality.alerts`, `pipeline.data_quality`, `system.health.events`
- `market.ticks` is consumed by SSE API — keep (not orphaned)
- `ctx.snapshot` has active consumer group (ctx_writer_group, zero lag) — keep

</specifics>

<deferred>
## Deferred Ideas

None — design doc covers full phase scope.

</deferred>

---

*Phase: 083-observability-hardening*
*Context gathered: 2026-05-15 via PRD Express Path*
