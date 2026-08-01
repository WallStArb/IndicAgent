# Disaster Recovery Procedures

**Version:** 2.9
**Last Updated:** 2026-06-07

---

> **Staleness note (2026-08-01):** This runbook's table-specific backup examples target
> `signal_ledger` — an ARCHIVED v2.x table with no live consumer as of 2026-07-02 per
> CLAUDE.md. **The commands below target ARCHIVED tables — do not run against production
> without first verifying the target table still exists and is the live one** (`feature_vectors`,
> `alpha_frames`, `alpha_events` are the current equivalents). Not yet rewritten for v3.0 --
> tracked for a future doc pass, not fixed here.

## Overview

This guide covers backup and restore procedures for IndicAgent. Recovery is prioritized by criticality: DB > plugin state > Kafka > configuration.

**Backup scope:**
- TimescaleDB (market data, features, signals, LLM calls)
- Plugin state checkpoints (incremental compute state)
- Configuration files (.env, systemd units)
- Docker volumes (optional)

---

## Database Backup

### TimescaleDB Backup

**Full backup:**
```bash
# Create backup directory
mkdir -p /var/backups/indicagent

# Full dump (all tables)
PGPASSWORD=postgres pg_dump -U postgres -h localhost \
  -F c -f /var/backups/indicagent/full-$(date +%Y%m%d-%H%M%S).dump \
  indicagent

# Compress
gzip /var/backups/indicagent/full-*.dump
```

**Schema-only backup (faster, for development):**
```bash
PGPASSWORD=postgres pg_dump -U postgres -h localhost -h localhost \
  --schema-only -f /var/backups/indicagent/schema-$(date +%Y%m%d).sql \
  indicagent
```

**Table-specific backup:**
```bash
# Backup just signal_ledger
PGPASSWORD=postgres pg_dump -U postgres -h localhost \
  -t signal_ledger -f /var/backups/indicagent/signal_ledger-$(date +%Y%m%d).sql \
  indicagent
```

### Automated Backup (Systemd Timer)

**Create backup script:**
```bash
# /usr/local/bin/indicagent-backup.sh
#!/bin/bash
BACKUP_DIR=/var/backups/indicagent
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p $BACKUP_DIR

PGPASSWORD=postgres pg_dump -U postgres -h localhost \
  -F c -f $BACKUP_DIR/full-$DATE.dump indicagent

gzip $BACKUP_DIR/full-$DATE.dump

# Keep last 7 days
find $BACKUP_DIR -name "full-*.dump.gz" -mtime +7 -delete
```

**Create systemd timer:**
```ini
# /etc/systemd/system/indicagent-backup.service
[Unit]
Description=IndicAgent Database Backup

[Service]
Type=oneshot
User=bg
ExecStart=/usr/local/bin/indicagent-backup.sh

# /etc/systemd/system/indicagent-backup.timer
[Unit]
Description=Daily IndicAgent backup

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable:**
```bash
sudo systemctl enable indicagent-backup.timer
sudo systemctl start indicagent-backup.timer
```

---

## Database Restore

### Full Restore

```bash
# Stop writers first (prevent data corruption)
sudo systemctl stop indicagent-feature-writer \
                    indicagent-signal-writer \
                    indicagent-lifecycle-writer

# Drop existing database (caution!)
PGPASSWORD=postgres psql -U postgres -h localhost \
  -c "DROP DATABASE indicagent;"

# Create fresh database
PGPASSWORD=postgres psql -U postgres -h localhost \
  -c "CREATE DATABASE indicagent;"

# Restore from backup
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent -F c /var/backups/indicagent/full-YYYYMMDD-HHMMSS.dump.gz

# Restart writers
sudo systemctl start indicagent-feature-writer \
                    indicagent-signal-writer \
                    indicagent-lifecycle-writer
```

### Partial Restore (Single Table)

```bash
# Drop existing table
PGPASSWORD=postgres psql -U postgres -h localhost indicagent \
  -c "DROP TABLE IF EXISTS signal_ledger;"

# Restore single table
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent -t signal_ledger /var/backups/indicagent/full-YYYYMMDD.dump.gz
```

### Point-in-Time Recovery (Advanced)

TimescaleDB supports PITR if WAL archiving is enabled. Not covered here — see TimescaleDB docs.

---

## Plugin State Backup

Plugin state checkpoints live in `cache/pipeline_checkpoint.json` (plugin states + Kalman filter) and `cache/bar_replay_checkpoint.json` (live replay cursor). Both are relative to the repo root.

### Backup

```bash
cp cache/pipeline_checkpoint.json \
   /var/backups/indicagent/pipeline_checkpoint-$(date +%Y%m%d-%H%M%S).json
```

### Restore

```bash
# Stop services that use plugin state
sudo systemctl stop indicagent-intelligence-pipeline

# Restore checkpoint
cp /var/backups/indicagent/pipeline_checkpoint-YYYYMMDD-HHMMSS.json \
   cache/pipeline_checkpoint.json

# Restart services
sudo systemctl start indicagent-intelligence-pipeline
```

**Note:** Plugin state is not critical — delete both cache files to force a cold restart. Services rebuild Kalman/GARCH/HMM state from DB bars on the next replay.

---

## Configuration Backup

### Backup

```bash
# Backup directory
BACKUP_DIR=/var/backups/indicagent/config
mkdir -p $BACKUP_DIR

# Copy configuration files
cp .env $BACKUP_DIR/env-$(date +%Y%m%d).backup
cp -r production/systemd $BACKUP_DIR/
cp production/docker-compose.yml $BACKUP_DIR/
```

### Restore

```bash
# Stop services
sudo systemctl stop indicagent-*

# Restore .env
cp /var/backups/indicagent/config/env-YYYYMMDD.backup .env

# Restore systemd units
sudo cp /var/backups/indicagent/config/systemd/*.service \
        /etc/systemd/system/
sudo systemctl daemon-reload

# Restart services
sudo systemctl start indicagent-ibkr-provider indicagent-provider-merger indicagent-intelligence-pipeline
```

---

## Kafka Backup

Kafka is not backed up by default — it's a transport buffer, not storage. For Kafka disaster recovery:

### Topic Recreation

```bash
# Recreate all topics
python3 scripts/infrastructure/setup/infrastructure_init_kafka_topics.py
```

### Offset Reset

If consumers need to reprocess:

```bash
# Reset to earliest
docker exec redpanda rpk group reset-offset <group> --topic <topic> -to-earliest
```

---

## Disaster Scenarios

### Scenario 1: Database Corruption

**Symptoms:** Queries failing, corruption errors in logs

**Recovery:**
```bash
# 1. Stop all writers
sudo systemctl stop *-writer

# 2. Restore from last known good backup
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent /var/backups/indicagent/full-YYYYMMDD.dump.gz

# 3. Restart writers
sudo systemctl start *-writer
```

**Data loss:** Since last backup (up to 24h with daily backup).

---

### Scenario 2: Server Crash (Hardware Failure)

**Recovery on new hardware:**
```bash
# 1. Install OS and prerequisites (see setup-new-machine.md)

# 2. Clone repo
git clone git@github.com:WallStArb/IndicAgent.git /home/bg/dev/indicagent

# 3. Restore .env
cp /var/backups/indicagent/config/env.backup .env

# 4. Start infrastructure
cd production && docker compose up -d

# 5. Restore database
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent /var/backups/indicagent/full-latest.dump.gz

# 6. Restore systemd units
sudo cp /var/backups/indicagent/config/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 7. Start services
sudo systemctl start indicagent-ibkr-provider indicagent-provider-merger indicagent-intelligence-pipeline
```

---

### Scenario 3: Accidental Data Deletion

**Recovery:**
```bash
# 1. Stop writers immediately
sudo systemctl stop *-writer

# 2. Restore from backup (partial if single table)
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent -t <table> /var/backups/indicagent/full-latest.dump.gz

# 3. Restart writers
sudo systemctl start *-writer
```

---

### Scenario 4: Ransomware/Malware

**Recovery:**
```bash
# 1. Isolate infected system (disconnect network)

# 2. Wipe and reinstall OS

# 3. Restore from offline backup (external drive)

# 4. Scan restored files before use

# 5. Change all credentials
```

---

## Backup Verification

### Regular Testing

**Monthly restore test:**
```bash
# 1. Create test database
PGPASSWORD=postgres psql -U postgres -h localhost \
  -c "CREATE DATABASE indicagent_test;"

# 2. Restore to test DB
PGPASSWORD=postgres pg_restore -U postgres -h localhost \
  -d indicagent_test /var/backups/indicagent/full-latest.dump.gz

# 3. Verify data
PGPASSWORD=postgres psql -U postgres -h localhost indicagent_test \
  -c "SELECT COUNT(*) FROM signal_ledger;"

# 4. Drop test DB
PGPASSWORD=postgres psql -U postgres -h localhost \
  -c "DROP DATABASE indicagent_test;"
```

---

## Offsite Backup (Optional)

For disaster-proof backup:

### S3/Cloud Storage

```bash
# Install rclone
sudo apt install rclone

# Configure rclone
rclone config

# Sync backup directory
rclone sync /var/backups/indicagent remote:indicagent-backups
```

### rsync to Remote Host

```bash
# Sync to backup server
rsync -avz /var/backups/indicagent/ \
  user@backup-server:/backup/indicagent/
```

---

## Recovery Time Objectives (RTO)

| Component | RTO | RPO | Notes |
|-----------|-----|-----|-------|
| TimescaleDB | 1 hour | 24 hours | Daily backup, restore takes ~30min |
| Plugin state | 0 min | N/A | Auto-rebuild from DB |
| Configuration | 10 min | 1 day | Manual restore |
| Kafka | 5 min | N/A | Recreate topics, offset reset |

---

## See Also

- **Database management:** `docs/operations/operations-database.md`
- **Deployment:** `docs/operations/operations-infrastructure.md`
- **Infrastructure reference:** `docs/operations/operations-infrastructure.md`
- **Setup:** `docs/development/setup.md`
