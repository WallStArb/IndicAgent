---
phase: 108-self-healing-hardening
verified: 2026-05-28T12:30:00Z
status: passed
score: 7/7 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Verify systemd watchdog is functioning by checking service restarts"
    expected: "Services that fail to call sd_notify within 60s should be auto-restarted by systemd"
    why_human: "Requires real-time observation of systemd behavior and service failures"
  - test: "Verify Grafana alerts are configured for the new OTel metrics"
    expected: "Alerts exist for watchdog_notify_suppressed_total, dlq_quarantine_total, api_health, etc."
    why_human: "Grafana dashboard configuration is external to the codebase"
  - test: "Verify DLQ quarantine prevents infinite retry loops in production"
    expected: "4th identical DLQ message in 24h should be quarantined and not re-attempted"
    why_human: "Requires production traffic pattern observation over 24h window"
  - test: "Verify oneshot JOB_COMPLETED_TOTAL counter reaches OTel collector"
    expected: "Counter increments should be visible in Prometheus/OTel collector after oneshot runs"
    why_human: "Requires OTel collector endpoint configuration verification"
  - test: "Verify stall detection threshold 120s does not cause false positives"
    expected: "No healthy services should be flagged as stalled under normal load"
    why_human: "Requires observation of real service message cadence patterns"
---

# Phase 108: Self-Healing Hardening Verification Report

**Phase Goal:** Self-healing hardening — OTel health signals + systemd watchdogs + DLQ quarantine + stall detection
**Verified:** 2026-05-28T12:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth   | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1   | BaseAgent emits watchdog_notify_total and watchdog_notify_suppressed_total counters | ✓ VERIFIED | Found in src/core/agent/base.py lines 57-66, call sites at 386-388 |
| 2   | All OTel instruments (DLQ_QUARANTINE_TOTAL, CONSUMER_STALL_DETECTED_TOTAL, JOB_COMPLETED_TOTAL, API_HEALTH) are importable | ✓ VERIFIED | All found in src/observability/metrics.py lines 356-386; import test passed |
| 3   | All 25 daemon unit files contain WatchdogSec=60 and NotifyAccess=main | ✓ VERIFIED | grep shows 25 files with WatchdogSec=60; systemd shows WatchdogUSec=1min, NotifyAccess=main |
| 4   | DLQDrainAgent implements rolling 24h quarantine counter seeded from DB at startup | ✓ VERIFIED | Found _quarantine_counts, _DLQ_MAX_RETRIES=3, _seed_quarantine_counts_from_db in services/dlq_drain_agent.py |
| 5   | Migration 099 adds dlq_events.quarantined column | ✓ VERIFIED | Migration file exists with ADD COLUMN quarantined BOOLEAN NOT NULL DEFAULT FALSE |
| 6   | ServiceAuditor stall threshold lowered to 120s with CONSUMER_STALL_DETECTED_TOTAL counter | ✓ VERIFIED | Found _STALL_THRESHOLD_SECONDS = 120 and counter call in services/service_auditor_agent.py |
| 7   | PluginExecutor exposes circuit_breakers read-only property | ✓ VERIFIED | Found @property circuit_breakers at line 192 in src/intelligence/pipeline/executor.py |
| 8   | IntelligencePipelineComputeAgent logs CB open transitions and records bar_e2e_latency_ms | ✓ VERIFIED | Found _cb_open_reported, intelligence_pipeline.cb_open logging, bar_e2e_latency histogram in services/intelligence_pipeline_agent.py |
| 9   | FastAPIInstrumentor wired in src/api/main.py with background api_health refresh | ✓ VERIFIED | Found FastAPIInstrumentor.instrument_app, _refresh_api_health task, API_HEALTH.set calls |
| 10   | API_HEALTH gauge set on /health/database endpoint success/failure branches | ✓ VERIFIED | Found API_HEALTH.set(1) and API_HEALTH.set(0) in src/api/routes/health.py |
| 11   | Oneshot scripts emit JOB_COMPLETED_TOTAL with correct job labels and call flush_and_shutdown_metrics | ✓ VERIFIED | Found in ml_training_agent.py, shadow_auditor_agent.py, roll_batch.py with correct labels |
| 12   | flush_and_shutdown_metrics helper exists in src/observability/metrics.py | ✓ VERIFIED | Found function definition at line 25 with proper error handling |
| 13   | CLAUDE.md updated with OTel Health Contract SOP and Grafana SLO alerts | ✓ VERIFIED | Found "OTel Health Contract (Phase 108 SOP)" section at line 186, version bumped to 5.44.0 |
| 14   | HYGIENE-07 audit document exists and confirms BaseAgent inheritance | ✓ VERIFIED | File 108-HYGIENE-07-AUDIT.md exists with grep audit output |
| 15   | HEAL-02 deferral document exists with rationale and re-evaluation triggers | ✓ VERIFIED | File 108-HEAL-02-DEFERRAL.md exists with 4 re-evaluation triggers |

**Score:** 15/15 truths verified (100%)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `src/observability/metrics.py` | DLQ_QUARANTINE_TOTAL, CONSUMER_STALL_DETECTED_TOTAL, JOB_COMPLETED_TOTAL, API_HEALTH, flush_and_shutdown_metrics | ✓ VERIFIED | All instruments present, flush helper implemented with proper error handling |
| `src/core/agent/base.py` | WATCHDOG_NOTIFY_TOTAL, WATCHDOG_NOTIFY_SUPPRESSED_TOTAL | ✓ VERIFIED | Counters defined with _base_meter, wired into _watchdog_notify() |
| `requirements.txt` | opentelemetry-instrumentation-fastapi>=0.45b0 | ✓ VERIFIED | Dependency present and installed (0.62b1 resolved) |
| `production/systemd/*.service` (25 files) | WatchdogSec=60 + NotifyAccess=main | ✓ VERIFIED | 25 daemon units updated, installed to /etc/systemd/system/, verified with systemctl |
| `production/migrations/099_dlq_quarantine.sql` | ADD COLUMN quarantined + CREATE INDEX | ✓ VERIFIED | Migration file exists with idempotent DDL |
| `services/dlq_drain_agent.py` | _quarantine_counts, _DLQ_MAX_RETRIES, _seed_quarantine_counts_from_db, quarantine logic | ✓ VERIFIED | All components present, count > 3 logic verified |
| `services/service_auditor_agent.py` | _STALL_THRESHOLD_SECONDS = 120, CONSUMER_STALL_DETECTED_TOTAL.add() | ✓ VERIFIED | Threshold lowered, counter call present |
| `src/intelligence/pipeline/executor.py` | circuit_breakers @property | ✓ VERIFIED | Read-only property returning _plugin_circuit_breakers |
| `services/intelligence_pipeline_agent.py` | bar_e2e_latency_ms, _cb_open_reported, CB scan, defensive logging | ✓ VERIFIED | Histogram, set, and logging all present with defensive try/except |
| `src/api/main.py` | FastAPIInstrumentor, _refresh_api_health task | ✓ VERIFIED | Instrumentation wired, background task with 30s refresh |
| `src/api/routes/health.py` | API_HEALTH.set(1|0) on both branches | ✓ VERIFIED | Gauge set on success and failure paths |
| `services/ml_training_agent.py` | JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics | ✓ VERIFIED | Counter with job="ml-training", flush in finally |
| `services/shadow_auditor_agent.py` | JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics | ✓ VERIFIED | Counter with job="shadow-auditor", flush in finally |
| `production/scripts/roll_batch.py` | JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics | ✓ VERIFIED | Counter with job="roll-batch", flush in finally |
| `CLAUDE.md` | OTel Health Contract SOP section | ✓ VERIFIED | Section added with 5 mandatory signals, Grafana SLO alerts, version bumped to 5.44.0 |
| `.planning/phases/108-self-healing-hardening/108-HYGIENE-07-AUDIT.md` | HYGIENE-07 audit record | ✓ VERIFIED | File exists with grep audit output and verification conclusion |
| `.planning/phases/108-self-healing-hardening/108-HEAL-02-DEFERRAL.md` | HEAL-02 deferral record | ✓ VERIFIED | File exists with rationale, 4 re-evaluation triggers, implementation hints |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `BaseAgent._watchdog_notify()` | WATCHDOG_NOTIFY_TOTAL / SUPPRESSED_TOTAL | .add(1, self._last_msg_ts_attrs) | ✓ WIRED | Call sites present at lines 386-388 |
| `services/dlq_drain_agent.py::_drain_message` | DLQ_QUARANTINE_TOTAL | .add(1, {agent, error_type}) | ✓ WIRED | Call present when count > _DLQ_MAX_RETRIES |
| `services/dlq_drain_agent.py::_setup` | dlq_events table | _seed_quarantine_counts_from_db() | ✓ WIRED | Startup seeding called at line 156 |
| `services/service_auditor_agent.py::stall handler` | CONSUMER_STALL_DETECTED_TOTAL | .add(1, {"unit": unit}) | ✓ WIRED | Call present at line 407 |
| `services/intelligence_pipeline_agent.py::_process_bar_compute` | executor.circuit_breakers | self._executor.circuit_breakers | ✓ WIRED | Public property access for CB scan |
| `services/intelligence_pipeline_agent.py::_process_bar_compute` | bar_e2e_latency_ms histogram | .record(pipeline_latency_ms, ...) | ✓ WIRED | Call present at line 593 |
| `src/api/main.py::lifespan` | API_HEALTH gauge | _refresh_api_health() background task | ✓ WIRED | Task scheduled with asyncio.create_task |
| `src/api/routes/health.py::/database` | API_HEALTH gauge | .set(1|0) on both branches | ✓ WIRED | Set calls present at lines 40, 47 |
| Oneshot scripts exit path | OTLP collector | flush_and_shutdown_metrics() in finally | ✓ WIRED | All three scripts call in finally block |
| `production/systemd/*.service` source | `/etc/systemd/system/` installed | Per-file sudo install | ✓ WIRED | 25 files installed, verified with diff |

### Requirements Coverage

| Requirement | Status | Evidence |
| ----------- | ------ | -------- |
| HEAL-01 (WatchdogSec rollout) | ✓ CLOSED | 25 daemon units have WatchdogSec=60 + NotifyAccess=main, BaseAgent emits watchdog counters |
| HEAL-02 (DB backup) | ✓ DEFERRED | Deferral documented in 108-HEAL-02-DEFERRAL.md with 4 re-evaluation triggers |
| HEAL-03 (Circuit breaker health events) | ✓ CLOSED | PluginExecutor.circuit_breakers property + pipeline CB open logging with structured logs |
| HEAL-04 (DLQ quarantine + stall detection) | ✓ CLOSED | Migration 099 applied, DLQDrainAgent quarantine counter, ServiceAuditor stall threshold 120s + counter |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| None found | — | — | No TODO/FIXME/placeholder comments in new Phase 108 code |

### Human Verification Required

### 1. Verify systemd watchdog is functioning by checking service restarts

**Test:** Monitor `journalctl -f -u indicagent-*` while a service is artificially stalled (stop processing messages)
**Expected:** Service should be restarted by systemd after ~60s of watchdog timeout
**Why human:** Requires real-time observation of systemd behavior and intentional service stall simulation

### 2. Verify Grafana alerts are configured for the new OTel metrics

**Test:** Check Grafana dashboard for alerts on watchdog_notify_suppressed_total, dlq_quarantine_total, api_health, consumer_stall_detected_total, bar_e2e_latency_ms
**Expected:** Alert rules exist with appropriate thresholds (stale > 120s, quarantine > 0, api_health = 0, etc.)
**Why human:** Grafana dashboard configuration is external to the codebase

### 3. Verify DLQ quarantine prevents infinite retry loops in production

**Test:** Inject 4 identical DLQ messages with same (agent, source_topic, error_type) within 24h window
**Expected:** 4th message should be stored with quarantined=TRUE and not re-attempted; dlq_quarantine_total counter should increment
**Why human:** Requires production traffic pattern observation over 24h window and manual message injection

### 4. Verify oneshot JOB_COMPLETED_TOTAL counter reaches OTel collector

**Test:** Trigger oneshot run (e.g., `sudo systemctl start indicant-shadow-auditor`), query OTel collector or Prometheus scrape endpoint
**Expected:** `job_completed_total{job="shadow-auditor",status="success"}` counter should be visible at collector within 30s
**Why human:** Requires OTel collector endpoint configuration verification and external system observation

### 5. Verify stall detection threshold 120s does not cause false positives

**Test:** Monitor `journalctl -u indicagent-service-auditor` during normal market hours for 1 hour
**Expected:** No healthy services should be flagged as stalled (no consumer_stall_detected_total increments)
**Why human:** Requires observation of real service message cadence patterns under production load

### Gaps Summary

No gaps found. All Phase 108 must-haves verified as implemented and substantive.

---

## Phase Summary

Phase 108 successfully delivered all self-healing hardening objectives across 7 plans:

**Wave 1 (Foundation):**
- Plan 01: OTel instruments, BaseAgent watchdog counters, FastAPI dependency
- Plan 02: WatchdogSec=60 rolled out to 25 daemon systemd units

**Wave 2 (Visibility):**
- Plan 03: DLQ quarantine with DB-seeded rolling 24h counter
- Plan 04: Stall detection (360s→120s) + circuit breaker property + pipeline e2e latency
- Plan 05: FastAPI auto-instrumentation + api_health gauge with background refresh
- Plan 06: Oneshot JOB_COMPLETED_TOTAL counter with OTel flush contract

**Wave 3 (Documentation):**
- Plan 07: CLAUDE.md OTel Health Contract SOP, HYGIENE-07 audit, HEAL-02 deferral

All four HEAL requirement IDs are accounted for:
- HEAL-01: CLOSED (Plan 01 + Plan 02)
- HEAL-02: DEFERRED (Plan 07)
- HEAL-03: CLOSED (Plan 04 + Plan 06)
- HEAL-04: CLOSED (Plan 03 + Plan 04)

The phase goal is achieved: OTel health signals, systemd watchdogs, DLQ quarantine, and stall detection are all implemented and ready for production validation.

---
_Verified: 2026-05-28T12:30:00Z_
_Verifier: Claude (gsd-verifier)_
