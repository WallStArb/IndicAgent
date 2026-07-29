# Infrastructure -- Systemd, Docker, and Servers

**Version:** 2.9
**Last Updated:** 2026-07-27
**Status:** current

---

## Purpose

Infrastructure operations: systemd supervision, Docker containers, deployment procedures, and server management for IndicAgent.

---

## Architecture

IndicAgent runs on a single server (`192.168.68.53`) with:

- **Services:** systemd-managed daemons (27 services) + oneshot timers (12)
- **Infrastructure:** Docker containers (TimescaleDB, Redpanda, Ollama, observability stack)
- **Supervision:** systemd with watchdog integration (Phase 108)
- **Telemetry:** OTel push-based to Collector, Prometheus scrape, Grafana dashboards

**Why systemd (not Docker for services):**
- Direct host integration (no container overhead for compute services)
- Native watchdog support for automatic restart
- Precise dependency control via `After=`/`Requires=`
- Journal-based logging aggregation
- Timer-based scheduling for batch jobs

---

## Systemd Supervision

### Service Types

**Daemon Services (Type=simple):** Long-running services that process Kafka streams

**Oneshot Services (Type=oneshot):** Timer-triggered scripts that exit after completion

### Unit File Pattern

#### Daemon Template

```ini
[Unit]
Description=IndicAgent <Service-Name>
After=network.target redpanda.service timescaledb.service
Wants=network-online.target

[Service]
Type=simple
User=bg
Group=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin:/usr/bin"
EnvironmentFile=/home/bg/dev/indicagent/.env

# Watchdog configuration (Phase 108)
WatchdogSec=60
NotifyAccess=main

# Python service
ExecStart=/home/bg/dev/indicagent/.venv/bin/python \
          /home/bg/dev/indicagent/services/<service_script>.py

# Auto-restart on failure
Restart=on-failure
RestartSec=10

# Security
NoNewPrivileges=true
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-<service-name>

[Install]
WantedBy=multi-user.target
```

#### Oneshot Template

```ini
[Unit]
Description=IndicAgent <Job-Name>
After=network.target timescaledb.service redpanda.service

[Service]
Type=oneshot
User=bg
Group=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin:/usr/bin"
EnvironmentFile=/home/bg/dev/indicagent/.env

ExecStart=/home/bg/dev/indicagent/.venv/bin/python \
          /home/bg/dev/indicagent/scripts/<script>.py

StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicant-<job-name>
```

#### Timer Template

```ini
[Unit]
Description=IndicAgent <Job-Name> Timer

[Timer]
OnCalendar=*-*-* 23:00:00  # Example: nightly at 11pm
Persistent=true

[Install]
WantedBy=timers.target
```

### Watchdog Integration (Phase 108)

**How it works:**
1. Service calls `sd_notify("WATCHDOG=1")` every `WatchdogSec / 2` seconds
2. systemd expects notification within `WatchdogSec` seconds
3. If no notification received, systemd kills and restarts the service

**BaseAgent implementation:**
```python
async def _watchdog_notify(self) -> None:
    socket_path = os.getenv("NOTIFY_SOCKET", "")
    usec = int(os.getenv("WATCHDOG_USEC", "0"))
    if not socket_path or usec <= 0:
        return
    import sdnotify
    notifier = sdnotify.SystemdNotifier()
    interval_s = usec / 2_000_000  # Ping at half watchdog interval
    while self.running:
        should_notify = True
        if self.max_idle_seconds > 0 and self._last_message_ts is not None:
            should_notify = (time.monotonic() - self._last_message_ts) < interval_s * 2
        if should_notify:
            notifier.notify("WATCHDOG=1")
            WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)
        else:
            WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)
        await asyncio.sleep(interval_s)
```

**Excluded from WatchdogSec:**
- `indicagent-dashboard` -- Next.js has no sd_notify; `Restart=always` sufficient
- All oneshot services -- WatchdogSec does not apply

### Service DAG

**Canonical source:** `_DAG_ORDER` in `services/service_auditor.py`

```
L0  Infrastructure sentinels
    indicagent-redpanda-ready, indicagent-timescaledb-ready,
    indicagent-infrastructure.target, indicagent-redpanda-watchdog

L1  Data ingestion
    indicagent-ibkr-provider, indicagent-bar-replay

L2  Stream routing
    indicagent-provider-merger

L3  Bar processing
    indicagent-bar-aggregator, indicagent-bar-auditor

L4  Bar persistence
    indicagent-bar-writer

L5  Intelligence pipeline
    indicagent-cross-asset, indicagent-macro-compute,
    indicagent-intelligence-pipeline

L6  Persistence writers (parallel)
    indicagent-feature-writer, indicagent-signal-writer,
    indicagent-lifecycle-writer, indicagent-lineage-writer,
    indicagent-ctx-writer, indicagent-signal-tracker-compute

L7  AI/LLM layer
    indicagent-alpha-swarm, indicagent-narrative-compute,
    indicagent-llm-writer, indicagent-swarm-ledger-writer

L8  Analytics (oneshot timers)
    indicagent-signal-metrics-compute, indicagent-graduation-compute,
    indicagent-ml-training, indicagent-ml-orchestrator, etc.

L9  Audit, parity, alerting
    indicagent-signal-auditor, indicagent-signal-replay,
    indicagent-alerting-agent, indicagent-dlq-drain

L10 Top-level
    indicagent-api, indicant-dashboard

L11 Meta
    indicant-service-auditor
```

**Priority:** Lower number = restarts first during graduated response.

### Manual/On-Demand Batch Services (no systemd timer)

Some batch services are deliberately NOT in `_DAG_ORDER` above and have no systemd unit or
timer at all. `services/cross_sectional_spread_tracker.py` (Phase 167, the T3 cross-sectional
decile long-short construction) is one of these, alongside `alpha_scorer.py`,
`counterfactual_tracker.py`, and `tag_calibrator.py`. Reasons a construction stays manual/
on-demand rather than getting a registered timer:

1. Peer precedent -- `alpha_scorer.py`, `counterfactual_tracker.py`, and `tag_calibrator.py`
   are all manual/on-demand with no systemd unit; a registered timer here would make this
   service the outlier.
2. CLAUDE.md's "prove edge before production infra" -- a construction that has not yet
   cleared its own Validation Gates does not earn scheduled infrastructure.
3. All indicagent systemd timers are confirmed disabled as of 2026-07-02 (CLAUDE.md) -- a
   registered timer would create a false impression of a cadence that does not actually run.
4. The `--backfill` pass populates the full 2006-2026 history in one shot, handing the gates
   the OOS day-cluster population immediately rather than waiting on calendar time.

**`cross_sectional_spread_tracker.py` -- the four CLI invocations:**

```bash
# One-time full-corpus backfill -- correct only for the first run, or immediately after a
# construction_spreads truncate. Populates the entire 2006-2026 history in one pass.
.venv/bin/python services/cross_sectional_spread_tracker.py --backfill

# Incremental compute-and-persist -- the correct invocation for every subsequent run. Resolves
# the watermark from the last persisted construction_spreads row and seeds prior leg membership
# from committed state only, so an interrupted run needs no special recovery flag -- the next
# plain incremental invocation recovers it (crash can only ever truncate a contiguous tail of
# the intended row set).
.venv/bin/python services/cross_sectional_spread_tracker.py

# Validation Gate 1 (shadow spread Sharpe), read-only against the OOS population
.venv/bin/python services/cross_sectional_spread_tracker.py --evaluate-gate

# Validation Gate 2 (attribution honesty), read-only against the OOS population
.venv/bin/python services/cross_sectional_spread_tracker.py --evaluate-attribution
```

Both evaluation modes (`--evaluate-gate`/`--evaluate-attribution`) are strictly read-only
against the database -- safe to run at any time, as many times as wanted. Each writes a
timestamped JSON verdict artifact under `logs/construction_verdicts/` (`gate1_<timestamp>.json`/
`gate2_<timestamp>.json` plus a `_latest.json` copy of each) that accumulates rather than
overwrites -- a later run never deletes an earlier verdict.

**Per-run summary manifest:** `.planning/corpus_manifests/cross_sectional_spread_tracker.json`
(written by both `--backfill` and the incremental mode; `construction_verdicts`-prefixed
manifests for the two evaluation modes live in the same directory). A `status: "partial"` in
this manifest means one or more bars were skipped as degenerate (too few symbols to form two
disjoint decile legs) -- expected at the very edges of the corpus, not itself an error.

**Recommended manual cadence:** run the plain incremental invocation periodically (weekly is
reasonable) to keep the OOS shadow track record current as new bars accumulate, then re-run
both evaluation modes to refresh the verdict artifacts. No timer enforces this -- it is a
manual operator action.

**Recovery:** `scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh`
truncates `construction_spreads` before `alpha_frames` on a corpus rebuild. After a truncate,
`--backfill` is the documented way to repopulate the table from scratch -- do not attempt to
resume from the incremental mode against an empty table (it will correctly detect an empty
table and fall back to backfill mode automatically, but running `--backfill` explicitly makes
the intent visible in the log).

### Service Management

```bash
# All services at a glance
systemctl list-units --all | grep indicagent

# Single service status
systemctl status indicagent-intelligence-pipeline

# Start/stop/restart
sudo systemctl start indicagent-<service>
sudo systemctl stop indicagent-<service>
sudo systemctl restart indicagent-<service>

# Reload after config change
sudo systemctl daemon-reload
sudo systemctl restart indicagent-<service>

# Logs (journald shows print() only -- structured logs in logs/<service>.log)
journalctl -u indicagent-<service> -n 50
journalctl -u indicagent-<service> -f
tail -f logs/<service>.log

# Timer management
systemctl list-timers --all | grep indicagent
systemctl status indicagent-ml-training.timer
```

### Environment Variables

**Critical:** All services must have consistent `INDICAGENT_ENV`. Mismatch causes topic naming divergence and silent data flow failure.

```bash
INDICAGENT_ENV=dev
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=gemma4:e4b
```

### File Locations

| Location | Purpose |
|----------|---------|
| `/etc/systemd/system/` | Service unit files (installed from `production/systemd/`) |
| `/etc/systemd/system/indicagent-*.timer` | Timer units for oneshot jobs |
| `/var/log/journal/` | Persistent journal storage |
| `/run/systemd/notify` | Notify socket for sd_notify |
| `/home/bg/dev/indicagent/.env` | Environment variables (loaded by all services) |

---

## Docker Infrastructure

### Containers

| Container | Port(s) | Purpose |
|-----------|---------|---------|
| `timescaledb` | `:5432` | TimescaleDB database |
| `redpanda` | `:19092` (Kafka), `:8081` (admin) | Kafka-compatible message broker |
| `ollama` | `:11434` | Local LLM inference |
| `otel-collector` | `:4317` (gRPC), `:4318` (HTTP), `:8889` (Prometheus) | Central telemetry hub |
| `indicagent-prometheus` | `:9090` | Metrics scrape and alert evaluation |
| `indicagent-grafana` | `:3001` | Dashboards |
| `indicagent-loki` | `:3100` | Log aggregation |
| `indicagent-tempo` | `:3200` (HTTP), `:4317` (OTLP) | Distributed traces |
| `indicagent-alertmanager` | `:9093` | Alert routing |
| `indicagent-mlflow` | `:5000` | ML experiment tracking |
| `ib-gateway` | `:7497` (TWS port mapped) | IBKR TWS gateway |

**All containers:** `restart: unless-stopped` in docker-compose.yml

### Docker Commands

```bash
# Status
docker ps --format "table {{.Names}}\t{{.Status}}"

# Logs
docker logs <container-name> --tail 50
docker logs <container-name> -f

# Restart container
docker restart <container-name>

# Enter container
docker exec -it <container-name> bash

# Compose management
cd production
docker compose up -d
docker compose ps
docker compose logs -f
```

### Redpanda (Kafka)

```bash
# Topic management
docker exec redpanda rpk topic list
docker exec redpanda rpk topic consume <topic-name> --from-end
docker exec redpanda rpk topic create <topic-name>

# Consumer groups
docker exec redpanda rpk group list
docker exec redpanda rpk group describe <group-name>

# Cluster info
docker exec redpanda rpk cluster info
```

### TimescaleDB

```bash
# Connect
docker exec -it timescaledb psql -U postgres indicagent

# Backup
pg_dump -U postgres -h localhost indicagent > backup.sql

# Restore
psql -U postgres -h localhost indicagent < backup.sql
```

### Ollama

```bash
# List models
docker exec ollama ollama list

# Pull model
docker exec ollama ollama pull <model-name>

# Generate (test)
docker exec ollama ollama run <model-name> "test prompt"

# Check VRAM
cat /sys/class/drm/card1/device/mem_info_vram_total
```

**Live services** `alpha_swarm` and `narrative_compute` hold persistent Ollama connections. Kill them before swapping models.

---

## Deployment

### Pre-Deployment Checklist

```bash
# Verify containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Verify OTel Collector receiving
docker logs indicagent-otel-collector --tail 20

# Verify Prometheus scraping
docker exec indicagent-prometheus wget -qO- http://localhost:9090/api/v1/rules

# Verify DB
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"

# Verify migration version
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"

# Verify git state
git branch --show-current  # Should be main
git status                 # Should be clean
git pull origin main
```

### Code Update Procedure

1. **Pull latest code**
   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Apply migrations** (if any)
   ```bash
   bash scripts/infrastructure/setup/infrastructure_db_setup.sh
   bash scripts/debug/validate/debug_db_verify.sh
   ```

3. **Update dependencies**
   ```bash
   source .venv/bin/activate
   uv pip install -r requirements.txt
   ```

4. **Rolling restart** (recommended)
   ```bash
   # L4: Persistence layer first
   sudo systemctl restart indicagent-bar-writer \
                       indicagent-feature-writer \
                       indicagent-signal-writer \
                       indicagent-lifecycle-writer
   sleep 10

   # L5: Compute layer
   sudo systemctl restart indicagent-intelligence-pipeline \
                       indicagent-alpha-swarm \
                       indicagent-narrative-compute
   sleep 10

   # L6-L7: Analytics
   sudo systemctl restart indicagent-signal-tracker-compute \
                       indicagent-signal-metrics-compute \
                       indicagent-llm-writer

   # L10: Service auditor last
   sudo systemctl restart indicant-service-auditor
   ```

5. **Update dashboard** (if applicable)
   ```bash
   cd dashboard && npm run build
   sudo systemctl restart indicagent-dashboard
   ```

### Docker Update Procedure

```bash
cd production
docker compose up -d
```

### Post-Deployment Verification

```bash
# Service health
systemctl list-units --all | grep indicagent | grep -v inactive
systemctl --failed --all | grep indicagent

# OTel signals
curl -s http://localhost:9090/api/v1/query?query=up | jq
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds' | jq

# Data flow
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(ts) FROM market_data_ohlcv GROUP BY symbol, tf ORDER BY MAX DESC LIMIT 5"

# Consumer lag
docker exec redpanda rpk group describe feature_pipeline_group
```

---

## Observability Stack

**Telemetry is push-based** -- services push OTLP to the Collector, no per-service scrape endpoints.

| Component | Port | Purpose |
|-----------|------|---------|
| OTel Collector | `:4317` (gRPC), `:4318` (HTTP), `:8889` (Prometheus) | Central telemetry hub |
| Prometheus | `:9090` | Scrapes Collector `:8889` only; evaluates alert rules |
| Grafana | `:3001` | Dashboards -- datasources: Prometheus, Tempo, Loki |
| Loki | `:3100` | Log aggregation (receives from OTel Collector) |
| Tempo | `:3200` (HTTP), `:4317` (OTLP) | Distributed traces (receives from OTel Collector) |
| Alertmanager | `:9093` | Alert routing -- receives from Prometheus |

**Verification:**
```bash
# Prometheus rules loaded
docker exec indicagent-prometheus wget -qO- http://localhost:9090/api/v1/rules

# OTel Collector receiving
docker logs indicagent-otel-collector --tail 20

# Grafana datasources
# Config in production/grafana/provisioning/datasources/
```

**Alert rules:** `production/alertmanager-rules.yml` (must be volume-mounted -- Prometheus silently loads zero rules if missing)

---

## Troubleshooting

### Service Won't Start

```bash
# Check unit file syntax
systemd-analyze verify /etc/systemd/system/indicagent-<service>.service

# Check for conflicting services
systemctl list-units --all | grep indicagent

# Check journal for errors
journalctl -u indicagent-<service> -n 50 --no-pager

# Common causes:
# - Dependency not ready (DB, Kafka)
# - Configuration error
# - Code exception
```

### Service Restart Loop

```bash
# Check how many times restarted
systemctl status indicagent-<service> | grep "Start limit"

# Reset start limit (if safe)
systemctl reset-failed indicagent-<service>
```

### Watchdog Killing Service

```bash
# Check if NotifyAccess is set
grep NotifyAccess /etc/systemd/system/indicagent-<service>.service

# Check if service is sending notifications
journalctl -u indicagent-<service> | grep WATCHDOG

# Increase WatchdogSec if needed
vim /etc/systemd/system/indicagent-<service>.service
# WatchdogSec=120
sudo systemctl daemon-reload
sudo systemctl restart indicagent-<service>
```

### Data Not Flowing

```bash
# Trace data flow through pipeline
# 1. Check IBKR provider emitting
journalctl -u indicagent-ibkr-provider --since "2 minutes ago" | grep "1m bar emitted"

# 2. Check merger routing
journalctl -u indicagent-provider-merger --since "2 minutes ago" | grep "routed"

# 3. Check pipeline processing
journalctl -u indicagent-intelligence-pipeline --since "2 minutes ago" | grep "bars processed"

# 4. Check writer persisting
journalctl -u indicagent-feature-writer --since "2 minutes ago" | grep "batch written"
```

### High Consumer Lag

```bash
# Identify lagging consumer
docker exec redpanda rpk group list
docker exec redpanda rpk group describe <group-name>

# Common causes:
# - Service crashed/stalled: check systemd status
# - DB slow: check query times in logs
# - Backlog from restart: wait for catch-up
```

### INDICAGENT_ENV Mismatch

**Symptom:** IBKR provider emits to `market.bars.raw.ibkr` but merger consumes `development.market.bars.raw.ibkr`.

**Fix:** Restart all pipeline services together after any `INDICAGENT_ENV` change.

**Diagnose:** `grep topics_consumed logs/provider_merger_agent.log`

---

## See Also

- **Foundation:** `docs/foundation/principles.md` -- Renaissance principles
- **Database:** `docs/operations/operations-database.md` -- TimescaleDB operations
- **Observability:** `docs/operations/operations-observability.md` -- Metrics, tracing, dashboards
- **Security:** `docs/operations/operations-security.md` -- Security procedures
- **Deployment:** `docs/development/setup.md` -- Initial machine setup
- **Self-healing:** `docs/architecture/self-healing.md` -- Self-healing architecture
- **Unit files:** `production/systemd/*.service` -- Service templates
