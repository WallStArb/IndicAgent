---
phase: 260528-9at-add-docker-healthchecks-timescaledb-redpanda
plan: 01
status: complete
completed: 2026-05-28
commit: 15697ad8
---

# Summary: Add Docker Healthchecks for TimescaleDB and Redpanda

Added `healthcheck` blocks to both services in `production/docker-compose.yml` in commit `15697ad8`.

## Changes

- **TimescaleDB**: `pg_isready -U postgres -d indicagent`, 10s interval, 5s timeout, 3 retries, 30s start_period
- **Redpanda**: `rpk cluster info`, same cadence

## Effect

Enables `docker inspect --format='{{.State.Health.Status}}'` for monitoring integration. Containers report `healthy`/`unhealthy` state to Docker engine, enabling dependent-service startup ordering and automated recovery signals.
