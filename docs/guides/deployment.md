# Production Deployment Guide

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

This guide covers production deployment procedures for IndicAgent v2.8+. For initial machine setup, see `setup-new-machine.md`.

**Deployment principles:**
- All infrastructure runs in Docker (TimescaleDB, Redpanda, Ollama, observability stack)
- Services run via systemd (not Docker) for direct host integration
- Zero-downtime deployments via rolling updates where possible
- OTel signals verify deployment health

---

## Pre-Deployment Checklist

### 1. Verify Infrastructure

```bash
# Verify all containers are healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# Check OTel Collector is receiving telemetry
docker logs indicagent-otel-collector --tail 20

# Verify Prometheus is scraping
docker exec indicagent-prometheus wget -qO- http://localhost:9090/api/v1/rules
```

### 2. Verify Database

```bash
# Check DB connectivity
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"

# Verify migration version
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"
```

### 3. Verify Git State

```bash
# Ensure you're on main branch
git branch --show-current

# Verify no uncommitted changes
git status

# Pull latest
git pull origin main
```

### 4. Backup (Optional but Recommended)

```bash
# Database backup
pg_dump -U postgres -h localhost indicagent > /var/backups/indicagent/pre-deploy-$(date +%Y%m%d-%H%M%S).sql

# Plugin state checkpoint backup
cp /tmp/plugin_states_checkpoint.json /var/backups/indicagent/plugin_states-$(date +%Y%m%d-%H%M%S).json
```

---

## Deployment: Code Update

### 1. Pull Latest Code

```bash
cd /home/bg/dev/indicagent
git fetch origin
git rebase origin/main
```

### 2. Apply Database Migrations (if any)

```bash
# Check if new migrations exist
ls -la production/migrations/ | tail

# Apply new migrations
bash production/scripts/db_migrate.sh

# Verify
bash production/scripts/db_verify.sh
```

### 3. Update Python Dependencies

```bash
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 4. Restart Services

**Rolling update (recommended):** Restart services in DAG order to minimize disruption.

```bash
# L4: Persistence layer (restart first, to handle backlog)
sudo systemctl restart indicagent-bar-writer
sudo systemctl restart indicagent-feature-writer
sudo systemctl restart indicagent-signal-writer
sudo systemctl restart indicagent-lifecycle-writer

# Wait for writers to stabilize
sleep 10

# L5: Compute layer
sudo systemctl restart indicagent-intelligence-pipeline
sudo systemctl restart indicagent-alpha-swarm
sudo systemctl restart indicagent-narrative-compute

# Wait for compute to stabilize
sleep 10

# L6-L7: Analytics and ML
sudo systemctl restart indicagent-signal-tracker-compute
sudo systemctl restart indicagent-signal-metrics-compute
sudo systemctl restart indicagent-llm-writer

# L10: Service auditor (restart last)
sudo systemctl restart indicant-service-auditor
```

**Full restart (faster downtime):**

```bash
# Stop all pipeline services
sudo systemctl stop indicagent-bar-writer \
                    indicagent-feature-writer \
                    indicagent-signal-writer \
                    indicagent-lifecycle-writer \
                    indicagent-intelligence-pipeline \
                    indicagent-signal-tracker-compute \
                    indicagent-alpha-swarm \
                    indicagent-narrative-compute \
                    indicagent-llm-writer

# Start in reverse order
sudo systemctl start indicagent-intelligence-pipeline \
                    indicagent-alpha-swarm \
                    indicagent-narrative-compute \
                    indicagent-llm-writer

sleep 5

sudo systemctl start indicagent-feature-writer \
                    indicagent-signal-writer \
                    indicagent-lifecycle-writer \
                    indicagent-signal-tracker-compute

# Service auditor last
sudo systemctl start indicagent-service-auditor
```

### 5. Update Dashboard (if applicable)

```bash
cd dashboard
npm run build
sudo systemctl restart indicagent-dashboard
```

---

## Deployment: Infrastructure Update

### Docker Compose Changes

When `production/docker-compose.yml` changes:

```bash
cd production
docker compose up -d
```

This performs a rolling update of containers with new images.

### New Container Added

```bash
cd production
docker compose pull
docker compose up -d
```

### Container Configuration Changes

```bash
# Recreate container with new config
docker compose up -d --force-recreate <container-name>
```

---

## Post-Deployment Verification

### 1. Service Health

```bash
# Check all services are active
systemctl list-units --all | grep indicagent | grep -v inactive

# Verify no services in failed state
systemctl --failed --all | grep indicagent
```

### 2. OTel Signals

```bash
# Verify services are emitting metrics
curl -s http://localhost:9090/api/v1/query?query=up | jq

# Check for recent messages
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds' | jq
```

### 3. Data Flow Verification

```bash
# Check bars are being written
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(ts) as last_bar FROM market_data_ohlcv GROUP BY symbol, tf ORDER BY last_bar DESC LIMIT 5"

# Check features are being written
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, tf, MAX(ts) as last_feature FROM intelligence_features GROUP BY symbol, tf ORDER BY last_feature DESC LIMIT 5"

# Check signals are being written
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, timeframe, MAX(fired_at) as last_signal FROM signal_ledger GROUP BY symbol, timeframe ORDER BY last_signal DESC LIMIT 5"
```

### 4. Consumer Lag

```bash
# Check for consumer lag on critical topics
docker exec redpanda rpk group describe feature_writer_group
docker exec redpanda rpk group describe signal_writer_group
```

### 5. Dashboard Verification

```bash
# Open dashboard
xdg-open http://localhost:3000

# Verify real-time updates are flowing
# Check Grafana dashboards
xdg-open http://localhost:3001
```

---

## Rollback Procedures

### Code Rollback

```bash
# Identify the commit to rollback to
git log --oneline -10

# Hard reset to previous commit
git reset --hard <commit-hash>

# Re-apply migrations if schema changed (manual rollback)
# psql -U postgres -h localhost indicagent < migration-rollback.sql

# Restart services
sudo systemctl restart indicagent-intelligence-pipeline \
                        indicagent-feature-writer \
                        indicagent-signal-writer
```

### Database Rollback

For schema changes, migrations should include rollback scripts:

```bash
# Identify current migration version
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"

# Apply rollback (if rollback script exists)
psql -U postgres -h localhost indicagent < production/migrations/rollback_<version>.sql
```

### Infrastructure Rollback

```bash
cd production
git checkout HEAD~1 production/docker-compose.yml
docker compose up -d
```

---

## Service-Specific Procedures

### IBKR Gateway Restart

```bash
# IBKR runs in Docker
docker restart ib-gateway

# Wait for connection (check logs)
docker logs ib-gateway --tail 20

# Restart provider after gateway is up
sudo systemctl restart indicagent-ibkr-provider
```

### Ollama Model Swap

```bash
# Kill services holding persistent connections
sudo systemctl stop indicagent-alpha-swarm
sudo systemctl stop indicagent-narrative-compute

# Swap model in Docker
docker exec ollama ollama pull <new-model>

# Update .env if default model changed
# vim .env
# OLLAMA_DEFAULT_MODEL=<new-model>

# Restart services
sudo systemctl start indicagent-alpha-swarm
sudo systemctl start indicagent-narrative-compute
```

### TimescaleDB Maintenance

```bash
# Enter container
docker exec -it timescaledb psql -U postgres indicagent

# Run compression
SELECT compress_chunk(show_chunks('market_data_ohlcv'));

# Run vacuum
VACUUM ANALYZE intelligence_features;

# Exit
\q
```

---

## Monitoring During Deployment

### Grafana Dashboards to Watch

1. **Service Health** — `agent_last_message_timestamp_seconds` freshness
2. **Pipeline Performance** — `bar_e2e_latency_ms` histogram
3. **Consumer Lag** — `persistence_consumer_lag_records` gauge
4. **Error Rate** — `plugin_fallbacks_total` counter rate

### Alert Channels

Ensure alerts are routing correctly:
- Alertmanager should be configured in `production/alertmanager.yml`
- Verify webhook/email/pager destinations

---

## Troubleshooting

### Services Won't Start

```bash
# Check service logs
journalctl -u indicagent-<service-name> -n 50

# Check for common issues:
# - Port already in use: lsof -i :<port>
# - DB connection: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT 1"
# - Kafka connection: docker exec redpanda rkp cluster info
```

### Data Not Flowing

```bash
# Trace data flow through pipeline
# 1. Check IBKR provider is emitting
journalctl -u indicagent-ibkr-provider --since "2 minutes ago" | grep "1m bar emitted"

# 2. Check merger is routing
journalctl -u indicagent-provider-merger --since "2 minutes ago" | grep "routed"

# 3. Check pipeline is processing
journalctl -u indicagent-intelligence-pipeline --since "2 minutes ago" | grep "bars processed"

# 4. Check writer is persisting
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

---

## See Also

- **Initial setup:** `docs/setup-new-machine.md`
- **Running services:** `docs/guides/running-services.md`
- **Database management:** `docs/guides/database-management.md`
- **Systemd supervision:** `docs/operations/systemd.md`
- **Alerting runbook:** `docs/guides/alerting-runbook.md`
- **Infrastructure reference:** `docs/operations/infrastructure-reference.md`
