# Agents Operations — Service Mesh, DAG Topology & Lifecycle Management

**Version:** 2.10.0 | **Status:** current | **Last Updated:** 2026-08-01

> **Resynced 2026-08-01 (todo 220):** the `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` tables below are
> a verbatim transcription of `services/service_auditor.py` as of that date — v2.x names
> (`feature-writer`, `intelligence-pipeline`, `parity-auditor`, `feature-snapshot-writer`) have
> been replaced with their live v3.0 equivalents (`feature-vector-writer`,
> `feature-vector-pipeline`, etc.). **Note for future readers:** the project intends to
> eventually run a second, more conventional intelligence path alongside v3.0's
> Renaissance-style AlphaEngine (reviving the paused v2.x signal chain, not replacing it) — if
> that happens, `_DAG_ORDER` will grow v2.x entries back in, and this table will need
> re-resyncing rather than treating the v2.x names as permanently retired. `services/service_auditor.py`
> remains the single authoritative source; treat this table as a snapshot, not a live mirror.

---

## Purpose

This document describes how the system of agents is managed: the service auditor that watches them, the DAG that determines restart order, the lag thresholds that define health, and the procedures for diagnosing and recovering from failures.

**Audience:** Engineers adding a new service to the mesh, debugging startup cascade failures, or understanding why a service was auto-restarted.

---

## Design Principles

### Why the Service Auditor Exists

systemd provides process liveness (WatchdogSec kills hung processes). Prometheus provides metrics and lag. Neither alone gives graduated, DAG-aware response. The `ServiceAuditor` adds the third layer: it reads both systemd unit state and Prometheus consumer-lag metrics, then applies a graduated response policy — DEGRADED (log), RESTART (systemctl), ESCALATE (DLQ + stop retrying) — in dependency order.

Without the auditor, a crash in `indicagent-bar-aggregator` would cascade: `indicagent-feature-vector-pipeline` would keep running but receive no bars, look healthy to systemd, and silently produce no output. The auditor detects the lag stall and restarts the right service in the right order.

### Why `_DAG_ORDER` Is the Single Source of Truth

`_DAG_ORDER` in `services/service_auditor.py` is the canonical registry. CLAUDE.md says "Never maintain a parallel list here." The reason: two lists drift. When a service is added to CLAUDE.md's architecture overview but not to `_DAG_ORDER`, the auditor does not know about it and cannot restart it. The code is authoritative.

### Why Layered Restart (Not Random)

Restarting services in random order causes thundering-herd failures: if `indicagent-feature-vector-pipeline` (priority 6 in the auditor's numbering) restarts before `indicagent-bar-aggregator` (priority 3) is healthy, the pipeline starts with empty state and processes zero messages. Restart order follows `_DAG_ORDER` priority: lower number restarts first.

### Why Lag-Based Health (Not Just Process Liveness)

A running process with a stalled consumer is operationally dead. `PERSISTENCE_CONSUMER_LAG` and `agent_last_message_timestamp_seconds` together cover both sides: the writer's buffer depth and the last time any message was processed. `_LAG_THRESHOLDS` defines per-service thresholds above which the auditor emits a DEGRADED event; two consecutive degraded checks trigger a RESTART.

---

## Architecture

### Service Auditor Graduated Response

```
Check cycle (every 15s):
  for each service in _DAG_ORDER (lowest priority first):
    state = systemctl_status(unit)
    lag   = prometheus_query(PERSISTENCE_CONSUMER_LAG{agent_id=...})

    HEALTHY   → no action
    DEGRADED  → lag > threshold, 1st detection: emit degraded event, log warning
    DEGRADED  → lag > threshold, 2nd consecutive: emit degraded event, no restart yet
    RESTART   → unit is dead/failed/StartLimitHit: systemctl reset-failed + start
    ESCALATE  → 3 restarts in 10 minutes: DLQ + stop retrying + emit escalated event
    RECOVERED → returns healthy after degraded: emit recovered event with duration_degraded_s
```

Every state transition is written to `service_health_events` (TimescaleDB) and published to the `system.health.events` Kafka topic — both are permanent audit trails.

### Layer Topology (L1-L10)

The layers below map to `_DAG_ORDER` priority numbers. Lower priority = restarts first.

| Layer | Priority | Services |
|-------|----------|---------|
| Infra sentinels | 0 | `redpanda-ready`, `redpanda-watchdog`, `timescaledb-ready` |
| L1 — data ingestion | 1 | `ibkr-provider`, `bar-replay` |
| L2 — stream merge | 2 | `provider-merger` |
| L3 — bar processing | 3 | `bar-aggregator`, `bar-auditor` |
| L4 — bar persistence | 4 | `bar-writer` |
| L5 — intelligence context | 5 | `cross-asset`, `macro-compute` |
| L6 — feature factory pipeline | 6 | `feature-vector-pipeline` |
| L7 — persistence writers | 7 | `feature-vector-writer`, `signal-writer`, `signal-tracker-compute`, `lifecycle-writer`, `lineage-writer`, `ctx-writer` |
| L8 — AI/analytics + IC/ensemble/alpha oneshots | 8 | `alpha-swarm`, `narrative-compute`, `llm-writer`, `swarm-ledger-writer`, `signal-metrics-compute`, `signal-metrics-writer`, `graduation-compute`, `graduation-writer`, `regime-writer`, `forward-return-writer`, `ic-engine`, `ensemble-trainer`, `alpha-publisher`, `ensemble-ic-engine`, `alpha-frame-writer`, `counterfactual-tracker`, and all timer-triggered oneshot services (ML batch, shadow, feature-validation, hmm-training, memory-batch) |
| L9 — audit, parity, alerting, config/self-healing | 9 | `signal-auditor`, `signal-replay`, `alerting-agent`, `dlq-drain`, `config-service`, `outbox-dispatcher`, `self-healing-agent` |
| L10 — top-level services | 10 | `api`, `dashboard` |
| Meta-monitor | 11 | `service-auditor` |

**Not in `_DAG_ORDER` despite being a timer-triggered oneshot:** `indicagent-roll-batch` is
listed in `_ONESHOT_UNITS` (so the auditor knows not to treat "inactive between runs" as a
failure) but has no `_DAG_ORDER` entry at all — a live asymmetry in the code, not a doc
staleness artifact; noted here rather than silently reproduced.

### `_DAG_ORDER` (authoritative — from `services/service_auditor.py`)

```python
_DAG_ORDER: dict[str, int] = {
    "indicagent-redpanda-ready": 0,
    "indicagent-redpanda-watchdog": 0,
    "indicagent-timescaledb-ready": 0,
    "indicagent-ibkr-provider": 1,
    "indicagent-bar-replay": 1,
    "indicagent-provider-merger": 2,
    "indicagent-bar-aggregator": 3,
    "indicagent-bar-auditor": 3,
    "indicagent-bar-writer": 4,
    "indicagent-cross-asset": 5,
    "indicagent-macro-compute": 5,
    "indicagent-feature-vector-pipeline": 6,
    "indicagent-feature-vector-writer": 7,
    "indicagent-signal-tracker-compute": 7,
    "indicagent-signal-writer": 7,
    "indicagent-lifecycle-writer": 7,
    "indicagent-lineage-writer": 7,
    "indicagent-ctx-writer": 7,
    "indicagent-alpha-swarm": 8,
    "indicagent-narrative-compute": 8,
    "indicagent-llm-writer": 8,
    "indicagent-swarm-ledger-writer": 8,
    "indicagent-signal-metrics-compute": 8,
    "indicagent-signal-metrics-writer": 8,
    "indicagent-graduation-compute": 8,
    "indicagent-graduation-writer": 8,
    "indicagent-ml-training": 8,
    "indicagent-ml-signal-training-materialize": 8,
    "indicagent-memory-batch": 8,  # oneshot: nightly 21:00 memory backfill + calibration promotion
    # timer-triggered oneshots (priority 8 — inactive between runs is correct)
    "indicagent-weight-updater": 8,
    "indicagent-shadow-auditor": 8,
    "indicagent-shadow-validator": 8,  # oneshot: weekly Mon 07:00 UTC, promotion-only
    "indicagent-feature-parity-auditor": 8,
    "indicagent-confidence-calibration-monitor": 8,
    "indicagent-signal-probe-auditor": 8,
    "indicagent-ml-orchestrator": 8,
    "indicagent-ml-data-quality": 8,
    "indicagent-ml-discovery": 8,
    "indicagent-feature-validation": 8,
    "indicagent-hmm-training": 8,
    # Phase 138 IC pipeline oneshots (inactive between IC pipeline runs is correct)
    "indicagent-regime-writer": 8,
    "indicagent-forward-return-writer": 8,
    "indicagent-ic-engine": 8,
    # Phase 139 ensemble + alpha emission oneshots (inactive between IC pipeline runs is correct)
    "indicagent-ensemble-trainer": 8,
    "indicagent-alpha-publisher": 8,
    "indicagent-ensemble-ic-engine": 8,  # Phase 142A
    "indicagent-alpha-frame-writer": 8,  # Phase 142B
    "indicagent-counterfactual-tracker": 8,  # Phase 142B
    "indicagent-signal-auditor": 9,
    "indicagent-signal-replay": 9,
    "indicagent-alerting-agent": 9,
    "indicagent-dlq-drain": 9,
    "indicagent-config-service": 9,  # OPS config HTTP API (port 9001)
    "indicagent-outbox-dispatcher": 9,
    "indicagent-self-healing-agent": 9,
    "indicagent-api": 10,
    "indicagent-dashboard": 10,
    "indicagent-service-auditor": 11,
}
```

Note: `indicagent-roll-batch` is a timer-triggered oneshot (`_ONESHOT_UNITS`) with no
`_DAG_ORDER` entry — see the callout above the layer table.

### Lag Thresholds (messages before DEGRADED)

**Behavioral drift from the version of this doc stamped 2026-05-29:** `_LAG_THRESHOLDS` is no
longer a hardcoded module-level dict. Per the Adaptive Parameter Registry migration (CLAUDE.md
Service Registry gotcha), thresholds are now seeded as `alert.lag.*` keys in `config_state` and
loaded at startup by `ServiceAuditor._load_lag_thresholds()`, then hot-reloaded when `alert.lag.*`
Kafka config-update messages arrive — no code change or restart needed to retune a threshold.
`services/service_auditor.py` keeps a code comment noting the original 21 entries were seeded by
`production/migrations/103_config_foundation.sql` (Phase 109 Plan 05 Task 3); check
`config_state` directly (or `/config/parameters` in the dashboard) for current values rather than
looking for a static dict in the source.

Services absent from an `alert.lag.*` key are not Kafka consumers (providers, infra sentinels, top-level services). Their health is determined solely by systemd unit state.

### `_AGENT_ID_TO_UNIT` (label → systemd unit)

The `PERSISTENCE_CONSUMER_LAG` metric uses `agent_id` label whose value comes from the `name=` argument passed to `super().__init__()`. This map translates that label to a systemd unit name so the auditor can restart the right service.

```python
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer":                    "indicagent-bar-writer",
    "bar_aggregator":                "indicagent-bar-aggregator",
    "feature_vector_pipeline":       "indicagent-feature-vector-pipeline",
    "feature_vector_writer":         "indicagent-feature-vector-writer",
    "signal_tracker":                "indicagent-signal-tracker-compute",
    "signal_writer":                 "indicagent-signal-writer",
    "llm_writer":                    "indicagent-llm-writer",
    "cross_asset_analyzer":          "indicagent-cross-asset",
    "bar_auditor":                   "indicagent-bar-auditor",
    "provider_merger":               "indicagent-provider-merger",
    "lifecycle_writer":              "indicagent-lifecycle-writer",
    "lineage_writer":                "indicagent-lineage-writer",
    "signal_metrics_analyzer":       "indicagent-signal-metrics-compute",
    "signal_metrics_writer":         "indicagent-signal-metrics-writer",
    "alpha_swarm":                   "indicagent-alpha-swarm",
    "narrative_swarm":               "indicagent-narrative-compute",
    "swarm_ledger_writer":           "indicagent-swarm-ledger-writer",
    "macro_analyzer":                "indicagent-macro-compute",
    "signal_auditor":                "indicagent-signal-auditor",
    "graduation_analyzer":           "indicagent-graduation-compute",
    "graduation_writer":             "indicagent-graduation-writer",
    "context_writer":                "indicagent-ctx-writer",
    "bar_replay_provider":           "indicagent-bar-replay",
    "signal_replay_auditor":         "indicagent-signal-replay",
    "dlq_writer":                    "indicagent-dlq-drain",
    # Phase 109 services (config foundation + self-healing engine)
    "config_service":                "indicagent-config-service",
    "outbox_dispatcher_agent":       "indicagent-outbox-dispatcher",
    "self_healer":                   "indicagent-self-healing-agent",
}
```

Key format changed since the 2026-05-29 snapshot: keys are now the auto-derived
`BaseDaemon._to_snake_case(ClassName)` agent_id (e.g. `signal_tracker`, not `SignalTracker` or
`signal_tracker_agent`) — see the comment in `service_auditor.py` above this dict.

---

## Metrics Ports

**Corrected 2026-07-31 — this section previously described a pull/scrape model that does not
match the code.** `BaseDaemon.start()` calls `init_otel_providers(name)`
(`src/observability/otel.py`), which configures an `OTLPMetricExporter` — every daemon **pushes**
metrics via OTLP gRPC to the central OTel Collector at `OTEL_EXPORTER_OTLP_ENDPOINT`
(`http://localhost:4317` by default), not the other way around. There is no per-service scrape
port for the standard five OTel signals; init is a hard failure (raises, crashes the process) if
the collector is unreachable, so a missing collector is loud, not silent. The Collector fans
metrics out to Prometheus (`:9090` → Grafana `:3001`), traces to Tempo, and logs to Loki (see
`docs/platform/platform-observability.md`).

A small number of services additionally expose their own `METRICS_PORT`-configured HTTP endpoint
for reasons unrelated to the standard OTel signals (e.g. `config_service` on `:9005`,
`self_healer` on `:9007`) — check the service's own module docstring before assuming a numbered
port applies generally; it does not describe `BaseDaemon`'s default behavior.

---

## Data Contracts

### What the Service Auditor Reads

- **systemd unit state:** via `systemctl show <unit> --property=ActiveState,SubState` (polled every 15s).
- **Kafka consumer lag:** via Prometheus query to `http://localhost:9090/api/v1/query` using `PERSISTENCE_CONSUMER_LAG{agent_id="<name>"}`.
- **OTel liveness:** `agent_last_message_timestamp_seconds{agent_id="<name>"}` — stale > 120s triggers a consumer stall event and increments `CONSUMER_STALL_DETECTED_TOTAL`.

### What the Service Auditor Writes

- `service_health_events` table (TimescaleDB) — every state transition with timestamp, unit name, state, and context.
- `system.health.events` Kafka topic — same events for downstream consumers.
- `SERVICE_UP_GAUGE{unit=<name>}` — 1 when healthy, 0 when degraded/failed.
- `SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL{unit=<name>}` — increments on every triggered restart.
- Alert requests to `topic_alert_requests` for CRITICAL/HIGH severity events.

---

## How To Extend

### Adding a New Service to the Registry

Follow these steps in order. Missing any step means the auditor cannot monitor or restart the service.

**Step 1: Add to `_DAG_ORDER` at the right layer.**

Open `services/service_auditor.py`. Find the layer comment that matches your service's role. Add an entry with the correct priority number. Lower numbers restart first — your service should be higher (later) than its dependencies.

```python
"indicagent-my-new-service": 7,  # priority 7: downstream of feature-vector-pipeline (6)
```

**Step 2: Seed a lag threshold (if it is a Kafka consumer).**

Lag thresholds are APR-backed, not a hardcoded dict (see Lag Thresholds above) — seed an
`alert.lag.<name>` key in `config_state` (via migration or the `/config/parameters` dashboard)
with the maximum acceptable consumer lag in messages. Compute agents: 200-500. Writers: 500-1000.
If the service is not a Kafka consumer (provider, timer, top-level), skip this step.

**Step 3: Add to `_AGENT_ID_TO_UNIT`.**

The key must exactly match `BaseDaemon._to_snake_case(ClassName)` — the auto-derived `name` (and
therefore the `agent_id` label on both `PERSISTENCE_CONSUMER_LAG` and
`agent_last_message_timestamp_seconds`) unless the constructor passes an explicit `name=`
override. This applies to every `BaseDaemon` subclass, not just `BaseWriter` — the auditor uses
this same map for stall detection (`agent_last_message_timestamp_seconds`) as well as buffer-lag
detection (`PERSISTENCE_CONSUMER_LAG`).

```python
"my_new_service": "indicagent-my-new-service",
```

**Step 4: Create the systemd unit file.**

Copy an existing unit from `production/systemd/` that matches your service type (daemon or oneshot). Update `ExecStart`, `Description`, and `WatchdogSec`. Install it:

```bash
sudo cp production/systemd/indicagent-my-new-service.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-my-new-service
sudo systemctl start indicagent-my-new-service
```

**Step 5: Verify OTel signals are emitting.**

After the service starts, confirm the five mandatory signals appear in Prometheus within 60 seconds:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds{agent_id="my_new_service"}' | jq .
```

If the gauge is missing, the auto-derived `name` (or explicit `name=` override) does not match `_AGENT_ID_TO_UNIT`.

---

## Failure Modes & Operations

### Restarting a Stuck Service

```bash
sudo systemctl status indicagent-<name>         # check current state
sudo systemctl reset-failed indicagent-<name>   # clear FAILED state
sudo systemctl start indicagent-<name>          # start the service
```

The service auditor handles this automatically for most services. Manual intervention is needed when:
- The service has exceeded the escalation threshold (3 restarts in 10 minutes).
- The service auditor itself has stopped.
- The issue is a configuration error (wrong topic name, missing env var) that no restart can fix.

### Diagnosing Startup Cascade Failures

If `indicagent-feature-vector-pipeline` fails to start, check in layer order:

1. Is Redpanda healthy? `docker exec redpanda rpk cluster health`
2. Is TimescaleDB accepting connections? `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"`
3. Is `indicagent-bar-aggregator` running? `systemctl status indicagent-bar-aggregator`
4. Is the relevant Kafka topic populated? `docker exec redpanda rpk topic describe market.bars`

A service at L6 cannot process messages if its upstream topic (produced by L3) is empty or the consumer group has no committed offsets.

### Log File Naming Convention

Log files follow `logs/<name>.log` — **no `_agent` suffix** (that convention was retired along
with the `BaseAgent` → `BaseDaemon` rename; see `docs/agents/agents-foundation.md`). `<name>`
defaults to `BaseDaemon._to_snake_case(ClassName)` unless the constructor passes an explicit
`name=` override. Examples (live v3.0 services):

| Service | Log file |
|---------|---------|
| `indicagent-feature-vector-writer` | `logs/feature_vector_writer.log` |
| `indicagent-feature-vector-pipeline` | `logs/feature_vector_pipeline.log` |
| `indicagent-alpha-swarm` | `logs/alpha_swarm.log` |
| `indicagent-narrative-compute` | `logs/NarrativeSynthesizer.log` (worker class name, not the coordinator's) |

If in doubt: `ls logs/ | grep <partial_name>`.

### ML Batch Services: Inactive Between Runs Is Correct

These services are timer-triggered oneshots — they run, do work, and exit. `inactive (dead)` status is expected and should not trigger alerts:

- `indicagent-ml-training`, `indicagent-ml-signal-training-materialize` (nightly 11pm)
- `indicagent-ml-orchestrator`, `indicagent-ml-data-quality`, `indicagent-ml-discovery` (weekly Monday)
- `indicagent-roll-batch` (nightly 8pm)
- `indicagent-weight-updater`, `indicagent-shadow-auditor` (timer-triggered)
- `indicagent-feature-validation` (daily), `indicagent-hmm-training` (monthly)

All are in `_ONESHOT_UNITS` in `service_auditor.py` and are excluded from the restart logic. To verify a timer fired: `systemctl list-timers --all | grep <name>`. To see run logs: `journalctl -u indicagent-<name>`.

### Health Check Commands

```bash
# All services at a glance
systemctl list-units --all | grep indicagent

# Consumer lag across all writers
docker exec redpanda rpk group describe feature_pipeline -t

# DB freshness
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT symbol, tf, MAX(ts) FROM intelligence_features GROUP BY symbol, tf ORDER BY MAX(ts) DESC LIMIT 5"

# Service auditor state transitions (last 20)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT time, unit, state, context FROM service_health_events ORDER BY time DESC LIMIT 20"

# OTel liveness for a specific agent
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds' | jq '.data.result[] | select(.metric.agent_id == "feature_writer_agent")'
```

---

## See Also

- `docs/agents/agents-foundation.md` — BaseDaemon contract, liveness signals, OODA loop rationale
- `docs/agents/agents-writers.md` — BaseWriter and the persistence pattern
- `services/service_auditor.py` — `_DAG_ORDER`, `_AGENT_ID_TO_UNIT` (authoritative source); lag thresholds live in `config_state` (`alert.lag.*`), loaded by `_load_lag_thresholds()`
- `docs/platform/platform-foundation.md` — infrastructure layer design
