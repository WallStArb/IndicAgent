# Phase 67: Observability, Alerting & Automation — Context

**Gathered:** 2026-04-13, updated 2026-04-23
**Status:** Nearly complete — 3 small items remaining (suitable for /gsd-fast)
**Source:** Renaissance-compliant design (docs/plans/2026-04-12-observability-automation-design.md)

<domain>
## Phase Boundary

Close the observability, alerting, and automation gaps that let operational failures go undetected. Every undetected downtime window is a poisoned training sample. This phase fixes that.

**Already implemented (via Phase 68 or earlier):**
- BaseAgent crash/setup metrics (4 Prometheus counters: crash_total, setup_success/failure_total, setup_latency_seconds)
- BaseAgent._send_alert() — Kafka-based alert publishing for all agents
- BaseAgent._setup_with_retry() — exponential backoff bootstrap resilience
- stream_keys: topic_alert_requests(), topic_gap_fill_dlq()
- metrics.py: all observability counters registered
- bar_auditor_agent: market_data_gaps write path, DLQ topic, gap-fill retry
- migration 062_market_data_gaps.sql
- SwarmOrchestrator cache seeding (200 rows/tf from intelligence_features)
- signal_tracker_compute bootstrap retry (own implementation)
- Grafana alert-rules.yml (13KB, 10+ rules)
- contact-points.example.yml
- All 3 dashboards: operations.json, pipeline-health.json, signals-i8.json
- service_auditor_agent: roll event consumer with auto-restart

**Remaining work (3 items, ~150 lines new code + refactor):**
1. AlertingAgent — new service (services/alerting_agent.py) + systemd unit
2. Renaissance refactor — remove inline webhooks from service_auditor_agent, replace with _send_alert()
3. contact-points.yml — real credentials (operational, not code)

**Not in scope:** AlertManager, I1-I7 plugin logic changes, historical gap backfill, website→Grafana proxy.

</domain>

<decisions>
## Implementation Decisions

### AlertingAgent Design (Minimal Dispatcher)

- **Renaissance principle:** Start minimal. Add complexity only when evidence proves it's needed.
- **Scope:** Kafka consumer → route by severity → HTTP POST. No rate limiting, no dedup, no retry, no database.
- **Why no dedup:** We haven't measured duplicate alert volume. Build it when data shows we need it.
- **Why no rate limiting:** No evidence of cascading alert storms. Measure first.
- **Architecture:** BaseAgent subclass. Consumes `topic_alert_requests()`. Dispatches CRITICAL → Telegram, HIGH/MEDIUM → Discord.
- **Internal metrics (mandatory — Instrument Everything):**
  - `alerting_dispatch_total` — Counter, labels: `{channel, severity, status}`
  - `alerting_latency_seconds` — Histogram, labels: `{channel}`
- **Systemd unit:** `indicagent-alerting-agent.service`, port :9132
- **File:** `services/alerting_agent.py` (~150 lines)
- **Test:** `tests/unit/service_tests/test_alerting_agent.py` — mock aiohttp, verify routing by severity

### Renaissance Refactor (Full Migration)

- **Decision:** Full migration. No hybrid. Remove ALL inline webhook methods from service_auditor_agent.
- **Why full:** Two dispatch paths = two failure modes, two places to update, zero benefit. service_auditor AUDITS. AlertingAgent DISPATCHES. SRP violation if both dispatch.
- **What changes in service_auditor_agent.py:**
  - REMOVE: `_dispatch_webhook()`, `_notify_telegram()`, `_notify_discord()`, `_dispatch_webhook_http()` methods
  - REPLACE: All 11 call sites → `await self._send_alert(severity, message, context)`
  - Keep: roll event consumer, graduated response policy, systemd integration
- **Compute cost:** Eliminates duplicate dispatch. One Kafka hop → one HTTP call per alert. Cleaner DAG.

### Contact Points (Operational)

- Real `contact-points.yml` with actual Telegram bot token + Discord webhook URL
- File is gitignored (credentials never committed)
- `contact-points.example.yml` already exists with placeholder values
- One-time setup: add bot token + webhook URL, reload Grafana provisioning

### Execution Approach

- **Method:** `/gsd-fast` — inline execution, no subagents, no planning overhead
- **Rationale:** ~150 lines new code + find-and-replace refactor. Planning overhead exceeds the work.
- **Commits:** 2-3 atomic commits (AlertingAgent new, refactor service_auditor, contact-points)

### Claude's Discretion

- Exact aiohttp session management details
- Test mocking strategy for webhook dispatch
- Whether to also migrate signal_tracker from own bootstrap retry to BaseAgent._setup_with_retry() (minor, optional)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Doc (source of truth)
- `docs/plans/2026-04-12-observability-automation-design.md` — Full component specs, naming conventions, success criteria

### Core Infrastructure
- `src/config/settings.py` — Settings class (telegram/discord fields already added)
- `src/observability/metrics.py` — All Prometheus metric registration
- `src/core/stream_keys.py` — topic_alert_requests(), topic_gap_fill_dlq() already exist
- `src/core/agent/base.py` — BaseAgent with _send_alert(), _setup_with_retry(), crash/setup metrics

### Services to Modify
- `services/service_auditor_agent.py` — Remove inline webhooks (11 refs), replace with _send_alert()

### Services to Create
- `services/alerting_agent.py` — NEW minimal dispatcher

### Grafana Infrastructure
- `production/grafana/provisioning/alerting/` — alert-rules.yml + contact-points.example.yml exist
- `production/grafana/dashboards/` — All 3 dashboards exist

### Naming Conventions
- `CLAUDE.md` — Cross-layer naming rules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseAgent._send_alert()`: Already implemented in base.py — any agent can publish alerts via Kafka
- `BaseAgent._setup_with_retry()`: Already implemented — exponential backoff for bootstrap
- `topic_alert_requests()` in stream_keys.py: Topic already defined
- `metrics.py`: All counters registered (alerting_dispatch_total, alerting_latency_seconds defined)

### Established Patterns
- BaseAgent pattern: _setup/_teardown/_run lifecycle, metrics_port, signal handlers
- Service file pattern: `services/<name>.py` with `if __name__ == "__main__"` entry point
- Systemd unit pattern: `indicagent-<name>.service` with standard env vars

### Integration Points
- `services/alerting_agent.py` consumes from `topic_alert_requests()` Kafka topic
- `services/service_auditor_agent.py` currently has inline webhooks → refactor to use _send_alert()
- Grafana provisioning reads `contact-points.yml` on reload

</code_context>

<deferred>
## Deferred Ideas

- **Website→Grafana proxy:** Access Grafana dashboards from the Next.js dashboard. Separate concern (frontend routing/auth/proxying) — belongs in its own phase or dashboard feature backlog.
- `market_data_gaps` backfill for historical outages (separate script, future work)
- AlertManager (Grafana native alerting is sufficient)
- Rate limiting / dedup for alerts (build when evidence proves it's needed)
- Migrate signal_tracker from own bootstrap retry to BaseAgent._setup_with_retry() (minor, optional)

</deferred>

---

*Phase: 067-observability-alerting-automation*
*Context gathered: 2026-04-13, updated 2026-04-23*
