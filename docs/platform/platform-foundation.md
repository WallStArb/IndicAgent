# Platform Foundation

**Version:** 2.8
**Last Updated:** 2026-05-29
**Status:** current

---

## Purpose

This document explains why the IndicAgent infrastructure is built the way it is. It is the primary reference for engineers deploying new services, understanding the infrastructure model, or diagnosing cascade failures.

The core premise: IndicAgent runs on a single high-memory server with a GPU. The infrastructure is sized exactly for that constraint — no cluster overhead, no Kubernetes complexity, no distributed state machines. Systemd + Docker is the right tool at this scale.

---

## Design Principles

### Why systemd instead of Kubernetes?

Kubernetes is the right answer when you need horizontal scaling across a cluster. IndicAgent does not. The workload is a single-server real-time pipeline: 132 plugins, sub-ms bar processing, GPU-resident LLM inference. Kubernetes would add:

- Cluster networking overhead (pod-to-pod latency matters here)
- etcd state management for a non-distributed system
- Container orchestration complexity with no scaling benefit

Systemd gives everything needed: dependency ordering (via `After=`/`Requires=`), automatic restart (`Restart=always`), process isolation, and first-class `sd_notify` integration for watchdog heartbeating. The service DAG maps directly to systemd `After=` declarations.

**Scaling strategy:** When throughput limits are hit, add more systemd workers or split a service into parallel instances. Prometheus lag monitoring (`consumer_stall_detected_total`) identifies the bottleneck before it becomes a crisis.

### Why Docker for infrastructure components, systemd for services?

Docker containers manage stateful infrastructure that pre-existed the project (TimescaleDB, Redpanda) or are third-party services with their own lifecycle (Ollama, OTel Collector, Grafana). They are long-lived, not redeployed on every code change, and need volume persistence.

Python services (agents) are deployed as systemd units because:
- They need tight integration with the host process model (`sd_notify`, watchdog, journald)
- Hot reloads and restarts are per-service, not per-container
- Dependency ordering between Python services is expressed cleanly in unit files

The split is: **infrastructure = Docker, business logic = systemd.**

### Why timer units for batch jobs instead of daemons?

Batch jobs (ML training, shadow auditor, roll detection, feature validation) run periodically and then exit. A daemon consuming zero messages for 23 hours adds noise to health monitoring. Timer units:
- Have clean start/stop semantics
- Emit `job_completed_total{status}` at exit for alerting (see OTel Health Contract)
- Show `inactive (dead)` between runs — that is correct, not a failure
- Can be triggered manually with `systemctl start <unit>.service` for debugging

### Why `restart: unless-stopped` for all Docker containers?

All 14 Docker containers use `restart: unless-stopped` (or `restart: always` for `ib-gateway`). This ensures:
- Automatic recovery from transient failures without operator intervention
- Services survive Docker daemon restarts (e.g., after host reboot)
- Only an explicit `docker stop` prevents restart, distinguishing intentional from accidental stops

`ib-gateway` uses `restart: always` because IBKR sessions expire nightly and the gateway must restart automatically.

---

## Architecture

### L1-L10 Service DAG

Services are organized in dependency layers. Higher layers depend on lower layers. The canonical registry is `_DAG_ORDER` in `services/service_auditor.py`.

```
L1  ibkr-provider, bar-replay            — data ingestion + bar replay
L2  provider-merger                      — stream merge
L3  bar-aggregator, bar-auditor          — bar processing
L4  bar-writer                           — OHLCV persistence
L5  intelligence-pipeline, cross-asset,  — I1-I7 compute + context
    macro-compute
L6  feature-writer, signal-writer,       — persistence writers (parallel)
    signal-tracker-compute, lifecycle-writer,
    lineage-writer, ctx-writer
L7  alpha-swarm, narrative-compute,      — AI/LLM layer
    llm-writer, swarm-ledger-writer
L8  signal-metrics-compute,              — analytics
    signal-metrics-writer, graduation-compute,
    graduation-writer, feature-snapshot-writer,
    ml-training
L9  signal-auditor, signal-replay,       — audit, parity, alerting
    parity-auditor, alerting-agent
L10 service-auditor                      — meta: monitors + restarts all above
```

**ML batch services** (`ml-training`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`) are timer-triggered, not daemons. `inactive (dead)` between runs is correct — do not treat as failures.

**Roll batch** (`roll-batch`) runs nightly at 8pm. Detects calendar-based futures rolls, promotes front-month contracts in `contract_metadata`, broadcasts updates via Kafka.

### Docker Container Inventory

All containers defined in `production/docker-compose.yml`. After any change: `cd production && docker compose up -d`.

| Container | Image | Ports | Purpose |
|-----------|-------|-------|---------|
| `timescaledb` | `timescale/timescaledb:latest-pg15` | `5432` | PostgreSQL + TimescaleDB — primary data store |
| `redpanda` | `redpandadata/redpanda:v25.3.10` | `19092` (Kafka), `18082` (HTTP proxy), `9644` (admin) | Kafka-compatible event bus |
| `ollama` | `ollama/ollama:rocm` | `127.0.0.1:11434` | Local LLM inference (GPU, ROCm) |
| `indicagent-node-exporter` | `prom/node-exporter` | `9100` | Host-level CPU/RAM/disk metrics |
| `indicagent-postgres-exporter` | `prometheuscommunity/postgres-exporter` | `9187` | TimescaleDB metrics |
| `indicagent-prometheus` | `prom/prometheus:v2.47.0` | `9090` | Metrics storage + alert evaluation |
| `indicagent-grafana` | `grafana/grafana:10.2.0` | `3001` | Dashboards (Prometheus + Tempo + Loki) |
| `indicagent-tempo` | `grafana/tempo:2.10.3` | — | Distributed trace storage |
| `indicagent-otel-collector` | `otel/opentelemetry-collector-contrib:0.102.0` | `4317` (gRPC), `4318` (HTTP), `8889` (Prometheus) | Central telemetry hub |
| `indicagent-alertmanager` | `prom/alertmanager:v0.27.0` | `9093` | Alert routing |
| `indicagent-loki` | `grafana/loki:2.9.6` | `3100` | Log aggregation |
| `indicagent-mlflow` | `ghcr.io/mlflow/mlflow` | `5000` | ML experiment tracking |
| `indicagent-langfuse` | `langfuse/langfuse:2` | `3010` | LLM observability |
| `ib-gateway` | `ghcr.io/gnzsnz/ib-gateway:stable` | `127.0.0.1:7497` (TWS), `127.0.0.1:5900` (VNC) | IBKR TWS headless gateway |

**Total: 14 Docker containers** (13 `restart: unless-stopped`, `ib-gateway` uses `restart: always`).

### systemd Unit Naming Convention

All systemd units follow the pattern: `indicagent-<name>.service` (daemons) or `indicagent-<name>.timer` + `indicagent-<name>.service` (timer-triggered batch jobs).

Timer units defined in `production/systemd/`:
- `indicagent-ml-training.timer` — nightly 11pm
- `indicagent-ml-orchestrator.timer`, `indicagent-ml-data-quality.timer`, `indicagent-ml-discovery.timer` — weekly Monday
- `indicagent-roll-batch.timer` — nightly 8pm
- `indicagent-shadow-auditor.timer`, `indicagent-feature-validation.timer`, `indicagent-redpanda-watchdog.timer` — various schedules

Installed units live in `/etc/systemd/system/`. Reference files in `production/systemd/` are the source; install manually after changes.

### How Services Communicate

Services communicate exclusively via Kafka topics (Redpanda). No direct service-to-service RPC calls. Topic construction is always via `src/core/stream_keys.py` — never hardcode topic strings.

**Critical:** `INDICAGENT_ENV` must be consistent across all services. Mixed env prefixes cause services to subscribe to different topics, resulting in zero data flow with no error messages. Check with:

```bash
grep INDICAGENT_ENV /etc/systemd/system/indicagent-*.service | head -5
```

---

## Data Contracts

### Checking Service Health

```bash
# All indicagent systemd units
systemctl list-units --all | grep indicagent

# Timer status (batch jobs)
systemctl list-timers --all | grep indicagent

# Specific service
systemctl status indicagent-intelligence-pipeline

# Docker containers
docker ps

# Service logs
tail -20 logs/<service>_agent.log
```

### Checking Data Flow

```bash
# Consumer lag (persistence agents)
docker exec redpanda rpk group describe feature_pipeline -t

# DB freshness
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT symbol, tf, MAX(ts) FROM intelligence_features GROUP BY symbol, tf ORDER BY MAX(ts) DESC LIMIT 5"

# Pipeline metrics
curl -s http://localhost:8000/metrics | grep bars_processed
```

### Required Environment Variables

| Variable | Example | Purpose |
|----------|---------|---------|
| `INDICAGENT_ENV` | `prod` | Topic prefix — MUST match across all services |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTel Collector endpoint |
| `TWS_USERID`, `TWS_PASSWORD` | — | IBKR credentials (ib-gateway Docker) |
| `LANGFUSE_NEXTAUTH_SECRET`, `LANGFUSE_SALT` | — | Langfuse auth (Docker) |

Full infrastructure reference: `docs/operations/operations-infrastructure.md`.

---

## How To Extend

### Adding a New systemd Daemon

1. Create `services/<name>_agent.py` following the `BaseAgent` pattern.
2. Add a unit file to `production/systemd/indicagent-<name>.service`:
   ```ini
   [Unit]
   Description=IndicAgent <Name>
   After=network.target indicagent-timescaledb-ready.service indicagent-redpanda-ready.service
   Requires=indicagent-timescaledb-ready.service

   [Service]
   Type=notify
   User=bg
   WorkingDirectory=/home/bg/dev/indicagent
   ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.<name>_agent
   Restart=always
   RestartSec=5
   WatchdogSec=60
   NotifyAccess=main
   Environment=INDICAGENT_ENV=prod

   [Install]
   WantedBy=multi-user.target
   ```
3. Install and enable: `sudo cp production/systemd/indicagent-<name>.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now indicagent-<name>.service`
4. Add to `_DAG_ORDER` in `services/service_auditor.py`.
5. Add OTel signals — see Phase 108 SOP in `docs/platform/platform-observability.md`.

**Mandatory unit file fields:** `Type=notify`, `WatchdogSec=60`, `NotifyAccess=main`. Without these, watchdog heartbeating is broken and `watchdog_notify_suppressed_total` increments.

### Adding a New Docker Service

1. Add the service block to `production/docker-compose.yml`.
2. Always include `restart: unless-stopped`.
3. Apply: `cd production && docker compose up -d <service-name>`.
4. Add to the container inventory table above.

---

## Failure Modes & Operations

### Cascade Failure Pattern

The DAG has hard dependencies: an L3 outage starves L5+. Example:

- `bar-aggregator` (L3) fails → no bars published → `intelligence-pipeline` (L5) processes nothing → all L6/L7/L8 persistence agents go idle → `agent_last_message_timestamp_seconds` goes stale → Grafana `Service Stall` alert fires within 120s.

Diagnosis:
```bash
# Find the failing layer
systemctl list-units --all | grep indicagent | grep -v running

# Check the failing service logs
tail -50 logs/<service>_agent.log

# Check upstream services
systemctl status indicagent-bar-aggregator indicagent-provider-merger
```

### `INDICAGENT_ENV` Mismatch

Symptom: services appear healthy (running, consuming) but no data flows through the pipeline. No errors logged.

Cause: one or more services have a different `INDICAGENT_ENV` value, so they subscribe to different Kafka topics.

Fix: grep all unit files for `INDICAGENT_ENV`, ensure all match.

### Common Startup Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| Service starts then exits immediately | Missing DB or Kafka readiness | Check `indicagent-timescaledb-ready` and `indicagent-redpanda-ready` status |
| `ModuleNotFoundError` | venv not activated or wrong path | Check `ExecStart` uses `.venv/bin/python` |
| `watchdog_notify_suppressed_total` incrementing | Missing `NotifyAccess=main` in unit file | Add `NotifyAccess=main` to `[Service]` section |
| Consumer lag growing | Downstream writer slow or dead | Check L6 writer services, `persistence_consumer_lag_records` metric |
| Docker container restart-looping | Dependency not ready | Check logs: `docker logs <container> --tail 50` |

---

## See Also

- **[agents-operations.md](../agents/agents-operations.md)** — Service registry DAG, role taxonomy
- **[platform-observability.md](platform-observability.md)** — OTel metrics, Grafana SLOs, circuit breakers
- **[platform-api.md](platform-api.md)** — FastAPI service, SSE streaming, health endpoints
- **[operations/infrastructure.md](../operations/infrastructure.md)** — Production procedures, deployment runbook
