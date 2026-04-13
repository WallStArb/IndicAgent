# Phase 67: Observability, Alerting & Automation — Context

**Gathered:** 2026-04-13
**Status:** Ready for execution — Renaissance refactored
**Source:** Renaissance-compliant design (docs/plans/2026-04-12-observability-automation-design.md)

**Renaissance improvements added:**
- Component 0: BaseAgent observability + alert publishing (4 metrics + `_send_alert()`) — all agents
- Component 1: AlertingAgent (separation of concerns) — new service
- Component 2a: Bootstrap retry in BaseAgent (reusable pattern)
- Component 3b: Roll automation with verification (earn the right)

**Jim Simons would approve:**
- ✅ Single Responsibility: AlertingAgent ONLY dispatches alerts
- ✅ Modularity: Bootstrap retry + alert publishing in BaseAgent, reusable by ALL agents
- ✅ Reuse: Crash/setup metrics + alert capability in ALL agents automatically
- ✅ Instrument Everything: Alerting system has 4 internal metrics
- ✅ Earn the Right: Roll automation verified before trusted
- ✅ Efficiency: Metrics cached at init, minimal runtime overhead
- ✅ Simplicity: Single pattern, no code duplication across agents
- ✅ Separation of Concerns: BaseAgent provides alert INTERFACE, AlertingAgent provides alert DISPATCH

<domain>
## Phase Boundary

Close the observability, alerting, and automation gaps that let operational failures go undetected. Every undetected downtime window is a poisoned training sample. This phase fixes that.

**In scope:**
- Component 0: BaseAgent observability + alert publishing (4 metrics: crash, setup success/failure, setup latency + `_send_alert()` method) — all agents
- Component 0: Bootstrap retry in BaseAgent (reusable via `_setup_with_retry()`)
- Component 1: Grafana alert rules (CRITICAL → Telegram, HIGH/MEDIUM → Discord) via provisioned YAML
- Component 1: AlertingAgent (NEW service, separates alert dispatch from audit)
- Component 2: `market_data_gaps` table + `bar_auditor_agent` write path (gap tracking for ML exclusion)
- Component 3: Roll automation with verification: `service_auditor_agent` consumes `topic_roll_events`, auto-restarts `ibkr-provider`, verifies post-restart health
- Component 4: Code fixes: signal_tracker bootstrap retry (uses BaseAgent pattern), SwarmOrchestrator cache seeding
- Component 5: Three Grafana dashboards rebuilt (operations.json new, pipeline-health.json + signals-i8.json rebuilt) with current service names and live queries

**NEW in Renaissance refactor:**
- ✅ **NEW agent service:** AlertingAgent (services/alerting_agent.py, systemd unit, port :9132)
- ✅ **NEW Kafka topic:** topic_alert_requests()
- ✅ **NEW BaseAgent features:** 4 crash/setup metrics, `_setup_with_retry()` method, `_send_alert()` method
- ✅ **NEW internal observability:** AlertingAgent metrics (dispatch_total, latency_seconds)
- ✅ **NEW verification:** Roll automation with pre/post lag comparison
- ✅ **NEW Renaissance-class architecture:** BaseAgent provides alert INTERFACE, AlertingAgent provides alert DISPATCH

**Not in scope:** AlertManager, I1-I7 plugin logic changes, historical gap backfill.

**One new Docker container (AlertingAgent). One new systemd unit.**

</domain>

<decisions>
## Implementation Decisions

### Component 0: BaseAgent Observability + Alert Publishing Foundation (NEW)

**Files:** `src/core/agent/base.py`, `src/observability/metrics.py`
**Test first:** `tests/unit/test_base_agent.py` (extend existing file)

- Add 4 new Prometheus metrics to ALL agents automatically:
  - `agent_crash_total` — Counter, labels: `{agent}`
  - `agent_setup_success_total` — Counter, labels: `{agent}`
  - `agent_setup_failure_total` — Counter, labels: `{agent}`, `{error_type}`
  - `agent_setup_latency_seconds` — Histogram, labels: `{agent}`, buckets: [0.1, 0.5, 1.0, 2.5, 5.0, 10.0]

- Add `_setup_with_retry()` method to BaseAgent:
  - 3 attempts with exponential backoff (2s, 4s, 8s)
  - Subclasses opt-in by calling `await self._setup_with_retry()` instead of `await self._setup()`
  - Reusable pattern: ANY agent with DB dependencies can use this

- Add `_send_alert()` method to BaseAgent (NEW — Renaissance-class):
  - Publishes alerts to `topic_alert_requests()` Kafka topic
  - Args: `severity` ("CRITICAL" | "HIGH" | "MEDIUM"), `message`, `context` (optional dict)
  - No-op if agent has no Kafka producer (graceful degradation)
  - AlertingAgent consumes and dispatches: CRITICAL → Telegram, HIGH/MEDIUM → Discord
  - ALL agents inherit this capability automatically

- Wrap `BaseAgent.start()` to track setup latency + success/failure:
  - Start timer before `_setup()`
  - On success: observe latency, increment success_total
  - On failure: increment failure_total with error_type label

- Wrap `BaseAgent.start()` to track crashes in `_run()`:
  - On exception: increment crash_total, then re-raise

**Benefits:**
- **Reuse:** EVERY agent gets crash/setup observability + alert capability automatically
- **Modularity:** Bootstrap retry + alert publishing in BaseAgent, reusable by ALL agents
- **Efficiency:** Metrics cached at init, minimal runtime overhead
- **Simplicity:** Single pattern, no code duplication
- **Decoupling:** Agents publish alerts to Kafka, don't know about Telegram/Discord

### Component 1: Grafana Alerting

- Two contact points: `telegram-critical` (Telegram bot DM, CRITICAL only) and `discord-ops` (Discord webhook, HIGH + MEDIUM)
- Provisioning path: `production/grafana/provisioning/alerting/contact-points.yml` (gitignored, real creds) + `contact-points.example.yml` (committed, placeholder values)
- Alert rules in `production/grafana/provisioning/alerting/alert-rules.yml` (committed)
- CRITICAL rules: provider_dead (rate==0 during market hours), service_crash_looping (>3 in 10m window, uses `agent_crash_total`), signals_dropped (increase>0), signal_dlq_growing (increase>0), data_completeness_critical (<90%)
- HIGH rules: consumer_lag_writer (>1000 msgs), bar_flow_stale (>300s since last bar), output_buffer_pressure (>400 depth), gap_fill_dlq_growing (>0)
- MEDIUM rules: data_completeness_soft (<95%)
- `contact-points.yml` added to `.gitignore`

### Component 1b: AlertingAgent (NEW — Separation of Concerns)

**Files:** `services/alerting_agent.py` (NEW), `/etc/systemd/system/indicagent-alerting-agent.service` (NEW)
**Test first:** `tests/unit/service_tests/test_alerting_agent.py` (new file)

- **NEW service:** AlertingAgent — centralized alert dispatcher
- **NEW systemd unit:** indicagent-alerting-agent.service, port :9132
- **NEW Kafka topic:** `topic_alert_requests()` → `{env}.alert.requests`
- **NEW Prometheus metrics** (internal observability):
  - `alerting_dispatch_total` — Counter, labels: `{channel, severity, status}`
  - `alert_latency_seconds` — Histogram, labels: `{channel}`, buckets: [0.1, 0.5, 1.0, 2.5, 5.0, 10.0]

- AlertingAgent responsibilities:
  - Consume from `topic_alert_requests`
  - Dispatch CRITICAL → Telegram (via `_dispatch_telegram()`)
  - Dispatch HIGH/MEDIUM → Discord (via `_dispatch_discord()`)
  - Track dispatch success/failure + latency

- service_auditor_agent changes (refactored):
  - **REMOVE:** `_notify_telegram()`, `_notify_discord()`, `_dispatch_webhook()` methods (Plan 1)
  - **USE:** `await self._send_alert()` from BaseAgent instead
  - Update `_handle_escalation()` to call `await self._send_alert("CRITICAL", title, body)`
  - Update `_handle_roll_event()` to call `await self._send_alert("HIGH", title, body)`

**Benefits:**
- **Single responsibility:** AlertingAgent ONLY dispatches alerts
- **Reuse:** ANY agent can send alerts via `BaseAgent._send_alert()`
- **Observability:** 4 internal metrics track alerting system health
- **Modularity:** Decoupled from service_auditor_agent
- **Separation of Concerns:** BaseAgent provides alert INTERFACE, AlertingAgent provides alert DISPATCH

### Component 2: Data Completeness (`market_data_gaps` table)

- Migration: `production/migrations/062_market_data_gaps.sql`
- Schema: `id BIGSERIAL PK`, `symbol TEXT NOT NULL`, `tf TEXT NOT NULL`, `gap_start_ts TIMESTAMPTZ NOT NULL`, `gap_end_ts TIMESTAMPTZ` (NULL while ongoing), `bars_expected INT NOT NULL`, `bars_missing INT NOT NULL`, `detected_at TIMESTAMPTZ DEFAULT NOW()`, `resolved_at TIMESTAMPTZ`, UNIQUE(symbol, tf, gap_start_ts)
- `bar_auditor_agent` write path: on audit cycle, if completeness_pct < 100% → UPSERT to market_data_gaps; if completeness_pct == 100% and open gap exists → set resolved_at + gap_end_ts = NOW()
- Consumer offset fix: change `auto_offset_reset="latest"` → `"earliest"` on gap requests consumer; add `_seen_gap_requests: set[tuple[str, str, datetime]]` dedup cleared every 24h
- Gap fill DLQ: when `_gap_requests_loop()` fails after 3 retries → publish to `topic_gap_fill_dlq()`, payload `{symbol, tf, start_ts, end_ts, retry_count, error}`
- New Prometheus counter: `bar_auditor_gap_fill_dlq_depth` in `src/observability/metrics.py`
- New stream key: `topic_gap_fill_dlq()` in `src/core/stream_keys.py` → `{env}.gap_fill.dlq`
- New consumer group: `bar_auditor_gap_fill_consumer`

### Component 3: Roll Automation (with Verification)

- `service_auditor_agent` gains second Kafka consumer for `topic_roll_events` (concurrent asyncio task, same process)
- **NEW:** Pre-restart: Snapshot current provider lag via `_get_provider_lag()`
- On `RollEvent` with `event_type = "roll_complete"`: log, publish HIGH alert via `_publish_alert_event()`, run `subprocess.run(["sudo", "systemctl", "restart", "indicagent-ibkr-provider"], check=True)`
- **NEW:** Post-restart: Wait 30s for warmup, then verify lag decreased
- **NEW:** Verification: If lag did NOT decrease, escalate to CRITICAL alert
- Dedup guard: `_handled_rolls: set[tuple[str, str]]` keyed by `(symbol, new_expiry)` — prevents double restart on at-least-once delivery
- Gate: only fires on `roll_complete`, not `roll_imminent` or `roll_detected`
- Sudoers entry: `bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider`
- New consumer group: `service_auditor_roll_consumer`
- Methods: `_handle_roll_event()`, `_restart_ibkr_provider()`, `_get_provider_lag()` — private snake_case

**Renaissance improvement:** Verification loop ensures automation earns the right to run autonomously.

### Component 4: Code Fixes

**4a. `signal_tracker_compute_agent` bootstrap retry (SIMPLIFIED):**
- **OLD:** Agent-specific retry logic
- **NEW:** Use `BaseAgent._setup_with_retry()` (reusable pattern)
- Success: `len(active_signals) > 0` OR COUNT query returns 0 (provably empty ledger)
- Failure condition: 0 signals loaded when ledger has rows → retry
- `sd_notify(READY=1)` moved to after successful bootstrap
- On `bootstrap_failed`: publish health event to `topic_alert_requests` (NOT topic_system_health_events) with `event_type = "bootstrap_failed"` (currently only logs — publish is in scope)

**4b. `SwarmOrchestratorComputeAgent` context cache seeding:**
- In `_setup()`, before consume loop: query last 200 rows per (symbol, tf) from `intelligence_features`
- Load into `SwarmContextCache` — one startup DB read, amortized cost negligible
- Note: Phase 56 (SwarmOrchestratorComputeAgent) shipped 2026-04-11 — this fix is ready to apply

### Component 5: Dashboard Rebuild

- `production/grafana/dashboards/operations.json` — new file replacing `service-overview.json`
- `production/grafana/dashboards/pipeline-health.json` — rebuilt in place
- `production/grafana/dashboards/signals-i8.json` — rebuilt in place
- All dashboards follow Golden Signals layout (Traffic, Latency, Errors, Saturation rows)
- All panel queries use current service names from active service map (no archived names)
- `operations.json` rows: Service Health (agent_crash_total), Traffic, Errors, Saturation, Data Quality (market_data_gaps)
- `pipeline-health.json` rows: Latency (p95 per tier, agent_setup_latency_seconds), Throughput (bars/min, signals), Health (plugin skips, checkpoint failures)
- `signals-i8.json` rows: Signal Funnel, Routing, AI Narrative

### Wave / Execution Order (UPDATED)

- **Plan 1 (BaseAgent foundation):** 4 crash/setup metrics + `_send_alert()` + `_setup_with_retry()` + Settings + stream keys + migration — ALL agents benefit
- **Plan 2 (AlertingAgent):** NEW service + systemd unit — separation of concerns
- **Plan 3 (code fixes):** signal_tracker bootstrap retry (uses BaseAgent pattern) + SwarmOrchestrator cache seeding
- **Plan 4 (alerting + roll automation):** Grafana alert rules YAML + contact-points files + roll consumer in service_auditor_agent (with verification) + bar_auditor DLQ path — depends on Plans 1-2
- **Plan 5 (dashboards):** 3 JSON dashboard files — depends on Plans 1-4 (new metrics/services referenced in panels)

**Parallelization:** Plans 1-3 can execute in parallel. Plans 4-5 depend on Plans 1-2.

### Claude's Discretion

- Exact Grafana panel JSON syntax (PromQL expressions, panel IDs, datasource UIDs) — implement using Grafana 10+ provisioning format
- TDD test coverage approach for webhook dispatcher (unit tests with mocked aiohttp, Settings)
- Whether Plan 4b (SwarmOrchestrator) becomes a stub/comment in the plan since Phase 56 isn't shipped yet — document as "applies when Phase 56 is executed"

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Doc (source of truth)
- `docs/plans/2026-04-12-observability-automation-design.md` — Full component specs, naming convention audit, success criteria

### Core Infrastructure
- `src/config/settings.py` — Settings class (add telegram/discord fields here)
- `src/observability/metrics.py` — All Prometheus metric registration (add new counters here, prevent duplicate registration)
- `src/core/stream_keys.py` — All Kafka topic key functions (add `topic_gap_fill_dlq()` here)
- `production/migrations/` — DB migration files (next: `062_market_data_gaps.sql`)

### Services to Modify
- `services/service_auditor_agent.py` — Add webhook dispatcher, roll consumer, crash counter
- `services/bar_auditor_agent.py` — Add market_data_gaps write path, DLQ consumer offset fix
- `services/signal_tracker_compute_agent.py` — Bootstrap retry + sd_notify gate

### Grafana Infrastructure
- `production/grafana/provisioning/` — Grafana provisioning directory (alerting/ subdir is new)
- `production/grafana/dashboards/` — Dashboard JSON files

### Naming Conventions
- `CLAUDE.md` — Cross-layer naming rules (stream keys, tables, agents, Prometheus metrics)

</canonical_refs>

<specifics>
## Specific Requirements

### Success Criteria (from design doc — UPDATED)

**Functional:**
1. A service crash-looping triggers a Telegram message within 60 seconds
2. Provider downtime > 5 min triggers a Telegram message
3. Every gap window is recorded in `market_data_gaps` with correct `bars_expected` / `bars_missing`
4. Futures roll triggers automatic `ibkr-provider` restart with verification
5. `signal-tracker-compute` starts with valid state even when DB responds slowly
6. `swarm_orchestrator` processes first bar with seeded context, not empty cache
7. All three Grafana dashboards load with current service names and live data
8. No Prometheus queries reference archived service names

**Observability (NEW — Instrument Everything):**
9. ALL agents have crash metrics (`agent_crash_total`)
10. ALL agents have setup metrics (`success_total`, `failure_total`, `latency_seconds`)
11. ALL agents have alert publishing capability via `BaseAgent._send_alert()`
12. Bootstrap retry available to ALL agents via `BaseAgent._setup_with_retry()`
13. AlertingAgent has internal metrics (`alerting_dispatch_total`, `alert_latency_seconds`)
14. Roll automation verification (pre/post lag comparison, CRITICAL escalation on failure)

**Renaissance Principles Compliance:**
- ✅ **Simplicity:** Single pattern for bootstrap retry + alert publishing (BaseAgent)
- ✅ **Modularity:** AlertingAgent separates dispatch from audit; BaseAgent provides alert interface
- ✅ **Reuse:** Crash/setup metrics + alert capability in ALL agents automatically
- ✅ **Instrument Everything:** Alerting system has internal metrics
- ✅ **Earn the Right:** Roll automation verified before trusted
- ✅ **Separation of Concerns:** BaseAgent (interface) vs AlertingAgent (dispatch)

### Prometheus Metric Naming (must follow `<agent>_<metric>` prefix convention)

**BaseAgent metrics (all agents):**
- `agent_crash_total` — counter, labels: `{agent}`
- `agent_setup_success_total` — counter, labels: `{agent}`
- `agent_setup_failure_total` — counter, labels: `{agent}`, `{error_type}`
- `agent_setup_latency_seconds` — histogram, labels: `{agent}`

**AlertingAgent metrics:**
- `alerting_dispatch_total` — counter, labels: `{channel, severity, status}`
- `alerting_latency_seconds` — histogram, labels: `{channel}`

**Data quality metrics:**
- `bar_auditor_gap_fill_dlq_depth` — counter (existing `bar_auditor_*` prefix)

### Sudoers Requirement
The `bg` user needs passwordless `systemctl restart indicagent-ibkr-provider` for roll automation. This is a one-line sudoers entry — document in plan but DO NOT automate the sudoers edit (requires manual one-time setup).

</specifics>

<deferred>
## Deferred Items

- `market_data_gaps` backfill for historical outages (separate script, future work)
- AlertManager (Grafana native alerting is sufficient)
- I1-I7 plugin logic changes
- Historical gap backfill

## What Changed in Renaissance Refactor

**Added:**
- ✅ Component 0: BaseAgent observability (4 metrics, bootstrap retry, `_send_alert()` method)
- ✅ Component 1b: AlertingAgent (new service, separation of concerns)
- ✅ Component 3b: Roll automation verification (earn the right)
- ✅ Internal observability metrics for alerting system
- ✅ Renaissance-class architecture: BaseAgent (alert INTERFACE) → AlertingAgent (alert DISPATCH)

**Removed (violated Renaissance principles):**
- ❌ Webhook dispatcher in service_auditor_agent (separation of concerns violation)
- ❌ Agent-specific bootstrap retry (modularity violation)
- ❌ Direct webhook calls from agents (coupling violation)

**Renumbered:**
- Component 1 → Component 0 (BaseAgent foundation first)
- Component 2 → Component 1 (Grafana)
- Component 3 → Component 2 (Data completeness)
- Component 4 → Component 3 (Roll automation)
- Component 5 → Component 4 (Code fixes)
- Component 6 → Component 5 (Dashboards)

</deferred>

---

*Phase: 067-observability-alerting-automation*
*Context gathered: 2026-04-12 via PRD Express Path*
