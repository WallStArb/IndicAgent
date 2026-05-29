# Systemd Supervision Architecture

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

IndicAgent uses systemd for service supervision across 43 unit files: 27 daemons, 12 oneshot timers, 4 already configured with WatchdogSec. Systemd provides process lifecycle management, dependency ordering, automatic restarts, and watchdog-based health monitoring.

**Why systemd:**
- Direct host integration (no container overhead for compute services)
- Native watchdog support for automatic restart
- Precise dependency control via `After=`/`Requires=`
- Journal-based logging aggregation
- Timer-based scheduling for batch jobs

---

## Service Types

### Daemon Services (Type=simple)

Long-running services that process Kafka streams:

```
indicagent-ibkr-provider
indicagent-provider-merger
indicagent-bar-aggregator-compute
indicagent-bar-writer
indicagent-bar-auditor
indicagent-intelligence-pipeline
indicagent-feature-writer
indicagent-signal-writer
indicagent-signal-tracker-compute
indicagent-lifecycle-writer
indicagent-signal-metrics-compute
indicagent-signal-metrics-writer
indicagent-signal-auditor
indicagent-signal-replay
indicagent-alpha-swarm
indicagent-narrative-compute
indicagent-llm-writer
indicagent-lineage-writer
indicagent-swarm-ledger-writer
indicant-graduation-compute
indicagent-graduation-writer
indicagent-feature-snapshot-writer
indicagent-parity-auditor
indicagent-service-auditor
indicagent-alerting-agent
indicagent-cross-asset
indicagent-macro-compute
indicagent-dlq-drain
```

Total: 27 daemons

### Oneshot Services (Type=oneshot)

Timer-triggered scripts that exit after completion:

```
indicagent-ml-training (nightly at 11pm)
indicagent-ml-data-quality (weekly Mon)
indicagent-ml-discovery (weekly Mon)
indicagent-ml-orchestrator (weekly Mon)
indicant-roll-batch (nightly at 8pm)
indicagent-shadow-auditor (daily)
```

Each oneshot has a corresponding `.timer` unit.

### Excluded from WatchdogSec

- `indicagent-dashboard` — Next.js has no sd_notify; `Restart=always` sufficient
- All oneshot services — WatchdogSec does not apply

---

## Unit File Pattern

### Daemon Unit Template

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

### Oneshot Unit Template

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
          /home/bg/dev/indicagent/production/scripts/<script>.py

StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicant-<job-name>
```

### Timer Unit Template

```ini
[Unit]
Description=IndicAgent <Job-Name> Timer

[Timer]
OnCalendar=*-*-* 23:00:00  # Example: nightly at 11pm
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Watchdog Integration (Phase 108)

### How It Works

1. Service calls `sd_notify("WATCHDOG=1")` every `WatchdogSec / 2` seconds
2. systemd expects notification within `WatchdogSec` seconds
3. If no notification received, systemd kills and restarts the service

### BaseAgent Implementation

`BaseAgent._watchdog_notify()` runs in a background task:

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

### Verify Watchdog is Working

```bash
# Check service has NotifyAccess
grep NotifyAccess /etc/systemd/system/indicagent-*.service

# Check watchdog pings in logs
journalctl -u indicagent-<service> | grep WATCHDOG

# Verify watchdog timeout
systemctl show indicagent-<service> -p WatchdogUSec
```

---

## Service DAG (Dependency Ordering)

Services start in dependency order defined in unit files:

**Canonical source:** `_DAG_ORDER` in `services/service_auditor_agent.py`

```
L1:  ibkr-provider, bar-replay
L2:  provider-merger
L3:  bar-aggregator, bar-auditor
L4:  bar-writer
L5:  intelligence-pipeline, cross-asset, macro-compute
L6:  feature-writer, signal-writer, signal-tracker-compute, lifecycle-writer,
     lineage-writer, ctx-writer
L7:  alpha-swarm, narrative-compute, llm-writer, swarm-ledger-writer
L8:  signal-metrics-compute, signal-metrics-writer, graduation-compute,
     graduation-writer, feature-snapshot-writer, ml-training
L9:  signal-auditor, signal-replay, parity-auditor, alerting-agent
L10: service-auditor
```

### Starting Services in Order

```bash
# Start all in correct order
sudo systemctl start indicagent-ibkr-provider
sudo systemctl start indicagent-provider-merger
sudo systemctl start indicagent-bar-aggregator-compute
sudo systemctl start indicagent-bar-auditor
sudo systemctl start indicagent-bar-writer
# ... etc
```

Or use the convenience script:

```bash
bash production/scripts/start_all_services.sh
```

---

## Service Management Commands

### Status

```bash
# Check all IndicAgent services
systemctl list-units --all | grep indicagent

# Check specific service
systemctl status indicagent-intelligence-pipeline

# Check failed services
systemctl --failed --all | grep indicagent
```

### Start/Stop/Restart

```bash
# Start
sudo systemctl start indicagent-<service>

# Stop
sudo systemctl stop indicagent-<service>

# Restart
sudo systemctl restart indicagent-<service>

# Reload (after config change)
sudo systemctl daemon-reload
sudo systemctl restart indicagent-<service>
```

### Logs

```bash
# View logs
journalctl -u indicagent-<service> -n 50

# Follow logs
journalctl -u indicagent-<service> -f

# Logs since time
journalctl -u indicagent-<service> --since "10 minutes ago"

# Logs for all indicagent services
journalctl --identifier=indicagent-* -n 100
```

### Timer Management

```bash
# List timers
systemctl list-timers --all | grep indicagent

# Check timer status
systemctl status indicagent-ml-training.timer

# Trigger timer manually
sudo systemctl start indicagent-ml-training

# View timer logs
journalctl -u indicagent-ml-training
```

---

## Environment Variables

Services read from `EnvironmentFile=/home/bg/dev/indicagent/.env`:

```bash
INDICAGENT_ENV=dev
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=gemma4:e4b
```

**Critical:** All services must have consistent `INDICAGENT_ENV`. Mismatch causes topic naming divergence and silent data flow failure.

---

## Performance Tuning

### Restart Intervals

```ini
# Auto-restart on failure
Restart=on-failure
RestartSec=10  # Wait 10s before restart

# Or exponential backoff
Restart=on-failure
RestartSec=100ms  # Start with 100ms
RestartSteps=5    # Up to 5 restarts
```

### Resource Limits (Optional)

```ini
[Service]
# Memory limit
MemoryMax=2G

# CPU limit
CPUQuota=200%

# OOM policy
OOMPolicy=continue
```

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
```

### Service Restart Loop

```bash
# Check how many times restarted
systemctl status indicagent-<service> | grep "Start limit"

# Reset start limit (if safe)
systemctl reset-failed indicagent-<service>

# Common causes:
# - Dependency not ready (DB, Kafka)
# - Configuration error
# - Code exception
```

### Watchdog Killing Service

```bash
# Check if NotifyAccess is set
grep NotifyAccess /etc/systemd/system/indicagent-<service>.service

# Check if service is actually sending notifications
journalctl -u indicagent-<service> | grep WATCHDOG

# Increase WatchdogSec if needed
# vim /etc/systemd/system/indicagent-<service>.service
# WatchdogSec=120
sudo systemctl daemon-reload
sudo systemctl restart indicagent-<service>
```

---

## File Locations

| Location | Purpose |
|----------|---------|
| `/etc/systemd/system/` | Service unit files (installed from `production/systemd/`) |
| `/etc/systemd/system/indicagent-*.timer` | Timer units for oneshot jobs |
| `/var/log/journal/` | Persistent journal storage |
| `/run/systemd/notify` | Notify socket for sd_notify |

---

## See Also

- **Self-healing:** `docs/architecture/self-healing.md`
- **Deployment:** `docs/guides/deployment.md`
- **Running services:** `docs/guides/running-services.md`
- **Infrastructure reference:** `docs/operations/infrastructure-reference.md`
- **Unit files:** `production/systemd/*.service`
