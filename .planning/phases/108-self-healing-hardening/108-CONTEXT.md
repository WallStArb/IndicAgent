# Phase 108: Self-Healing Hardening - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete the OTel health contract for every process in the fleet, close the systemd watchdog gap, and add the missing self-healing signals (CB alerting, DLQ quarantine, stuck consumer detection). After this phase: every service is visible in Grafana with consistent signals, systemd auto-restarts stalled daemons, and three failure classes (plugin failure, DLQ poison pills, stuck consumers) surface as observable OTel metrics before humans notice them.

**Scope anchors:**
1. OTel health contract — defined, implemented in BaseAgent, documented as SOP
2. WatchdogSec — 27 daemon unit files + indicagent-api get WatchdogSec=60
3. Non-BaseAgent Python services migrated to BaseAgent (HYGIENE-07 closes here)
4. FastAPI OTel instrumentation (indicagent-api)
5. Oneshot completion counters (ml-training, roll-batch, shadow-auditor)
6. DLQ quarantine via dlq_events DB (no new Kafka topics)
7. Consumer stall threshold 360s → 120s + OTel counter
8. CLAUDE.md SOP update

**Out of scope:**
- DB backups (deferred — no clear restore scenario identified)
- Next.js dashboard OTel (HTTP health probe sufficient; not in data path)
- Re-delivery loop for DLQ (no retry mechanism exists today; quarantine is DB-level counting)
- New Kafka health event topics (OTel + Prometheus + Grafana is the unified layer)

</domain>

<decisions>
## Implementation Decisions

### Design Principle (applies everywhere)
- **D-01:** OTel is the single health measurement layer. Every service emits OTel → OTel Collector → Prometheus → Grafana. No parallel health event publishing to Kafka for monitoring purposes. Kafka `system.health.events` exists for audit trails, not for monitoring decisions.
- **D-02:** One pane of glass = Grafana. Alerts fire from Grafana on Prometheus metrics. ServiceAuditor reads Prometheus. No ambiguity about which tool is authoritative.
- **D-03:** Renaissance RED method for every service — Rate (messages/sec), Errors (error rate), Duration (latency histogram). These three signals answer "is this service healthy?" for any service type.

### OTel Health Contract (what every daemon MUST emit)
- **D-04:** Mandatory signals for every daemon inheriting BaseAgent:
  - `agent_last_message_timestamp_seconds` (gauge) — liveness; updated on every processed message
  - `agent_crash_total` (counter) — uncaught exceptions in `_run()`
  - `agent_dlq_total` (counter) — every DLQ routing event
  - `watchdog_notify_total` (counter) — every successful sd_notify WATCHDOG=1 ping **[new]**
  - `watchdog_notify_suppressed_total` (counter) — every suppressed ping (agent alive but idle/stalled) **[new]**
- **D-05:** These are implemented once in BaseAgent. Every subclass inherits them automatically. No per-service work needed for new agents.
- **D-06:** Oneshot services (ml-training, roll-batch, shadow-auditor) emit one counter at script end: `job_completed_total{job="<name>", status="success|failure"}`. Three lines of Python. Grafana alerts if `time_since_last_success > 25h`.

### WatchdogSec Rollout
- **D-07:** Add `WatchdogSec=60` to 27 daemon unit files that are currently missing it. `indicagent-api` (uvicorn) is included — uvicorn auto-calls sd_notify when WATCHDOG_USEC is set, zero code change.
- **D-08:** Skip `indicagent-dashboard` (Next.js has no sd_notify; adding WatchdogSec without notify would kill it every 60s; `Restart=always` is sufficient for the dashboard).
- **D-09:** Skip all 13 oneshot unit files (timer-triggered; WatchdogSec does not apply).
- **D-10:** `BaseAgent._watchdog_notify()` already implements sd_notify correctly (reads WATCHDOG_USEC, pings at half interval). The only BaseAgent code change is adding the two OTel counters (D-04).

### Non-BaseAgent Service Migration
- **D-11:** Migrate the 3-5 Python services not yet on BaseAgent to full BaseAgent inheritance. These are identified in HYGIENE-07: `signal_replay_auditor`, `bar_replay_provider`, and any others found during audit. This closes the Grafana blind spot — every Python daemon becomes visible.
- **D-12:** Audit method: `grep -rL "BaseAgent" services/*.py` to find non-inheriting services. Confirm each is a daemon (not a utility script) before migrating.

### FastAPI OTel
- **D-13:** Add `opentelemetry-instrumentation-fastapi` to requirements. One `FastAPIInstrumentor().instrument_app(app)` call in `src/api/main.py`. This auto-instruments every HTTP endpoint with rate, error, and latency metrics — zero custom code.
- **D-14:** Add one custom health gauge: `api_health` = 1 when DB is reachable, 0 when not. Checked in the existing `/health/database` endpoint.

### End-to-End Latency
- **D-15:** Add `bar_e2e_latency_ms` histogram to `intelligence_pipeline_agent`. Measures time from bar arrival to signal written to Kafka. This is the single "is the pipeline slowing down?" metric. Labels: `symbol`, `tf`.
- **D-16:** Existing per-stage histograms (`PLUGIN_DURATION_MS`, `PERSISTENCE_BATCH_LATENCY`, etc.) are already in place. Phase 108 adds the end-to-end wrapper, not per-stage replacements.
- **D-17:** BPS (bars per second) is derived from the existing `bars_processed_total` counter pattern via `rate(bars_processed_total[1m])` in Grafana. No new counter needed — verify the counter exists and is labeled correctly.

### Circuit Breaker Alerting
- **D-18:** CB state OTel gauge (`AGENT_CIRCUIT_BREAKER_STATE`) already exists from FOUND-05 (Phase 106). Phase 108 verifies it has correct `plugin_id` label and is being set on state transitions.
- **D-19:** CB state transition detection in `IntelligencePipelineAgent` bar loop: track `_cb_open_reported` set; when a CB transitions to OPEN, emit structured log `intelligence_pipeline.cb_open` with `plugin_id`, `failure_count`. No Kafka publish — OTel gauge is the signal, Grafana alert fires when gauge > 0.

### DLQ Quarantine
- **D-20:** No re-delivery loop (none exists today; building one is out of scope). Quarantine is DB-level: `DLQDrainAgent` tracks occurrence count per `(agent, source_topic, error_type)` in `dlq_events` table. After ≥ `DLQ_MAX_RETRIES=3` identical errors in 24h, mark subsequent messages `quarantined=true` in `dlq_events`.
- **D-21:** Add `dlq_quarantine_total` OTel counter in `DLQDrainAgent`. Grafana alerts when > 0.
- **D-22:** No new Kafka topic (`dead.final` deferred — requires re-delivery loop to be meaningful).

### Stuck Consumer Detection
- **D-23:** ServiceAuditor already has stall detection (`_fetch_stalled_agents`). Lower `_STALL_THRESHOLD_SECONDS` from 360 to 120 per HEAL-04.
- **D-24:** Add `consumer_stall_detected_total` OTel counter in ServiceAuditor, incremented when a stall is detected before restarting. Labels: `unit`. Grafana can alert on stall rate and show restart frequency.
- **D-25:** Existing restart behavior unchanged — ServiceAuditor still restarts stalled units. Counter adds the OTel visibility layer.

### SOP Documentation
- **D-26:** Update CLAUDE.md with the OTel health contract (D-04 mandatory signals). New agents that don't inherit BaseAgent are a code review rejection. The health contract is the law.
- **D-27:** Document the Grafana alert SLOs: `agent_last_message_timestamp_seconds` stale > 120s → alert; `watchdog_notify_suppressed_total` rate > 0 → alert; `dlq_quarantine_total` > 0 → alert; `api_health` = 0 → alert.

### Deferred
- **D-28:** DB backup deferred — no clear restore scenario identified. Can be added as a standalone quick task when the recovery use case is defined.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### OTel Infrastructure
- `src/observability/otel.py` — OTel provider initialization; OTLP gRPC export to collector
- `src/observability/metrics.py` — all existing OTel instruments; add new ones here
- `production/otel-collector-config.yaml` — collector routing: OTLP in → Prometheus/Tempo/Loki out
- `src/observability/spans.py` — `observed_span()` helper for traces

### BaseAgent & Lifecycle
- `src/core/agent/base.py` — BaseAgent implementation; `_watchdog_notify()` at line ~349; add OTel counters here
- `src/core/agent/base_writer.py` — BaseWriterAgent; `_maybe_route_to_dlq()` DLQ path
- `src/core/schemas/dlq_payload.py` — DLQPayload schema; `retry_count` field exists but always 0

### Services to Migrate / Instrument
- `services/signal_replay_auditor_agent.py` — HYGIENE-07 migration target
- `services/bar_replay_provider.py` — HYGIENE-07 migration target (verify if daemon)
- `src/api/main.py` — FastAPI app; add FastAPIInstrumentor here
- `services/dlq_drain_agent.py` — add quarantine counting logic here

### Systemd
- `production/systemd/` — all 43 unit files; 27 daemons need WatchdogSec=60
- Services already with WatchdogSec: `bar-aggregator`, `bar-auditor`, `bar-writer`, `service-auditor`
- Services to skip: all oneshots (Type=oneshot), `indicagent-dashboard`

### Intelligence Pipeline
- `services/intelligence_pipeline_agent.py` — add `bar_e2e_latency_ms` histogram + CB state transition logging
- `services/service_auditor_agent.py` — lower `_STALL_THRESHOLD_SECONDS` 360→120; add `consumer_stall_detected_total` counter

### Requirements
- `REQUIREMENTS.md` — HEAL-01 through HEAL-04 (self-healing requirements)
- `REQUIREMENTS.md` — HYGIENE-07 (BaseAgent migration, closes here)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseAgent._watchdog_notify()` — already correct sd_notify implementation; just needs two OTel counters added
- `AGENT_CIRCUIT_BREAKER_STATE` gauge — already exists in `metrics.py`; verify `plugin_id` label
- `AGENT_DLQ_TOTAL` counter — already exists; DLQ quarantine adds `dlq_quarantine_total` alongside
- `ServiceAuditor._fetch_stalled_agents()` — existing stall detection; Phase 108 adds OTel counter + lowers threshold
- `opentelemetry-instrumentation-fastapi` — standard library, one-line instrumentation

### Established Patterns
- All OTel instruments defined at module level in `src/observability/metrics.py`, imported by services
- Label key is `agent_id` (not `agent`) — see CLAUDE.md; critical for Grafana dashboard consistency
- `observed_span()` from `spans.py` for traces; `.record()` for histograms; `.add()` for counters/gauges
- `DLQ_MAX_RETRIES` and `STALL_TIMEOUT_SEC` should live in `src/config/settings.py` (not hardcoded)

### Integration Points
- OTel counters added to `BaseAgent._watchdog_notify()` — auto-inherited by all 39 daemon services
- FastAPIInstrumentor wired at `src/api/main.py` app startup
- DLQ quarantine logic in `services/dlq_drain_agent.py` — reads `dlq_events` table, writes `quarantined` field
- `_STALL_THRESHOLD_SECONDS` in `services/service_auditor_agent.py` line 47

### Fleet Snapshot
- 43 total unit files: 27 daemons missing WatchdogSec, 4 already have it, 12 oneshots (skip)
- `indicagent-api` included (uvicorn auto-sd_notify); `indicagent-dashboard` excluded
- Existing histograms cover per-stage latency; `bar_e2e_latency_ms` is the missing end-to-end wrapper

</code_context>

<specifics>
## Specific Ideas

- **One-person shop constraint**: Every design decision favors automation over manual tasks. No manual health checks, no manual restart procedures. systemd + Grafana alerts handle everything.
- **"What would Renaissance demand?"**: Complete fleet visibility in one Grafana dashboard. Every service speaks OTel. P95 latency alerts fire before humans notice slowdowns. DLQ quarantine prevents infinite retry loops from hiding behind silence.
- **Grafana SLO alerts to implement** (document in phase plans):
  - `agent_last_message_timestamp_seconds` stale > 120s per service → page
  - `watchdog_notify_suppressed_total` rate > 0 → warning (service alive but not processing)
  - `dlq_quarantine_total` increment → warning (poison pill detected)
  - `api_health` = 0 → page (DB unreachable)
  - `rate(bars_processed_total[5m])` drops > 50% from baseline → warning (BPS degradation)

</specifics>

<deferred>
## Deferred Ideas

- **DB backup** — nightly pg_dump to `/var/backups/indicagent/`. Deferred: no clear restore scenario defined. Add as quick task when recovery use case is identified.
- **DLQ dead.final Kafka topic** — quarantine via separate Kafka topic requires a re-delivery loop that does not exist today. Deferred to a future phase that also builds the retry mechanism.
- **Next.js dashboard OTel** — full OTel instrumentation of the dashboard. Deferred: dashboard is not in the data path; HTTP health probe is sufficient for a one-person shop.
- **Distributed tracing across services** — using Tempo to trace a bar from ibkr-provider through intelligence-pipeline to feature-writer. The Tempo infrastructure is in place; the per-span instrumentation is a future phase.

</deferred>

---

*Phase: 108-Self-Healing-Hardening*
*Context gathered: 2026-05-28*
