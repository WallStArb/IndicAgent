# IndicAgent Production DB and Infra

**Version:** 2.3.0  
**Last Updated:** 2026-02-12  
**Status:** Current

Database, migrations, and infrastructure for IndicAgent. For the full list of runtime services (indicator-processor, timeframe-builder, intelligence-processor, coordination, etc.), see the root [README.md](../README.md) and [services/README.md](../services/README.md).

## Structure
- `migrations/`: Authoritative SQL migrations (run in order)
- `schemas/`: Dev convenience schema (aligned with migrations)
- `scripts/`: DB setup and verification helpers
- `config/`: Infra configs (e.g., Dragonfly)

## Usage
1. Apply all migrations
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent \
bash scripts/infrastructure/setup/infrastructure_db_setup.sh
```

2. Verify schema
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent \
bash scripts/debug/validate/debug_db_verify.sh
```

3. Start databases with Docker Compose
```bash
cd production
docker compose up -d

# TimescaleDB: postgres://postgres:postgres@localhost:5432/indicagent
# Dragonfly:   redis://localhost:6379
```

## Runtime (systemd services)

Core services are managed by systemd (see `services/`):
- `indicagent-backend-api.service` (FastAPI, port 8000)
- `indicagent-websocket.service` (Socket.IO, port 8001)
- `indicagent-hf-tws.service` (IBKR high-frequency daemon)

Install and start:
```bash
sudo cp /home/bg/projects/indicagent/services/indicagent-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-backend-api indicagent-websocket indicagent-hf-tws
sudo systemctl start indicagent-backend-api indicagent-websocket indicagent-hf-tws
```

## Dragonfly (Redis-compatible)
- Sample config: `production/config/dragonfly.conf`
- Start (example):
```bash
docker run -d --name dragonfly -p 6379:6379 \
  -v $PWD/production/config/dragonfly.conf:/etc/dragonfly.conf \
  docker.dragonflydb.io/dragonflydb/dragonfly \
  --redis-compatible yes --appendonly yes --dir /data --dbfilename dump.aof
```

Adjust flags to your environment.

