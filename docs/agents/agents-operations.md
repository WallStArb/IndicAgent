# Agents Operations — Service Mesh, DAG Topology & Lifecycle Management

**Version:** 2.8.0 | **Status:** current | **Last Updated:** 2026-05-29

---

## Purpose

This document describes how the system of agents is managed: the service auditor that watches them, the DAG that determines restart order, the lag thresholds that define health, and the procedures for diagnosing and recovering from failures.

**Audience:** Engineers adding a new service to the mesh, debugging startup cascade failures, or understanding why a service was auto-restarted.

---

## Design Principles

### Why the Service Auditor Exists

systemd provides process liveness (WatchdogSec kills hung processes). Prometheus provides metrics and lag. Neither alone gives graduated, DAG-aware response. The `ServiceAuditor` adds the third layer: it reads both systemd unit state and Prometheus consumer-lag metrics, then applies a graduated response policy — DEGRADED (log), RESTART (systemctl), ESCALATE (DLQ + stop retrying) — in dependency order.

Without the auditor, a crash in `indicagent-bar-aggregator` would cascade: `indicagent-intelligence-pipeline` would keep running but receive no bars, look healthy to systemd, and silently produce no output. The auditor detects the lag stall and restarts the right service in the right order.

### Why `_DAG_ORDER` Is the Single Source of Truth

`_DAG_ORDER` in `services/service_auditor.py` is the canonical registry. CLAUDE.md says "Never maintain a parallel list here." The reason: two lists drift. When a service is added to CLAUDE.md's architecture overview but not to `_DAG_ORDER`, the auditor does not know about it and cannot restart it. The code is authoritative.

### Why Layered Restart (Not Random)

Restarting services in random order causes thundering-herd failures: if `indicagent-intelligence-pipeline` (L6 in the auditor's priority numbering) restarts before `indicagent-bar-aggregator` (L3) is healthy, the pipeline starts with empty state and processes zero messages. Restart order follows `_DAG_ORDER` priority: lower number restarts first.

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
| L6 — intelligence pipeline | 6 | `intelligence-pipeline` |
| L7 — persistence writers | 7 | `feature-writer`, `signal-writer`, `signal-tracker-compute`, `lifecycle-writer`, `lineage-writer`, `ctx-writer` |
| L8 — AI/analytics layer | 8 | `alpha-swarm`, `narrative-compute`, `llm-writer`, `swarm-ledger-writer`, `signal-metrics-compute`, `signal-metrics-writer`, `graduation-compute`, `graduation-writer`, and all timer-triggered oneshot services |
| L9 — audit, parity, alerting | 9 | `signal-auditor`, `signal-replay`, `alerting-agent`, `dlq-drain` |
| L10 — top-level services | 10 | `api`, `dashboard` |
| Meta-monitor | 11 | `service-auditor` |

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
    "indicagent-intelligence-pipeline": 6,
    "indicagent-feature-writer": 7,
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
    # oneshot timer services (priority 8 — inactive between runs is correct)
    "indicagent-weight-updater": 8,
    "indicagent-shadow-auditor": 8,
    "indicagent-ml-orchestrator": 8,
    "indicagent-ml-data-quality": 8,
    "indicagent-ml-discovery": 8,
    "indicagent-ml-training": 8,
    "indicagent-ml-signal-training-materialize": 8,
    "indicagent-roll-batch": 8,  # nightly 8pm timer; futures roll detection
    "indicagent-feature-validation": 8,
    "indicagent-hmm-training": 8,
    "indicagent-signal-auditor": 9,
    "indicagent-signal-replay": 9,
    "indicagent-alerting-agent": 9,
    "indicagent-dlq-drain": 9,
    "indicagent-api": 10,
    "indicagent-dashboard": 10,
    "indicagent-service-auditor": 11,
}
```

### `_LAG_THRESHOLDS` (messages before DEGRADED)

```python
_LAG_THRESHOLDS: dict[str, int] = {
    "indicagent-provider-merger": 500,
    "indicagent-bar-aggregator": 500,
    "indicagent-bar-auditor": 200,
    "indicagent-bar-writer": 1000,
    "indicagent-intelligence-pipeline": 500,
    "indicagent-cross-asset": 200,
    "indicagent-macro-compute": 500,
    "indicagent-feature-writer": 1000,
    "indicagent-signal-tracker-compute": 500,
    "indicagent-signal-writer": 500,
    "indicagent-lifecycle-writer": 500,
    "indicagent-lineage-writer": 500,
    "indicagent-alpha-swarm": 200,
    "indicagent-narrative-compute": 200,
    "indicagent-llm-writer": 500,
    "indicagent-swarm-ledger-writer": 500,
    "indicagent-signal-metrics-writer": 500,
    "indicagent-graduation-compute": 500,
    "indicagent-graduation-writer": 500,
    "indicagent-ctx-writer": 500,
    "indicagent-dlq-drain": 500,
}
```

Services absent from `_LAG_THRESHOLDS` are not Kafka consumers (providers, infra sentinels, top-level services). Their health is determined solely by systemd unit state.

### `_AGENT_ID_TO_UNIT` (label → systemd unit)

The `PERSISTENCE_CONSUMER_LAG` metric uses `agent_id` label whose value comes from the `name=` argument passed to `super().__init__()`. This map translates that label to a systemd unit name so the auditor can restart the right service.

```python
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer_agent":              "indicagent-bar-writer",
    "bar_aggregator_agent":          "indicagent-bar-aggregator",
    "intelligence_pipeline_agent":   "indicagent-intelligence-pipeline",
    "feature_writer_agent":          "indicagent-feature-writer",
    "SignalTracker":      "indicagent-signal-tracker-compute",
    "signal_writer_agent":           "indicagent-signal-writer",
    "llm_writer_agent":              "indicagent-llm-writer",
    "CrossAssetAnalyzer":        "indicagent-cross-asset",
    "bar_auditor_agent":             "indicagent-bar-auditor",
    "provider_merger_agent":         "indicagent-provider-merger",
    "lifecycle_writer_agent":        "indicagent-lifecycle-writer",
    "lineage_writer_agent":          "indicagent-lineage-writer",
    "signal_metrics_compute":        "indicagent-signal-metrics-compute",
    "signal_metrics_writer":         "indicagent-signal-metrics-writer",
    "AlphaSwarm":        "indicagent-alpha-swarm",
    "NarrativeSwarm":    "indicagent-narrative-compute",
    "swarm_ledger_writer":           "indicagent-swarm-ledger-writer",
    "MacroAnalyzer":             "indicagent-macro-compute",
    "signal_auditor_agent":          "indicagent-signal-auditor",
    "GraduationAnalyzer":        "indicagent-graduation-compute",
    "graduation_writer_agent":       "indicagent-graduation-writer",
    "ctx_writer_agent":              "indicagent-ctx-writer",
    "bar_replay_provider":           "indicagent-bar-replay",
    "signal_replay_auditor":         "indicagent-signal-replay",
    "dlq_drain_agent":               "indicagent-dlq-drain",
}
```

---

## Metrics Ports

Each daemon service exposes OTel metrics via its assigned port. All ports are scraped by the OTel Collector at `:4317` and forwarded to Prometheus at `:9090`.

| Service | systemd unit suffix | Metrics port |
|---------|---------------------|-------------|
| IBKRProvider | `ibkr-provider` | `:9129` |
| ProviderMerger | `provider-merger` | `:9130` |
| BarAggregator | `bar-aggregator` | `:9120` |
| BarWriter | `bar-writer` | `:9121` |
| BarAuditor | `bar-auditor` | `:9123` |
| CrossAssetService | `cross-asset` | `:9118` |
| IntelligencePipeline | `intelligence-pipeline` | `:9125` |
| FeatureWriter | `feature-writer` | `:9116` |
| FeatureSnapshotWriter | `feature-snapshot-writer` | `:9132` |
| ParityAuditor | `parity-auditor` | `:9133` |
| SignalWriter | `signal-writer` | `:9119` |
| SignalTracker | `signal-tracker-compute` | `:9115` |
| SignalAuditor | `signal-auditor` | `:9128` |
| SignalMetricsAnalyzer | `signal-metrics-compute` | `:9126` |
| NarrativeSwarm | `narrative-compute` | `:9113` |
| LLMWriter | `llm-writer` | `:9117` |
| ServiceAuditor | `service-auditor` | `:9131` |

Services absent from this table (API, dashboard, timer-based oneshots) do not expose dedicated metrics ports — their health is determined by systemd unit state only.

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
"indicagent-my-new-service": 7,  # priority 7: downstream of intelligence-pipeline (6)
```

**Step 2: Add to `_LAG_THRESHOLDS` (if it is a Kafka consumer).**

Set the threshold to the maximum acceptable consumer lag in messages. Compute agents: 200-500. Writers: 500-1000. If the service is not a Kafka consumer (provider, timer, top-level), skip this step.

```python
"indicagent-my-new-service": 500,
```

**Step 3: Add to `_AGENT_ID_TO_UNIT` (if it is a `BaseWriter`).**

The key must exactly match the `name=` argument passed to `super().__init__()` in the service's constructor. This is how the auditor maps a Prometheus label to a systemd unit.

```python
"my_new_service_agent": "indicagent-my-new-service",
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
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds{agent_id="my_new_service_agent"}' | jq .
```

If the gauge is missing, the `name=` argument passed to `super().__init__()` does not match `_AGENT_ID_TO_UNIT`.

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

If `indicagent-intelligence-pipeline` fails to start, check in layer order:

1. Is Redpanda healthy? `docker exec redpanda rpk cluster health`
2. Is TimescaleDB accepting connections? `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"`
3. Is `indicagent-bar-aggregator` running? `systemctl status indicagent-bar-aggregator`
4. Is the relevant Kafka topic populated? `docker exec redpanda rpk topic describe market.bars`

A service at L6 cannot process messages if its upstream topic (produced by L3) is empty or the consumer group has no committed offsets.

### Log File Naming Convention

Log files follow `logs/<agent_snake_case>_agent.log`. The name is derived from the `name=` argument to `super().__init__()`. Examples:

| Service | Log file |
|---------|---------|
| `indicagent-feature-writer` | `logs/feature_writer_agent.log` |
| `indicagent-alpha-swarm` | `logs/alpha_swarm_compute_agent.log` |
| `indicagent-intelligence-pipeline` | `logs/intelligence_pipeline_agent.log` |
| `indicagent-narrative-compute` | `logs/narrative_group_compute_agent.log` |

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

- `docs/agents/agents-foundation.md` — BaseAgent contract, liveness signals, OODA loop rationale
- `docs/agents/agents-writers.md` — BaseWriter and the persistence pattern
- `services/service_auditor.py` — `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` (authoritative source)
- `docs/platform/platform-foundation.md` (planned) — infrastructure layer design
