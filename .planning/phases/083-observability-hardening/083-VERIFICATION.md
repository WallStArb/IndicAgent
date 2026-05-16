---
phase: 083-observability-hardening
verified: 2026-05-15T18:30:00Z
status: passed
score: 18/18 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Confirm dlq_events table is queryable in running DB"
    expected: "SELECT COUNT(*) FROM dlq_events returns 0 (empty, ready)"
    why_human: "Requires live DB connection; programmatic check would need runtime credentials"
  - test: "Verify bar.aggregator.dlq topic shows retention.ms=604800000 in Redpanda"
    expected: "rpk topic describe bar.aggregator.dlq shows DYNAMIC_TOPIC_CONFIG 604800000"
    why_human: "Requires running Docker Redpanda container"
  - test: "Run promtool check rules production/alertmanager-rules.yml"
    expected: "Exits 0 — all 5 new alert rules parse correctly"
    why_human: "promtool not installed on this machine per summary"
---

# Phase 083: Observability Hardening Verification Report

**Phase Goal:** OTel span enrichment across base classes, full prometheus_client removal (metrics.py migrated to direct OTel SDK), DLQ consolidation to BaseAgent, DLQ drain agent with hypertable, alert rules.
**Verified:** 2026-05-15T18:30:00Z
**Status:** passed
**Re-verification:** No - initial verification
**Requirements:** None — ROADMAP.md marks this phase as "Level 0 — infrastructure hardening, design doc serves as spec". No P83-* requirement IDs appear in REQUIREMENTS.md. All 6 plan frontmatter files confirm `requirements-completed: []`.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | spans.py exists and exports ATTR_* constants and observed_span async context manager | VERIFIED | File exists at src/observability/spans.py; all 9 ATTR_* constants present; observed_span async context manager with StatusCode.ERROR and record_exception confirmed |
| 2 | OTel Resource includes service.instance.id = hostname:pid | VERIFIED | otel.py line 38: `"service.instance.id": f"{socket.gethostname()}:{os.getpid()}"` |
| 3 | observed_span sets ERROR status and records exception on raise | VERIFIED | spans.py lines 30-32: set_status(StatusCode.ERROR) + record_exception + raise |
| 4 | Every base-class span site sets ERROR status and records exception on raise | VERIFIED | base_agent.py, base_writer.py, base_group_service.py, chain.py all contain StatusCode.ERROR + record_exception |
| 5 | Pipeline span sites in intelligence_pipeline_agent.py use observed_span | VERIFIED | Lines 842 and 1268 use `async with observed_span(...)` |
| 6 | Span attributes use ATTR_* constants from spans.py, not raw strings | VERIFIED | Zero raw "symbol"/"plugin_name"/"intelligence_tier" strings in set_attribute/attributes= blocks across base classes |
| 7 | metrics.py has a single module-level _meter and zero prometheus_client imports | VERIFIED | Single `_meter = otel_metrics.get_meter("indicagent")` at line 18; zero prometheus_client imports |
| 8 | All call sites use OTel .add()/.record() — zero remaining .labels(...).inc()/.set()/.observe() patterns | VERIFIED | grep -rn ".labels(" src/ services/ returns 0 matches |
| 9 | Dead metrics PLUGIN_EXECUTION_TOTAL, PLUGIN_EXECUTION_TIME, FEATURES_TIER_LATENCY_SECONDS, DLQ_DEPTH gone | VERIFIED | None found in metrics.py; BAR_AUDITOR_GAP_FILL_DLQ_DEPTH is a different metric (gap fill counter, not the deleted wrapper) |
| 10 | Wrapper classes OTelCounter/OTelGauge/OTelHistogram and _safe_* helpers are gone | VERIFIED | grep returns 0 matches in src/ and services/ |
| 11 | SERVICE_UP_GAUGE defined in metrics.py; service_auditor_agent imports it | VERIFIED | metrics.py line 403: `SERVICE_UP_GAUGE = _meter.create_up_down_counter(...)`; service_auditor_agent.py line 35 imports it |
| 12 | init_tracing calls removed from signal_metrics_compute_agent and signal_metrics_writer_agent | VERIFIED | grep returns 0 matches in both files |
| 13 | BaseAgent has _get_producer() method; _send_to_dlq uses it; DLQ_DEPTH removed from base.py | VERIFIED | base.py line 401: `def _get_producer`; DLQ_DEPTH absent from base.py; DLQ_MESSAGES_TOTAL present |
| 14 | bar_aggregator_agent, graduation_compute_agent, llm_writer_service use inherited _send_to_dlq via _dlq_topic() override | VERIFIED | All three have `def _dlq_topic()`; no _dlq_producer fields; no _send_to_dlq overrides in graduation/llm_writer |
| 15 | dlq_events hypertable with 30-day retention | VERIFIED | 088_dlq_events.sql has CREATE TABLE + create_hypertable + add_retention_policy(30 days) |
| 16 | dlq_drain_agent subscribes to 15 DLQ topics and writes to dlq_events | VERIFIED | 192-line agent; 15 topic imports; INSERT INTO dlq_events with ON CONFLICT DO NOTHING |
| 17 | dlq_drain registered in _DAG_ORDER at L9 with _LAG_THRESHOLDS and _AGENT_ID_TO_UNIT entries | VERIFIED | service_auditor_agent.py lines 88, 116, 151: all three entries confirmed |
| 18 | Five new alert rules in phase83-observability group; prometheus-client removed from requirements.txt | VERIFIED | alertmanager-rules.yml contains phase83-observability group with 5 rules; requirements.txt has zero prometheus lines; zero prometheus_client imports in src/services/tests |

**Score:** 18/18 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/observability/spans.py` | ATTR_* constants + observed_span() async ctx manager | VERIFIED | 33 lines; all 9 constants; observed_span with ERROR semantics |
| `src/observability/otel.py` | service.instance.id Resource attribute | VERIFIED | Line 38 confirmed |
| `src/observability/metrics.py` | Single _meter, zero prometheus_client | VERIFIED | Line 18; no wrapper classes; SERVICE_UP_GAUGE at line 403 |
| `src/core/agent/base.py` | _get_producer() + refactored _send_to_dlq | VERIFIED | Line 401 _get_producer; DLQ_DEPTH absent |
| `src/core/ai/base_agent.py` | StatusCode.ERROR in span error recording | VERIFIED | Lines 108, 126, 245 confirmed |
| `src/core/agent/base_writer.py` | ATTR_* + StatusCode.ERROR in writer spans | VERIFIED | Lines 35, 281, 320 confirmed |
| `src/core/ai/base_group_service.py` | ATTR_* + StatusCode.ERROR | VERIFIED | Lines 238, 263 confirmed |
| `src/core/llm/chain.py` | StatusCode.ERROR + record_exception | VERIFIED | Lines 103-104 confirmed |
| `services/intelligence_pipeline_agent.py` | observed_span at both pipeline span sites | VERIFIED | Lines 842 and 1268 confirmed; import at line 128 |
| `src/core/plugin_circuit_breaker.py` | PLUGIN_DURATION_MS.record() calls | VERIFIED | Lines 302, 373 confirmed |
| `services/service_auditor_agent.py` | SERVICE_UP_GAUGE.add() + dlq_drain registered | VERIFIED | Line 35 import; line 318 .add(); lines 88/116/151 dlq_drain |
| `production/migrations/088_dlq_events.sql` | dlq_events hypertable + 30d retention + dedup index | VERIFIED | All three DDL statements present |
| `services/dlq_drain_agent.py` | 15-topic DLQ consumer writing to dlq_events | VERIFIED | 192 lines; 15 imports; INSERT + ON CONFLICT confirmed |
| `production/systemd/indicagent-dlq-drain.service` | ExecStart + SyslogIdentifier | VERIFIED | Lines 12, 18 confirmed |
| `production/scripts/ensure_topics.sh` | retention.ms=604800000 idempotent provisioning | VERIFIED | Both create + alter-config with 604800000 |
| `production/alertmanager-rules.yml` | 5 new rules in phase83-observability group | VERIFIED | All 5 rules confirmed; existing groups intact |
| `requirements.txt` | No prometheus-client line | VERIFIED | grep -i "^prometheus" returns empty |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| services/intelligence_pipeline_agent.py | src/observability/spans.py | `from src.observability.spans import` | WIRED | Line 128 import; used at lines 842, 1268 |
| src/observability/metrics.py | opentelemetry.metrics | `_meter = otel_metrics.get_meter("indicagent")` | WIRED | Line 18; single meter |
| services/service_auditor_agent.py | src/observability/metrics.py | SERVICE_UP_GAUGE import | WIRED | Line 35 import; line 318 usage |
| src/core/plugin_circuit_breaker.py | src/observability/metrics.py | PLUGIN_DURATION_MS.record() | WIRED | Lines 302, 373 usage |
| services/dlq_drain_agent.py | dlq_events table | INSERT INTO dlq_events | WIRED | Line 56 INSERT; line 60 ON CONFLICT |
| services/service_auditor_agent.py | dlq_drain_agent | _DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT | WIRED | Lines 88, 116, 151 |
| services/bar_aggregator_agent.py | src/core/agent/base.py | inherited _send_to_dlq + _dlq_topic() override | WIRED | Line 192 _dlq_topic; line 452 _send_to_dlq |
| services/graduation_compute_agent.py | src/core/agent/base.py | inherited _send_to_dlq + _dlq_topic() override | WIRED | Line 129 _dlq_topic; line 302 _send_to_dlq |
| services/llm_writer_service.py | src/core/agent/base.py | inherited _send_to_dlq (override removed) | WIRED | Line 510 _dlq_topic; no _send_to_dlq override |

### Requirements Coverage

No formal requirement IDs exist for phase 083. The ROADMAP.md explicitly states "Requirements: None (Level 0 — infrastructure hardening, design doc serves as spec)". No P83-* entries in REQUIREMENTS.md. Coverage is N/A.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| src/core/service_utils.py line 26 | Comment reference to `record_plugin_execution(...)` in docstring | Info | Stale comment; record_plugin_execution is correctly deleted from production code and all call sites. No functional impact. |
| services/dlq_drain_agent.py | `agent_id` not set as class attribute — uses `name="dlq_drain_agent"` in `super().__init__()` | Info | Minor: plan specified `agent_id = "dlq_drain"` as class attribute; implementation uses constructor name param. The _AGENT_ID_TO_UNIT mapping uses "dlq_drain_agent" as key which matches the name. Functionally consistent. |

No blockers or warnings found.

### Human Verification Required

#### 1. dlq_events Table Live Check

**Test:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT COUNT(*) FROM dlq_events; SELECT * FROM _timescaledb_catalog.hypertable WHERE table_name='dlq_events';"`
**Expected:** COUNT = 0 (table ready, empty); hypertable row returned
**Why human:** Requires live TimescaleDB; can't verify migration was applied without runtime DB connection

#### 2. Redpanda DLQ Topic Retention

**Test:** `docker exec redpanda rpk topic describe bar.aggregator.dlq | grep retention.ms`
**Expected:** `retention.ms 604800000 DYNAMIC_TOPIC_CONFIG`
**Why human:** Requires running Docker container

#### 3. promtool Rule Validation

**Test:** Install promtool and run `promtool check rules production/alertmanager-rules.yml`
**Expected:** Exits 0 — all rules valid YAML and PromQL
**Why human:** promtool not installed on this machine (noted in summary); structural YAML is correct based on grep verification

#### 4. Dead Redpanda Topics Deleted

**Test:** `docker exec redpanda rpk topic list | grep -E "intelligence\.shadow\.transitions|intelligence\.signal\.audit|market\.data\.quality|ml\.data_quality|pipeline\.data_quality|system\.health\.events"`
**Expected:** Empty — 6 orphaned topics confirmed deleted
**Why human:** Requires running Redpanda container

### Gaps Summary

No gaps. All 18 must-have truths verified against actual codebase. The phase achieved its goal:

- **OTel span enrichment:** spans.py created with ATTR_* constants and observed_span; all 4 base classes enriched with StatusCode.ERROR + record_exception; pipeline spans migrated to observed_span.
- **prometheus_client removal:** metrics.py rewritten with single _meter, zero wrapper classes, zero dead metrics; all .labels().inc()/.set()/.observe() call sites migrated; requirements.txt cleaned.
- **DLQ consolidation:** BaseAgent._get_producer() added; _send_to_dlq consolidated; 3 inline DLQ implementations (bar_aggregator, graduation_compute, llm_writer) replaced with _dlq_topic() override pattern.
- **DLQ drain agent:** dlq_drain_agent.py (192 lines) subscribing to 15 topics; 088_dlq_events.sql migration with hypertable + 30d retention + dedup index; systemd unit installed; registered at L9 in service_auditor.
- **Alert rules:** 5 rules in phase83-observability group (LLMCircuitBreakerOpen, SwarmCapacitySkipRateHigh, ShadowPluginEVDecayed, PipelineP95LatencyRegression, DLQActivity); existing groups untouched.

---

_Verified: 2026-05-15T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
