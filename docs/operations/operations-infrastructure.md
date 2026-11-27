# Infrastructure -- Systemd, Docker, and Servers

**Version:** 2.9
**Last Updated:** 2026-07-27
**Status:** current

---

## Purpose

Infrastructure operations: systemd supervision, Docker containers, deployment procedures, and server management for IndicAgent.

## Remote access (Cloudflare tunnels)

Two servers, two remotely managed tunnels named after the hostnames. Each server runs `cloudflared` from its own connector token, so ubuntu2 stays reachable when ubuntu1 is down.

| Server | Role | LAN | Tunnel | SSH hostname | Laptop alias |
|---|---|---|---|---|---|
| ubuntu1 | primary | 192.168.68.60 | ubuntu1 (`abcb8d19-...`) | ssh1.indicagent.com | ia1 |
| ubuntu2 | standby and backup | 192.168.68.65 | ubuntu2 (`ade02e25-...`) | ssh2.indicagent.com | ia2 |

Hardware (verified 2026-11-13): ubuntu1 has 64 GB RAM (59 GiB usable), 24 threads (AMD Ryzen AI 9 HX 370) and a 1.9 TB disk (1.6 TB free); numeric stack Python 3.14.4, numpy 2.4.6, scipy 1.18.1, pandas 3.1.1. ubuntu2 has 29 GiB RAM and a 914 GB disk and holds the standby, WAL-archive and base-backup duties. Postgres memory settings are sized for this box per the D-38 compose values (shared_buffers 14 GB, work_mem 256 MB, effective_cache_size 40 GB since 2026-11-14, was 17340 MB).

Ingress rules live in Cloudflare, not in `/etc/cloudflared/config.yml` (ignored for a remotely managed tunnel; ubuntu1's unit still passes it for the tunnel ID). The repo file `production/cloudflare/tunnels.yml` is the source of truth; push it with `scripts/ops/cloudflare/apply_tunnel_ingress.py` (token with Cloudflare Tunnel Edit in `~/.cloudflare/api_token`). Do not edit rules in the dashboard by hand, or the next apply overwrites them. Web hostnames (grafana, api, dash) are services and keep their names. Laptop `~/.ssh/config`: `Host ia1` / `HostName ssh1.indicagent.com` / `ProxyCommand cloudflared access ssh --hostname %h`, and the same for `ia2` with `ssh2`. On a promotion, update the roles line in `CLAUDE.md` and this table.

---

## Architecture

IndicAgent runs on a single server (`192.168.68.60`, a fixed address set in netplan since the
2026-11-12 move to the new server; the previous server, now the standby and backup at `192.168.68.65`, was `.53` until the
2026-09-23 power outage) with:

- **Services:** systemd-managed daemons (24 service units) + oneshot timers (9)
- **Infrastructure:** Docker containers (TimescaleDB, Redpanda, observability stack)
- **Supervision:** systemd with watchdog integration (Phase 108)
- **Telemetry:** OTel push-based to Collector, Prometheus scrape, Grafana dashboards

**Dormant streaming block is KEEP (owner decision 2026-11-01, todo 579):** `bar_auditor`,
`bar_replay_provider` and `bar_aggregator` stay installed with their units
disabled. The real-time feed is down and today's data arrives by nightly batch, but the feed
returns: Alpaca is the streaming candidate and the endgame is real-time trading, so this block
is the eventual real-time path, not dead weight. `bar_writer` was deleted (2026-11-14, todo 614 row 7): it wrote 1m rows to canonical past raw (law 528) and 1m left canonical at step 7 (2026-11-16), so a returning feed persists through the raw ingress, not a Kafka-to-canonical writer. Do not retire the rest in cleanup passes; audits
that flag it as dormant should close on this note. Reactivation on feed return: enable the
remaining units in wave order (`systemctl start indicagent-bar-replay
indicagent-bar-aggregator indicagent-bar-auditor`), verify bars flow to `market.bars` topics and
the aggregator's HTF output, and re-check `_DAG_ORDER` lag thresholds.

**Streaming feature writer is disabled and has no table (todo 584 item 3, 2026-11-04):**
the retired feature-vector writer persists the legacy v1 FeatureVector contract, and migration
570 dropped the only table that matched it; `feature_vectors` is now the kernel-registry table
the rebuild writer fills through `bulk_load`. Its former producer, `feature_vector_pipeline`, computed
with the v2.x feature factory, not the kernels (deleted in R2 item 5b). On feed return it
first needs a producer that emits kernel outputs and a writer
that persists them through `FEATURE_VECTORS_COLUMNS` and `feature_vector_row_values`.

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
SyslogIdentifier=indicagent-<job-name>
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
    indicagent-redpanda-ready, indicagent-redpanda-watchdog,
    indicagent-timescaledb-ready, indicagent-infrastructure.target

L1  Data ingestion
    indicagent-bar-replay

L2  Stream routing
    indicagent-provider-merger

L3  Bar processing
    indicagent-bar-aggregator, indicagent-bar-auditor

L5  Compute pipeline

L6  Persistence writers

L7  Oneshot analytics (timers or fetcher-triggered; inactive between runs is correct)
    indicagent-feature-parity-auditor, indicagent-ic-measure,
    indicagent-feature-lifecycle, indicagent-bar-derivation,
    indicagent-economic-series-writer, indicagent-bar-reconciliation-audit,
    indicagent-research-ledger-render

L8  Audit, parity, alerting, config, self-healing
    indicagent-alerting-agent, indicagent-dlq-drain,
    indicagent-compression-auditor, indicagent-config-service,
    indicagent-outbox-dispatcher, indicagent-self-healing-agent

L9  Top-level
    indicagent-api, indicagent-dashboard

L10 Meta
    indicagent-service-auditor
```

**Priority:** Lower number = restarts first during graduated response.

### Manual/on-demand batch services (no systemd timer)

Some batch services are deliberately not in `_DAG_ORDER` above and have no systemd unit or timer, for example `tag_calibrator.py`. `services/cross_sectional_spread_tracker.py` was deleted in 186-19 (as were `alpha_scorer.py` and `counterfactual_tracker.py`); the long-short construction role is the research package's R1 rule, and the decile spec is in `docs/research/summary-cards/legacy-ctf-momentum-decile-ls.md`.

### Split feed auditor (daily, todo 649)

`indicagent-split-feed-auditor.timer` (07:45 UTC, after the Alpaca nightly) runs `services/split_feed_auditor.py`: one read of the Alpaca corporate-actions feed (forward and reverse splits, ex-dates in the last `infra.split_feed_auditor.lookback_days`), active names only. A split with a matching `corporate_action_current` row is recorded. One without a row but with a matching restatement flag, inside `row_grace_days`, is a candidate: the warning `split_feed_auditor.candidates_written` and a row in `logs/split_candidates/split_candidates_<date>.csv` (the `calendar_market` row format; the Yahoo witness, review and apply stay manual). One with no row and no matching flag, or with no row past the grace, fails the unit (exit 1). A feed error or an unreadable payload also fails it. It never writes `corporate_action`. APR keys `infra.split_feed_auditor.*` (migration 612).

### Regime coverage auditor (nightly canary)

`indicagent-regime-coverage-auditor.timer` (02:00) runs `services/regime_coverage_auditor.py`, which
lists the symbols whose `feature_vectors.regime` is 100% NULL. The unit fails only on a gap that is
not registered, or whose registration has expired. Registered gaps live in APR key
`alpha.regime.coverage_auditor.known_exceptions`, a JSON list of `{symbol, kind, reason, clears_on,
expires, todo}`. `kind` is `rebuild_pending` (needs `expires` and `clears_on`, the trigger that ends
it, for example `186-26 rebuild`) or `permanent_degenerate` (a reason, no expiry; capped by
`alpha.regime.coverage_auditor.max_permanent_exceptions` and listed in the log on every run).
Gauges `regime_coverage_auditor_exceptions_live` and `regime_coverage_auditor_days_to_earliest_expiry`
carry the unexpired count and the days left.

An exception means a diagnosed, expected gap (history shorter than the walk-forward warmup, a
degenerate fit). An operator adds one only after classifying the symbol with
`scripts/infrastructure/features_regime_kernel_coverage_sweep.py` (read-only), recording the todo
that tracks it. Every entry carries an `expires` date (ISO), a review date: renew it with a fresh
diagnosis or remove it, because an expired entry fails the job again. A listed symbol that is no
longer a gap logs `regime_coverage_auditor.stale_exception` and does not fail; remove it. A
malformed list (missing symbol, reason or expires, an unparseable date, a duplicate symbol) fails
the job with status `failure`. Change the list through `config_state` with a `config_history` row
(the `/config/parameters` page, or a migration).

### Service Management

```bash
# All services at a glance
systemctl list-units --all | grep indicagent

# Single service status

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

## Host kernel tunables

Host sysctls live in `/etc/sysctl.d/99-indicagent.conf` on each server (not in the repo); a rebuilt host must reproduce these values. Memory-related lines on ubuntu1 (verified 2026-11-14): `vm.dirty_background_bytes = 1073741824`, `vm.dirty_bytes = 4294967296`, `vm.max_map_count = 1048576` and `vm.swappiness = 10` (added 2026-11-14; the Ubuntu default of 60 had pushed 4 of 8 GB of idle pages, including dormant redpanda, into swap while 36 GiB of RAM was available; `sudo sysctl -p /etc/sysctl.d/99-indicagent.conf` applies it, no reboot). Pending, scheduled by the lead after step 7: huge pages for `shared_buffers`, runbook `docs/operations/massive-step7-runbook.md` Part G.

## Host thermal cap

ubuntu1 is a mini PC whose SODIMMs share the CPU's heat path. On 2026-11-23 a one-hour 16-worker run held the CPU at 89 to 93 C (its daily maximum was 92 to 93 C on every heavy day of the previous 11) and both DIMM sensors (`spd5118`, max 55 C, critical 85 C) read 114 to 118 C. Memory corrupted at 19:01 EST and the counted runs died; the data scan was clean, so the damage was in memory only. The DIMMs fell to 54 C ten minutes after the load stopped.

The cap lives in `production/systemd/indicagent-host-thermal-cap.service` (oneshot, runs as root): boost off (`/sys/devices/system/cpu/cpufreq/boost` = 0), governor `powersave` (amd_pstate active mode offers only the `performance` preference under the `performance` governor) and `energy_performance_preference` = `balance_performance` on every policy. Raise the cap to `balance_power` only if a measured run still holds a DIMM above 85 C.

Install (ubuntu1 only): `sudo cp production/systemd/indicagent-host-thermal-cap.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now indicagent-host-thermal-cap.service`.

Rollback, live and persistent: `sudo systemctl disable --now indicagent-host-thermal-cap.service` (ExecStopPost restores boost 1 and the `performance` governor, which was the governor before the cap).

Worker count: counted and battery runs use 4 workers until a run at that setting holds both DIMM sensors under 85 C for its whole duration (samples in `logs/family10_dimm_temp.log` while the watchdog runs); only then raise to 8. Never 16.

## Host memory budget

ubuntu1 has 59.4 GiB of RAM (24 threads). Each heavy run reports its own peak: guarded launchers and `tools/run_resource.sh` run the job in a transient user scope and, at exit, read the scope's `memory.peak`, `memory.swap.peak`, `oom_kill` and leftover processes from the cgroup (todo 681). The peak includes page cache, so it is an upper bound on resident need. Read it in the status line (`run_resource workload=... memory_peak_gib=...` in `logs/family10_run_status.txt`), in `/var/lib/node-exporter-textfile/run_resource_<workload>_<stage>.prom`, or on the operations dashboard. A launcher with several jobs reports the running maximum of its scope, so the first stage's peak is exact and later stages are upper bounds.

Measured 2026-11-27, host at rest (`docker stats`, `pg_settings`, `free -g`):

| Component | Measured | Note |
|---|---|---|
| Postgres container (`timescaledb`) | 15.8 GiB resident | `shared_buffers` is 14.0 GiB (1835008 pages of 8 kB), `work_mem` 256 MB per sort or hash node, `max_connections` 200, `maintenance_work_mem` 2 GiB |
| Other containers (eleven) | 1.2 GiB together | redpanda 182 MiB of its 6 GiB `mem_limit`; one of the eleven is the sibling project's `ssfi-timescaledb` (259 MiB), which is not in `production/docker-compose.yml` |
| Kernel, OS, page cache | not budgeted | `free` showed 47 GiB buff/cache and 39 GiB available at the same time, so cache yields to jobs |
| One heavy compute job (4 workers) | pending the first runs | the repilot's pilot and the `ic_measure` run give the first real peaks; the per-worker slope needs one 8-worker run, which the owner allows only after a run holds both DIMM sensors under 85 C |
| One I/O-only transfer | pending the first run | |
| Headroom | pending | |

Instrument checks so far, not budget rows: a 300 MiB allocation that SIGKILLed itself left a 0.31 GiB peak and exit 137 through the wrapper; a real wrapped `pytest` of `tests/unit/test_run_resource.py` peaked at 0.07 GiB.

What the numbers allow today: the always-on components measured above sum to 17.0 GiB, so at most 42.4 GiB of the 59.4 GiB remains for the kernel and one job. That figure overstates the room: Postgres' resident size already contains its 14 GiB of `shared_buffers`, which `free` also counts in buff/cache and shared, and MemAvailable at rest read 38.8 to 40.7 GiB, at or just under the 40 GiB floor, with 1.4 of 8 GiB of swap in use. The launch floor therefore sits at the host's resting MemAvailable: every heavy launch has near-zero margin until the floor is revisited from the measured peaks. The launch gate `MEM_FLOOR_KB` (40 GiB of MemAvailable, `guarded_run_common.sh`) stays as it is until the measured peaks exist. When the pilot, `stage_1d`, the IC measure, a battery block and the unit suite each have one recorded peak, this section gets the derived launch floor, a ruled `MemoryMax` for the APR key, and the floor change if the measurements call for one (a part B style edit with its own gates).

## Docker Infrastructure

### Containers

| Container | Port(s) | Purpose |
|-----------|---------|---------|
| `timescaledb` | `:5432` | TimescaleDB database |
| `redpanda` | `:19092` (Kafka), `:8081` (admin) | Kafka-compatible message broker |
| `otel-collector` | `:4317` (gRPC), `:4318` (HTTP), `:8889` (Prometheus) | Central telemetry hub |
| `indicagent-prometheus` | `:9090` | Metrics scrape and alert evaluation |
| `indicagent-grafana` | `:3001` | Dashboards |
| `indicagent-loki` | `:3100` | Log aggregation |
| `indicagent-tempo` | `:3200` (HTTP), `:4317` (OTLP) | Distributed traces |
| `indicagent-alertmanager` | `:9093` | Alert routing |
| `indicagent-node-exporter` | `:9100` | Host metrics |
| `indicagent-postgres-exporter` | `:9187` | Database metrics |
| `indicagent-postgres-exporter-tables` | per-table metrics | Table-level database metrics |

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

# Verify migration state (no version table exists; probe an object a recent migration created)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT to_regclass('public.ohlcv_revision');"

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
   # L1-L4: ingestion and bar persistence first
   sudo systemctl restart indicagent-provider-merger \
                       indicagent-bar-aggregator
   sleep 10

   # L5-L6: compute and writers
   sleep 10

   # L9: top-level
   sudo systemctl restart indicagent-api

   # L10: service auditor last
   sudo systemctl restart indicagent-service-auditor
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
# Trace data flow through the bar path (the streaming path is dormant; for batch runs,
# check the writer and derivation logs instead)
# 1. Check the provider emitting (no live provider exists; the IBKR provider was removed 2026-11-13)

# 2. Check merger routing
journalctl -u indicagent-provider-merger --since "2 minutes ago" | grep "routed"

# 3. Check pipeline processing

# 4. Check writer persisting
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
- **Self-healing:** `docs/platform/platform-self-healing.md` -- Self-healing architecture
- **Unit files:** `production/systemd/*.service` -- Service templates
