# Observability, Alerting & Automation Design

**Date:** 2026-04-12  
**Status:** Approved — pending implementation plan  
**Scope:** Single phase covering CRITICAL + HIGH gaps identified in post-cleanup audit  
**Renaissance principle:** Instrument everything. Let the system run. No manual tasks.

---

## Problem Statement

The system produces data it cannot trust, and when it breaks nobody knows. Three incidents from the live system illustrate the gap:

1. `bar-replay` crash-looped 1,346 times — discovered manually hours later
2. `ibkr-provider` watchdog-killed 195 times (hours of missed bars) — no alert fired
3. `signal-tracker-compute` + `lifecycle-writer` installed but never enabled — silently doing nothing

Every undetected downtime window is a training sample that looks like "no signal" but actually means "no data." That poisons models downstream.

---

## Architecture: Right Tool for Each Job

Two failure modes require different alerting paths:

```
Prometheus metrics ──→ Grafana alert rules ──→ Telegram (CRITICAL)
                                           └──→ Discord (HIGH/MEDIUM)

Kafka events ──→ service_auditor_agent ──→ _dispatch_webhook() ──→ Telegram/Discord
                 (already running)          (2 new methods)

bar_auditor_agent ──→ market_data_gaps (new table)
                  └──→ topic_gap_fill_dlq() (new topic, on retry exhaustion)

roll_compute_agent ──→ topic_roll_events ──→ service_auditor_agent
                                             └──→ systemctl restart indicagent-ibkr-provider
```

**Grafana** handles metric-based thresholds (lag trends, latency percentiles, completeness %). These require time-window aggregation — Prometheus/Grafana is the right tool.

**`service_auditor_agent`** handles event-based alerts (crash escalation, roll detected, bootstrap failure). These are already Kafka events — routing them through Grafana would add polling latency and convert events into fake metrics.

No new agents. No new Docker containers. No new infrastructure.

---

## Component 1: Grafana Alerting

### Contact Points

| Name | Channel | Severity |
|------|---------|---------|
| `telegram-critical` | Telegram bot DM | CRITICAL only |
| `discord-ops` | Discord `#indicagent-ops` webhook | HIGH + MEDIUM |

### Alert Rules (`production/grafana/provisioning/alerting/alert-rules.yml`)

| Severity | Name | Expression | Threshold |
|----------|------|-----------|-----------|
| CRITICAL | Provider dead | `rate(provider_bars_produced_total[5m])` | `== 0` during market hours |
| CRITICAL | Service crash-looping | `rate(service_auditor_service_restarts_total[10m])` | `> 3` — requires new counter in `service_auditor_agent` (see Component 4c) |
| CRITICAL | Signals being dropped | `increase(signal_writer_buffer_dropped_total[5m])` | `> 0` |
| CRITICAL | Signal DLQ growing | `increase(intelligence_pipeline_signal_dlq_total[5m])` | `> 0` |
| CRITICAL | Data completeness critical | `bar_auditor_canonical_completeness_pct` | `< 90` |
| HIGH | Consumer lag — any writer | writer consumer lag metrics | `> 1000` messages |
| HIGH | Bar flow stale | `bar_agg_time_since_last_bar_seconds` | `> 300` |
| HIGH | Output buffer pressure | `intelligence_pipeline_output_buffer_depth` | `> 400` |
| HIGH | Gap fill DLQ growing | `gap_fill_dlq_depth` counter | `> 0` |
| MEDIUM | Data completeness soft | `bar_auditor_canonical_completeness_pct` | `< 95` |

### Provisioning Structure

```
production/grafana/
  provisioning/
    alerting/
      contact-points.yml        ← gitignored (real credentials)
      contact-points.example.yml ← committed (placeholder values)
      alert-rules.yml           ← committed (all rule definitions)
    dashboards/
      dashboards.yml            ← existing, unchanged
  dashboards/
    operations.json             ← new (replaces service-overview.json)
    pipeline-health.json        ← rebuilt in place
    signals-i8.json             ← rebuilt in place
```

`contact-points.yml` added to `.gitignore`. Bot token and webhook URL never committed.

### Naming Conventions

- Provisioning files: kebab-case YAML
- Alert rule names: `snake_case` matching the metric domain
- Dashboard files: kebab-case JSON

---

## Component 2: Data Completeness

### Migration: `market_data_gaps` Table

```sql
-- 062_market_data_gaps.sql
CREATE TABLE market_data_gaps (
    id            BIGSERIAL    PRIMARY KEY,
    symbol        TEXT         NOT NULL,
    tf            TEXT         NOT NULL,
    gap_start_ts  TIMESTAMPTZ  NOT NULL,
    gap_end_ts    TIMESTAMPTZ,           -- NULL while gap is ongoing
    bars_expected INT          NOT NULL,
    bars_missing  INT          NOT NULL,
    detected_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ,           -- set when bar_auditor confirms filled
    UNIQUE (symbol, tf, gap_start_ts)
);
CREATE INDEX ON market_data_gaps (symbol, tf, gap_start_ts);
```

### `bar_auditor_agent` Changes

**Write path (on each audit cycle):**
- When `completeness_pct < 100%` for a (symbol, tf): UPSERT into `market_data_gaps`
  - If gap already exists for `gap_start_ts`: update `bars_missing`
  - If new gap: INSERT with `gap_end_ts = NULL`
- When `completeness_pct == 100%` and an open gap row exists: set `resolved_at = NOW()`, `gap_end_ts = NOW()`

**Consumer offset fix:**
- Change `auto_offset_reset="latest"` → `"earliest"` on the gap requests consumer
- Add in-memory dedup: `_seen_gap_requests: set[tuple[str, str, datetime]]` cleared every 24h
- Prevents re-processing the same gap request on consumer restart

**Gap fill DLQ:**
- When `_gap_requests_loop()` in `base_provider_agent` fails after 3 retries: publish to `topic_gap_fill_dlq()`
- Payload: `{symbol, tf, start_ts, end_ts, retry_count, error}`
- `bar_auditor_agent` exposes a `gap_fill_dlq_depth` Prometheus counter
- Grafana HIGH alert fires when counter grows

**Downstream value:**
- ML training JOINs `market_data_gaps` to exclude contaminated windows
- Backfill scripts query it for what to fill
- Signal ledger rows where `feature_ts` falls within a known gap can be flagged

### Naming

- Table: `market_data_gaps` (snake_case plural noun ✓)
- New Kafka topic: `topic_gap_fill_dlq()` in `stream_keys.py` → `{env}.gap_fill.dlq`
- New Prometheus counter: `bar_auditor_gap_fill_dlq_depth` (follows `bar_auditor_*` prefix)

---

## Component 3: Roll Automation

### Design

`service_auditor_agent` adds a second Kafka consumer for `topic_roll_events` alongside its existing health event consumer. Both run as concurrent asyncio tasks within the same process — no new service.

**On `RollEvent` with `event_type = "roll_complete"`:**
1. Log: `roll_automation.triggered {symbol} {old_expiry} → {new_expiry}`
2. Dispatch HIGH alert: "Futures roll: {symbol} {old}→{new}, restarting provider"
3. `subprocess.run(["sudo", "systemctl", "restart", "indicagent-ibkr-provider"], check=True)`

**Dedup guard:** `_handled_rolls: set[tuple[str, str]]` tracking `(symbol, new_expiry)` — Kafka at-least-once delivery cannot trigger a double restart.

**Gate:** Only fires on `roll_complete`, not `roll_imminent` or `roll_detected` — prevents premature restarts before the old contract actually expires.

**Sudoers entry** (scoped to exactly one command):
```
bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider
```

### Naming

- New consumer group: `service_auditor_roll_consumer` (follows `<concept>_consumer` pattern)
- New methods: `_handle_roll_event()`, `_restart_ibkr_provider()` — private snake_case ✓

---

## Component 4: Code Fixes

### 4a. `signal_tracker_compute_agent` Bootstrap Retry

**Problem:** Single DB query. Slow DB → zero signals loaded → silent logic failure.

**Fix:** Wrap `_bootstrap_active_signals()` in retry loop:
- 3 attempts with 2s / 4s / 8s exponential backoff
- Success condition: `len(active_signals) > 0` OR ledger COUNT query returns 0 (provably empty)
- Failure condition: 0 signals loaded when ledger has rows → retry
- `sd_notify(READY=1)` moves to after successful bootstrap (systemd won't mark ready until state is valid)

### 4b. `SwarmOrchestratorComputeAgent` Context Cache Seeding

**Problem:** `SwarmContextCache` starts empty — first N bars processed without historical regime context.

**Fix:** In `_setup()`, before the consume loop:
- Query last 200 rows per (symbol, tf) from `intelligence_features`
- Load into `SwarmContextCache`
- One startup DB read, amortized cost is negligible

### 4c. `service_auditor_agent` Webhook Dispatcher

Two new private methods following existing agent patterns:

```python
async def _notify_telegram(self, title: str, body: str) -> None:
    """POST CRITICAL alert to Telegram bot."""

async def _notify_discord(self, title: str, body: str, severity: str) -> None:
    """POST HIGH/MEDIUM alert to Discord webhook."""

async def _dispatch_webhook(self, severity: str, title: str, body: str) -> None:
    """Route alert to correct contact point(s) based on severity."""
```

Called from:
- `_handle_escalation()` (existing, already fires at 3+ restarts) → CRITICAL
- `_handle_roll_event()` (new) → HIGH
- Bootstrap failure events from `signal_tracker_compute_agent` → HIGH

**New Prometheus counter** added to `src/observability/metrics.py`:
`service_auditor_service_restarts_total` — incremented each time `service_auditor_agent` triggers or observes a service restart. This drives the crash-looping Grafana alert.

**New `Settings` fields** added to `src/config/settings.py`:
```python
telegram_bot_token: str = ""
telegram_chat_id: str = ""
discord_webhook_url: str = ""
```
Populated via environment variables, never hardcoded. Empty string = channel disabled (no-op in dispatcher).

**`signal_tracker_compute_agent` bootstrap failure path:** On `bootstrap_failed`, the agent must publish a health event to `topic_system_health_events()` (already consumed by `service_auditor_agent`) with `event_type = "bootstrap_failed"`. `service_auditor_agent` routes this to `_dispatch_webhook()` → HIGH alert. Currently the agent only logs — this publish call is explicitly in scope.

Webhook URLs loaded from `Settings` — never hardcoded.

---

## Component 5: Dashboard Rebuild

Three Grafana dashboards covering the Golden Signals (Traffic, Latency, Errors, Saturation):

### Operations (`operations.json`) — Always-Open View

| Row | Panels |
|-----|--------|
| Service Health | Services running count · restart rate by service · data completeness % · active signals |
| Traffic | Bars produced rate · bars processed rate · time since last bar |
| Errors | Restart heatmap · signal DLQ · gap-fill DLQ · buffer drops rate |
| Saturation | Consumer lag per writer · output buffer depth · thread pool workers |
| Data Quality | Completeness % by (symbol, tf) · gap windows from `market_data_gaps` |

### Pipeline (`pipeline-health.json`) — Latency and Throughput

| Row | Panels |
|-----|--------|
| Latency | I1 p95 · I7 p95 · DB write p95 · merger bar p95 |
| Throughput | Bars/min · HTF bars emitted · signals generated vs selected vs written |
| Health | Plugin skips · state checkpoint failures · checkpoint fallback rate |

### Signals (`signals-i8.json`) — Rebuilt in Place

| Row | Panels |
|-----|--------|
| Signal Funnel | Generated vs selected vs written · active signals · lifecycle transitions/hr |
| Routing | Merger bars routed vs dropped · provider merger lag |
| AI Narrative | Narrative rate · LLM latency · LLM circuit breaker state |

---

## Naming Convention Audit

| Layer | New Name | Follows Rule |
|-------|---------|-------------|
| DB table | `market_data_gaps` | snake_case plural noun ✓ |
| Kafka topic fn | `topic_gap_fill_dlq()` | `topic_<output_domain>()` ✓ |
| Kafka topic string | `{env}.gap_fill.dlq` | dots only, env prefix ✓ |
| Consumer group | `service_auditor_roll_consumer` | `<concept>_consumer` ✓ |
| Prometheus counter | `bar_auditor_gap_fill_dlq_depth` | `<agent>_<metric>` prefix ✓ |
| Private methods | `_dispatch_webhook`, `_notify_telegram`, `_notify_discord`, `_handle_roll_event`, `_restart_ibkr_provider` | private snake_case ✓ |
| Grafana files | `contact-points.yml`, `alert-rules.yml`, `operations.json` | kebab-case ✓ |
| Migration | `062_market_data_gaps.sql` | sequential NNN ✓ |

---

## What Is NOT in Scope

- New agent services (no new `.py` service files, no new systemd units)
- AlertManager (Grafana native alerting is sufficient)
- Changes to I1–I7 plugin logic
- New Kafka topics beyond `topic_gap_fill_dlq()`
- `market_data_gaps` backfill for historical outages (separate script, future work)

---

## Success Criteria

1. A service crash-looping triggers a Telegram message within 60 seconds
2. Provider downtime > 5 min triggers a Telegram message
3. Every gap window is recorded in `market_data_gaps` with correct `bars_expected` / `bars_missing`
4. Futures roll triggers automatic `ibkr-provider` restart without human intervention
5. `signal-tracker-compute` starts with valid state even when DB responds slowly
6. `swarm_orchestrator` processes first bar with seeded context, not empty cache
7. All three Grafana dashboards load with current service names and live data
8. No Prometheus queries reference archived service names
