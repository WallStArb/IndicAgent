---
phase: 083-observability-hardening
verified: 2026-05-16T01:33:22Z
status: gaps_found
score: 20/21 must-haves verified
re_verification:
  previous_status: passed
  previous_score: 18/18
  gaps_closed:
    - "OTel MeterProvider never initialized (ProxyMeterProvider string guard fixed to isinstance check)"
    - "indicagent-dlq-drain service inactive (enabled/started, StartLimitIntervalSec moved to [Unit])"
  gaps_remaining:
    - "3 orphaned Redpanda topics not deleted: intelligence.signal.audit, market.data.quality, system.health.events"
  regressions: []
gaps:
  - truth: "All 6 orphaned Redpanda topics removed"
    status: failed
    reason: "3 of 6 topics still exist in Redpanda: intelligence.signal.audit, market.data.quality, system.health.events. Plan 07 Task 3 was supposed to delete them."
    artifacts: []
    missing:
      - "docker exec redpanda rpk topic delete intelligence.signal.audit market.data.quality system.health.events"
---

# Phase 083: Observability Hardening Verification Report (Re-verification)

**Phase Goal:** Unify metrics on OTel SDK, enrich spans with standard attributes and error recording, close alert gaps, harden DLQ with drain consumer and queryable history, eliminate dead code/topics.
**Verified:** 2026-05-16T01:33:22Z
**Status:** gaps_found
**Re-verification:** Yes - after UAT gap closure (Plans 01-07 complete)

This is a re-verification following the UAT (083-UAT.md) which identified 3 gaps and Plan 07 which closed 2 of them. The previous VERIFICATION.md was dated 2026-05-15T18:30:00Z with status: passed (before UAT ran).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | spans.py exists and exports ATTR_* constants and observed_span async context manager | VERIFIED | File exists; all 9 ATTR_* constants confirmed; observed_span with StatusCode.ERROR + record_exception |
| 2 | OTel Resource includes service.instance.id = hostname:pid | VERIFIED | otel.py line 36: `"service.instance.id": f"{socket.gethostname()}:{os.getpid()}"` |
| 3 | observed_span sets ERROR status and records exception on raise | VERIFIED | spans.py lines 30-32 confirmed |
| 4 | Every base-class span site sets ERROR status and records exception on raise | VERIFIED | base_agent.py lines 108/126/245, base_writer.py, base_group_service.py, chain.py all contain StatusCode.ERROR + record_exception |
| 5 | Pipeline span sites in intelligence_pipeline_agent.py use observed_span | VERIFIED | Lines 842 and 1268 use `async with observed_span(...)`; import at line 128 |
| 6 | Span attributes use ATTR_* constants from spans.py, not raw strings | VERIFIED | Zero raw "symbol"/"plugin_name"/"intelligence_tier" strings in attribute blocks |
| 7 | metrics.py has a single module-level _meter and zero prometheus_client imports | VERIFIED | Single `_meter = otel_metrics.get_meter("indicagent")` at line 18; zero prometheus_client imports |
| 8 | All call sites use OTel .add()/.record() - zero remaining .labels() patterns | VERIFIED | grep -rn ".labels(" src/ services/ returns 0 matches |
| 9 | Dead metrics PLUGIN_EXECUTION_TOTAL, PLUGIN_EXECUTION_TIME, FEATURES_TIER_LATENCY_SECONDS, DLQ_DEPTH gone | VERIFIED | None found in metrics.py |
| 10 | Wrapper classes OTelCounter/OTelGauge/OTelHistogram and _safe_* helpers are gone | VERIFIED | grep returns 0 matches in src/ and services/ |
| 11 | SERVICE_UP_GAUGE defined in metrics.py; service_auditor_agent imports it | VERIFIED | metrics.py line 403; service_auditor_agent line 318 uses SERVICE_UP_GAUGE.add() |
| 12 | init_tracing calls removed from signal_metrics_compute_agent and signal_metrics_writer_agent | VERIFIED | grep returns 0 matches in both files |
| 13 | BaseAgent has _get_producer() method; _send_to_dlq uses it; DLQ_DEPTH removed from base.py | VERIFIED | base.py line 401: def _get_producer; DLQ_DEPTH absent; DLQ_MESSAGES_TOTAL present |
| 14 | bar_aggregator_agent, graduation_compute_agent, llm_writer_service use inherited _send_to_dlq via _dlq_topic() override | VERIFIED | All three have def _dlq_topic(); no _dlq_producer fields; no _send_to_dlq overrides in graduation/llm_writer |
| 15 | dlq_events hypertable with 30-day retention exists | VERIFIED | 088_dlq_events.sql applied; table confirmed in DB; hypertable row present; 30-day retention policy job confirmed (job_id=1034) |
| 16 | dlq_drain_agent subscribes to 15 DLQ topics and writes to dlq_events | VERIFIED | 192-line agent; 30 grep matches (15 imports + 15 return calls); INSERT INTO dlq_events + ON CONFLICT confirmed |
| 17 | dlq_drain registered in _DAG_ORDER at L9 with _LAG_THRESHOLDS and _AGENT_ID_TO_UNIT entries | VERIFIED | service_auditor_agent.py lines 88 (_DAG_ORDER), 116 (_LAG_THRESHOLDS: 500), 151 (_AGENT_ID_TO_UNIT) |
| 18 | Five new alert rules in phase83-observability group; prometheus-client removed from requirements.txt | VERIFIED | alertmanager-rules.yml contains phase83-observability group with 5 rules; requirements.txt has zero prometheus lines |
| 19 | OTel MeterProvider initialized correctly (isinstance guard, not string name check) | VERIFIED | otel.py lines 41+53: isinstance(metrics.get_meter_provider(), MeterProvider) + isinstance(trace.get_tracer_provider(), TracerProvider); OTel metrics confirmed live at :8889 (indicagent_service_up visible) |
| 20 | indicagent-dlq-drain systemd service is active (running) | VERIFIED | `systemctl is-active indicagent-dlq-drain` returns "active"; StartLimitIntervalSec is in [Unit] section (line 5) |
| 21 | All 6 orphaned Redpanda topics removed | FAILED | 3 of 6 topics still exist: intelligence.signal.audit, market.data.quality, system.health.events confirmed present via rpk topic list |

**Score:** 20/21 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/observability/spans.py` | ATTR_* constants + observed_span() async ctx manager | VERIFIED | 33 lines; 9 ATTR_* constants; observed_span with ERROR semantics |
| `src/observability/otel.py` | service.instance.id + isinstance MeterProvider guard | VERIFIED | Line 36 service.instance.id; lines 41/53 isinstance guards |
| `src/observability/metrics.py` | Single _meter, zero prometheus_client, SERVICE_UP_GAUGE | VERIFIED | Line 18 single _meter; line 403 SERVICE_UP_GAUGE |
| `src/core/agent/base.py` | _get_producer() + refactored _send_to_dlq | VERIFIED | Line 401 _get_producer; DLQ_DEPTH absent |
| `src/core/ai/base_agent.py` | StatusCode.ERROR in span error recording | VERIFIED | Lines 108, 126, 245 confirmed |
| `services/intelligence_pipeline_agent.py` | observed_span at both pipeline span sites | VERIFIED | Lines 842 and 1268 confirmed |
| `src/core/plugin_circuit_breaker.py` | PLUGIN_DURATION_MS.record() calls | VERIFIED | Lines 302, 373 confirmed |
| `services/service_auditor_agent.py` | SERVICE_UP_GAUGE.add() + dlq_drain registered | VERIFIED | Line 318 .add(); lines 88/116/151 dlq_drain |
| `production/migrations/088_dlq_events.sql` | dlq_events hypertable + 30d retention + dedup index | VERIFIED | File exists; applied to DB; hypertable + retention confirmed |
| `services/dlq_drain_agent.py` | 15-topic DLQ consumer writing to dlq_events | VERIFIED | 192 lines; 30 topic references; INSERT + ON CONFLICT |
| `production/systemd/indicagent-dlq-drain.service` | ExecStart + StartLimitIntervalSec in [Unit] | VERIFIED | StartLimitIntervalSec at line 5 in [Unit]; service active |
| `production/scripts/ensure_topics.sh` | retention.ms=604800000 idempotent provisioning | VERIFIED | Both create + alter-config with 604800000 |
| `production/alertmanager-rules.yml` | 5 new rules in phase83-observability group | VERIFIED | All 5 rules confirmed; existing groups intact |
| `requirements.txt` | No prometheus-client line | VERIFIED | grep -i "^prometheus" returns empty |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| services/intelligence_pipeline_agent.py | src/observability/spans.py | from src.observability.spans import | WIRED | Line 128 import; used at lines 842, 1268 |
| src/observability/metrics.py | opentelemetry.metrics | _meter = otel_metrics.get_meter("indicagent") | WIRED | Line 18; single meter |
| src/observability/otel.py | opentelemetry.sdk.metrics.MeterProvider | isinstance guard | WIRED | Lines 41, 53 isinstance checks; metrics visible at :8889 |
| services/service_auditor_agent.py | src/observability/metrics.py | SERVICE_UP_GAUGE import | WIRED | Line 35 import; line 318 usage |
| src/core/plugin_circuit_breaker.py | src/observability/metrics.py | PLUGIN_DURATION_MS.record() | WIRED | Lines 302, 373 usage |
| services/dlq_drain_agent.py | dlq_events table | INSERT INTO dlq_events | WIRED | Line 56 INSERT; line 60 ON CONFLICT |
| services/service_auditor_agent.py | dlq_drain_agent | _DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT | WIRED | Lines 88, 116, 151 |
| services/bar_aggregator_agent.py | src/core/agent/base.py | inherited _send_to_dlq + _dlq_topic() override | WIRED | Line 192 _dlq_topic; line 452 _send_to_dlq |
| services/graduation_compute_agent.py | src/core/agent/base.py | inherited _send_to_dlq + _dlq_topic() override | WIRED | Line 129 _dlq_topic; line 302 _send_to_dlq |
| services/llm_writer_service.py | src/core/agent/base.py | inherited _send_to_dlq (override removed) | WIRED | Line 510 _dlq_topic; no _send_to_dlq override |

### Requirements Coverage

No formal requirement IDs exist for phase 083. ROADMAP.md marks this as "Level 0 - infrastructure hardening, design doc serves as spec". No P83-* entries in REQUIREMENTS.md. Coverage is N/A.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| src/core/stream_keys.py | Dead functions deleted, shadow_auditor cleaned | Info | Confirmed absent: topic_bar_audit_dlq, topic_signal_audit_dlq, topic_cross_asset_dlq, topic_shadow_transitions all removed |

No blocker anti-patterns found.

### Gaps Summary

One gap remains open after Plan 07 execution: 3 orphaned Redpanda topics (`intelligence.signal.audit`, `market.data.quality`, `system.health.events`) were not deleted. The plan called for `rpk topic delete` on all three, but the deletion did not take effect. These topics have no consumer code pointing to them (stream_keys.py functions deleted), so they are inert — but they represent incomplete cleanup and the plan's acceptance criterion is not met.

The two major UAT gaps are closed: the OTel MeterProvider isinstance fix is in place and indicagent metrics are live at :8889; the dlq-drain service is active and running with correct systemd configuration.

---

_Verified: 2026-05-16T01:33:22Z_
_Verifier: Claude (gsd-verifier)_
