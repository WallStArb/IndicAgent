# Alerting Runbook

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

This runbook documents the standard operating procedures for responding to Grafana alerts. All alerts fire from Prometheus metrics collected via OTel.

**Alert severity levels:**
- **critical** — Immediate action required, service is down
- **warning** — Investigation required, degraded performance
- **info** — Informational, no immediate action

---

## Critical Alerts

### Service Stall — `agent_last_message_timestamp_seconds` stale > 120s

**Symptoms:**
- Service not processing messages
- Grafana shows stale timestamp for service
- Dashboard not updating

**Diagnosis:**
```bash
# Check service status
systemctl status indicagent-<service-name>

# Check service logs for errors
journalctl -u indicagent-<service-name> -n 50

# Verify consumer is not stuck
docker exec redpanda rpk group describe <consumer-group>
```

**Resolution:**
```bash
# If service is in failed state
sudo systemctl restart indicagent-<service-name>

# If service is active but stalled (should auto-restart via watchdog)
sudo systemctl restart indicagent-<service-name>

# Verify recovery
journalctl -u indicagent-<service-name> -f
```

**Prevention:**
- ServiceAuditor should auto-restart stalled services
- systemd watchdog should auto-restart at 60s mark
- Check `consumer_stall_detected_total` counter in Grafana

---

### API Health Down — `api_health{service="indicagent-api"}` < 1

**Symptoms:**
- API not responding
- Dashboard cannot fetch data
- `/health/database` endpoint returning 503

**Diagnosis:**
```bash
# Check API is running
systemctl status indicagent-api

# Check database connectivity from API host
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"

# Check API logs
journalctl -u indicagent-api -n 50
```

**Resolution:**
```bash
# If DB is down, fix DB first
docker ps | grep timescaledb

# If API crashed, restart
sudo systemctl restart indicagent-api

# Verify health endpoint
curl http://localhost:8000/health/database
```

**Prevention:**
- Monitor TimescaleDB container health
- Check database connection pool exhaustion

---

### Bars Processing Rate Drop — `rate(bars_processed_total[5m])` down > 50%

**Symptoms:**
- Pipeline throughput significantly degraded
- Latency increasing across all tiers
- Possible bottleneck in I2-I6 sequential tiers

**Diagnosis:**
```bash
# Check pipeline latency
curl -s 'http://localhost:9090/api/v1/query?query=rate(bar_e2e_latency_ms_sum[5m])' | jq

# Check which tier is slow (grep logs for timing)
journalctl -u indicagent-intelligence-pipeline --since "2 minutes ago" | grep "Pipeline latency"

# Check for stuck plugins (circuit breaker open)
curl -s 'http://localhost:9090/api/v1/query?query=intelligence_pipeline_plugin_cb_state' | jq
```

**Resolution:**
```bash
# If circuit breaker open, investigate plugin error
journalctl -u indicagent-intelligence-pipeline --since "10 minutes ago" | grep "cb_open"

# Restart pipeline to clear stuck state
sudo systemctl restart indicagent-intelligence-pipeline

# If chronic I2-I6 slowness, this is known bottleneck
# See docs/architecture/pipeline-optimization.md for planned batch processing fix
```

**Prevention:**
- Monitor plugin execution times per tier
- Planned batch processing will address sequential tier bottleneck

---

## Warning Alerts

### Watchdog Suppression — `rate(watchdog_notify_suppressed_total[5m])` > 0

**Symptoms:**
- `sd_notify()` calls failing
- Systemd not receiving watchdog pings
- Service will be killed after WatchdogSec timeout

**Diagnosis:**
```bash
# Check systemd unit file for NotifyAccess
grep NotifyAccess /etc/systemd/system/indicagent-<service-name>.service

# Should be:
# [Service]
# NotifyAccess=main
```

**Resolution:**
```bash
# Add NotifyAccess=main to unit file
sudo vim /etc/systemd/system/indicagent-<service-name>.service
# Add: NotifyAccess=main under [Service]

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart indicagent-<service-name>
```

**Prevention:**
- All services should have `NotifyAccess=main` in unit files
- Verify after adding new services

---

### DLQ Quarantine — `rate(dlq_quarantine_total[5m])` > 0

**Symptoms:**
- Poison pill detected
- Same error occurring 3+ times in 24h for same (agent, source_topic, error_type)
- Messages being quarantined instead of retried

**Diagnosis:**
```bash
# Check DLQ for quarantined messages
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT agent, source_topic, error_type, COUNT(*) FROM dlq_events WHERE quarantined=TRUE GROUP BY agent, source_topic, error_type"

# Check recent DLQ messages
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT * FROM dlq_events WHERE quarantined=TRUE ORDER BY routed_at DESC LIMIT 10"
```

**Resolution:**
```bash
# Identify root cause from error_type and error_message
# Common causes:
# - Schema change: fix producer/consumer schema
# - Data quality issue: fix upstream validation
# - DB constraint: fix data or constraint

# After fix, unquarantine if needed
UPDATE dlq_events SET quarantined=FALSE WHERE id=<id>;

# Restart DLQ drain to re-process
sudo systemctl restart indicagent-dlj-drain
```

**Prevention:**
- Validate schema changes before deployment
- Add input validation for new data sources

---

### High Consumer Lag — `persistence_consumer_lag_records{agent_id="..."}` > 1000

**Symptoms:**
- Writer not keeping up with message rate
- Possible DB slow or writer issue
- Data processing backlog growing

**Diagnosis:**
```bash
# Check writer is running
systemctl status indicant-<writer-name>

# Check DB batch latency
curl -s 'http://localhost:9090/api/v1/query?query=rate(persistence_batch_latency_seconds_sum[5m])' | jq

# Check DB performance
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT now(), query, state, wait_event_type FROM pg_stat_activity WHERE state != 'idle'"

# Check for long-running queries
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT pid, now() - query_start as duration, query FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC LIMIT 10"
```

**Resolution:**
```bash
# If DB is slow, investigate long-running queries
# Cancel long-running queries if safe
SELECT pg_cancel_backend(<pid>);

# If writer crashed, restart
sudo systemctl restart indicant-<writer-name>

# If chronic lag, consider:
# - Increasing writer batch size
# - Adding writer instances (consumer group scaling)
# - DB optimization (indexes, compression)
```

**Prevention:**
- Monitor DB query times
- Regular vacuum and compression
- Appropriate indexes on hot tables

---

### Oneshot Failure — `job_completed_total{status="failure"}` increment

**Symptoms:**
- Timer-triggered job failed
- ml-training, roll-batch, or shadow-auditor failed

**Diagnosis:**
```bash
# Check job logs
journalctl -u indicant-<job-name> -n 100

# Check timer status
systemctl list-timers --all | grep <job-name>
```

**Resolution:**
```bash
# Fix error based on logs
# Common causes:
# - DB connection issue: fix DB
# - Missing data: fix upstream
# - Code bug: fix and redeploy

# Re-run manually if needed
sudo systemctl start indicant-<job-name>
```

**Prevention:**
- Test oneshot scripts in development
- Validate prerequisites (data, DB) before run

---

## Info Alerts

### High Plugin Execution Time — `plugin_execution_seconds` p95 > threshold

**Symptoms:**
- Plugin slower than usual
- Possible performance regression

**Diagnosis:**
```bash
# Identify slow plugin in Grafana dashboard
# Check plugin logs for errors
journalctl -u indicagent-intelligence-pipeline | grep <plugin-name>
```

**Resolution:**
```bash
# If plugin error, fix bug
# If plugin compute-bound, consider optimization
# See docs/architecture/pipeline-optimization.md
```

**Prevention:**
- Profile plugins before deployment
- Monitor plugin execution times

---

## Escalation Procedures

### When to Escalate

**Immediate escalation (page):**
- Multiple critical alerts simultaneously
- Service down for > 5 minutes
- Data loss suspected

**Standard escalation (email):**
- Warning alerts not resolved in 1 hour
- Recurring issues needing investigation

### Escalation Contacts

| Role | Contact | Responsibility |
|------|---------|----------------|
| Platform Owner | <owner> | Final decision maker |
| On-Call Engineer | <oncall> | First responder |

---

## Alert Maintenance

### Adding New Alerts

1. Define alert rule in `production/alertmanager-rules.yml`
2. Add documentation to this runbook
3. Test alert with trigger condition
4. Verify notification routing

### Modifying Existing Alerts

1. Update rule in `production/alertmanager-rules.yml`
2. Update documentation in this runbook
3. Reload Prometheus: `docker exec indicagent-prometheus kill -HUP 1`
4. Verify new rule loaded: `curl http://localhost:9090/api/v1/rules`

---

## See Also

- **Self-healing architecture:** `docs/architecture/self-healing.md`
- **Observability:** `docs/platform/platform-observability.md`
- **Grafana dashboards:** `docs/operations/operations-observability.md`
- **Deployment:** `docs/operations/operations-infrastructure.md`
- **Troubleshooting:** `docs/operations/operations-infrastructure.md`
