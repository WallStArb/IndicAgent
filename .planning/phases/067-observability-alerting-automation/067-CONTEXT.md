# Phase 67: Observability, Alerting & Automation — Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-12-observability-automation-design.md)

<domain>
## Phase Boundary

Close the observability, alerting, and automation gaps that let operational failures go undetected. Every undetected downtime window is a poisoned training sample. This phase fixes that.

**In scope:**
- Grafana alert rules (CRITICAL → Telegram, HIGH/MEDIUM → Discord) via provisioned YAML
- `market_data_gaps` table + `bar_auditor_agent` write path (gap tracking for ML exclusion)
- Roll automation: `service_auditor_agent` consumes `topic_roll_events`, auto-restarts `ibkr-provider`
- Four code fixes: signal_tracker bootstrap retry, SwarmOrchestrator cache seeding, service_auditor webhook dispatcher, crash counter Prometheus metric
- Three Grafana dashboards rebuilt (operations.json new, pipeline-health.json + signals-i8.json rebuilt) with current service names and live queries

**Not in scope:** New agent services, AlertManager, I1-I7 plugin logic changes, new Kafka topics beyond `topic_gap_fill_dlq()`, historical gap backfill.

**Zero new Docker containers. Zero new systemd units.**

</domain>

<decisions>
## Implementation Decisions

### Component 1: Grafana Alerting

- Two contact points: `telegram-critical` (Telegram bot DM, CRITICAL only) and `discord-ops` (Discord webhook, HIGH + MEDIUM)
- Provisioning path: `production/grafana/provisioning/alerting/contact-points.yml` (gitignored, real creds) + `contact-points.example.yml` (committed, placeholder values)
- Alert rules in `production/grafana/provisioning/alerting/alert-rules.yml` (committed)
- CRITICAL rules: provider_dead (rate==0 during market hours), service_crash_looping (>3 in 10m window, uses new `service_auditor_service_restarts_total` counter), signals_dropped (increase>0), signal_dlq_growing (increase>0), data_completeness_critical (<90%)
- HIGH rules: consumer_lag_writer (>1000 msgs), bar_flow_stale (>300s since last bar), output_buffer_pressure (>400 depth), gap_fill_dlq_growing (>0)
- MEDIUM rules: data_completeness_soft (<95%)
- `contact-points.yml` added to `.gitignore`

### Component 2: Data Completeness (`market_data_gaps` table)

- Migration: `production/migrations/062_market_data_gaps.sql`
- Schema: `id BIGSERIAL PK`, `symbol TEXT NOT NULL`, `tf TEXT NOT NULL`, `gap_start_ts TIMESTAMPTZ NOT NULL`, `gap_end_ts TIMESTAMPTZ` (NULL while ongoing), `bars_expected INT NOT NULL`, `bars_missing INT NOT NULL`, `detected_at TIMESTAMPTZ DEFAULT NOW()`, `resolved_at TIMESTAMPTZ`, UNIQUE(symbol, tf, gap_start_ts)
- `bar_auditor_agent` write path: on audit cycle, if completeness_pct < 100% → UPSERT to market_data_gaps; if completeness_pct == 100% and open gap exists → set resolved_at + gap_end_ts = NOW()
- Consumer offset fix: change `auto_offset_reset="latest"` → `"earliest"` on gap requests consumer; add `_seen_gap_requests: set[tuple[str, str, datetime]]` dedup cleared every 24h
- Gap fill DLQ: when `_gap_requests_loop()` fails after 3 retries → publish to `topic_gap_fill_dlq()`, payload `{symbol, tf, start_ts, end_ts, retry_count, error}`
- New Prometheus counter: `bar_auditor_gap_fill_dlq_depth` in `src/observability/metrics.py`
- New stream key: `topic_gap_fill_dlq()` in `src/core/stream_keys.py` → `{env}.gap_fill.dlq`
- New consumer group: `bar_auditor_gap_fill_consumer`

### Component 3: Roll Automation

- `service_auditor_agent` gains second Kafka consumer for `topic_roll_events` (concurrent asyncio task, same process — no new service)
- On `RollEvent` with `event_type = "roll_complete"`: log, dispatch HIGH alert, run `subprocess.run(["sudo", "systemctl", "restart", "indicagent-ibkr-provider"], check=True)`
- Dedup guard: `_handled_rolls: set[tuple[str, str]]` keyed by `(symbol, new_expiry)` — prevents double restart on at-least-once delivery
- Gate: only fires on `roll_complete`, not `roll_imminent` or `roll_detected`
- Sudoers entry: `bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider`
- New consumer group: `service_auditor_roll_consumer`
- New method: `_handle_roll_event()`, `_restart_ibkr_provider()` — private snake_case

### Component 4: Code Fixes

**4a. `signal_tracker_compute_agent` bootstrap retry:**
- Wrap `_bootstrap_active_signals()` in retry loop: 3 attempts, 2s/4s/8s exponential backoff
- Success: `len(active_signals) > 0` OR COUNT query returns 0 (provably empty ledger)
- Failure condition: 0 signals loaded when ledger has rows → retry
- `sd_notify(READY=1)` moved to after successful bootstrap
- On `bootstrap_failed`: publish health event to `topic_health_events()` with `event_type = "bootstrap_failed"` (currently only logs — publish is in scope). Use `topic_health_events` from `stream_keys.py` — `topic_system_health_events` does not exist.

**4b. `SwarmOrchestratorComputeAgent` context cache seeding:**
- In `_setup()`, before consume loop: query last 200 rows per (symbol, tf) from `intelligence_features`
- Load into `SwarmContextCache` — one startup DB read, amortized cost negligible
- Note: Phase 56 (SwarmOrchestratorComputeAgent) is not yet implemented. This fix applies when Phase 56 is executed.

**4c. `service_auditor_agent` webhook dispatcher:**
- New Settings fields: `telegram_bot_token: str = ""`, `telegram_chat_id: str = ""`, `discord_webhook_url: str = ""`
- New methods: `_notify_telegram()`, `_notify_discord()`, `_dispatch_webhook()` — private async, follow existing agent patterns
- Empty string = channel disabled (no-op in dispatcher)
- Called from: `_handle_escalation()` (existing, CRITICAL), `_handle_roll_event()` (new, HIGH), bootstrap failure events (HIGH)
- New counter: `service_auditor_service_restarts_total` in `src/observability/metrics.py`

### Component 5: Dashboard Rebuild

- `production/grafana/dashboards/operations.json` — new file replacing `service-overview.json`
- `production/grafana/dashboards/pipeline-health.json` — rebuilt in place
- `production/grafana/dashboards/signals-i8.json` — rebuilt in place
- All dashboards follow Golden Signals layout (Traffic, Latency, Errors, Saturation rows)
- All panel queries use current service names from active service map (no archived names)
- `operations.json` rows: Service Health, Traffic, Errors, Saturation, Data Quality (market_data_gaps)
- `pipeline-health.json` rows: Latency (p95 per tier), Throughput (bars/min, signals), Health (plugin skips, checkpoint failures)
- `signals-i8.json` rows: Signal Funnel, Routing, AI Narrative

### Wave / Execution Order

- **Plan 1 (foundation):** Settings fields + webhook dispatcher + `service_auditor_service_restarts_total` counter + `market_data_gaps` migration + `topic_gap_fill_dlq()` stream key — these are dependencies for everything else
- **Plan 2 (code fixes):** bootstrap retry (4a) + SwarmOrchestrator cache seeding note (4b) — independent of Plan 1
- **Plan 3 (alerting + roll automation):** Grafana alert rules YAML + contact-points files + roll consumer in service_auditor_agent + bar_auditor DLQ path — depends on Plan 1
- **Plan 4 (dashboards):** 3 JSON dashboard files — depends on Plan 1 (new metrics/tables referenced in panels)

Plans 1 and 2 can execute in parallel. Plans 3 and 4 both depend on Plan 1.

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

### Success Criteria (from design doc)
1. A service crash-looping triggers a Telegram message within 60 seconds
2. Provider downtime > 5 min triggers a Telegram message
3. Every gap window is recorded in `market_data_gaps` with correct `bars_expected` / `bars_missing`
4. Futures roll triggers automatic `ibkr-provider` restart without human intervention
5. `signal-tracker-compute` starts with valid state even when DB responds slowly
6. `swarm_orchestrator` processes first bar with seeded context, not empty cache
7. All three Grafana dashboards load with current service names and live data
8. No Prometheus queries reference archived service names

### Prometheus Metric Naming (must follow `<agent>_<metric>` prefix convention)
- `service_auditor_service_restarts_total` — counter, labels: `{service_name}`
- `bar_auditor_gap_fill_dlq_depth` — counter (existing `bar_auditor_*` prefix)
- `gap_fill_dlq_depth` — used in Grafana alert expression (check if same as above)

### Sudoers Requirement
The `bg` user needs passwordless `systemctl restart indicagent-ibkr-provider` for roll automation. This is a one-line sudoers entry — document in plan but DO NOT automate the sudoers edit (requires manual one-time setup).

</specifics>

<deferred>
## Deferred Items

- `market_data_gaps` backfill for historical outages (separate script, future work)
- AlertManager (Grafana native alerting is sufficient)
- I1-I7 plugin logic changes
- New Kafka topics beyond `topic_gap_fill_dlq()`
- ~~Phase 4b (`SwarmOrchestratorComputeAgent` cache seeding) is deferred until Phase 56 ships~~ **CLEARED 2026-04-12** — `services/swarm_orchestrator_agent.py` confirmed on disk; Phase 56 shipped

</deferred>

---

*Phase: 067-observability-alerting-automation*
*Context gathered: 2026-04-12 via PRD Express Path*
