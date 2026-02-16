# New Machine Setup: Redis, PostgreSQL, TimescaleDB

**Version:** 1.0.0  
**Last Updated:** 2026-02-13  
**Status:** Checklist for moving IndicAgent to a new machine

Use this when setting up infrastructure on a new machine. All scripts and configs referenced here live in the repo. DB and stream names below match the current codebase (`src/core/stream_keys.py`, migrations, `db_verify.sh`).

---

## 1. Prerequisites

- **Docker** (for PostgreSQL/TimescaleDB and Dragonfly)
- **Python 3.13** and **Node 20+** (for app and dashboard)
- **psql** (PostgreSQL client) for running migrations and verify

---

## 2. Start Redis (Dragonfly)

Dragonfly is Redis-compatible. Either use Docker Compose (recommended) or a single container.

**Option A – Docker Compose (TimescaleDB + Dragonfly together):**

```bash
cd /path/to/indicagent/production
docker compose up -d
```

**Option B – Standalone containers (from repo root):**

```bash
# Dragonfly (Redis-compatible) on port 6379
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly

# TimescaleDB on port 5432 (see step 3)
docker run -d --name timescaledb -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15
```

With Docker Compose, the `indicagent` database is created automatically. With standalone TimescaleDB, create it once:

```bash
psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE indicagent;"
```

---

## 3. PostgreSQL + TimescaleDB

**If using Docker Compose (step 2 Option A):** TimescaleDB is already running with `POSTGRES_DB=indicagent`. Skip to step 4.

**If using standalone container:** After creating the `indicagent` database (see above), continue to step 4.

**Connection:** `postgresql://postgres:postgres@localhost:5432/indicagent`

---

## 4. Apply database migrations

Migrations are in `production/migrations/` and must be run in order. The setup script applies them all.

```bash
cd /path/to/indicagent

export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
bash production/scripts/db_setup.sh
```

If you prefer not to set `DATABASE_URL`, the script defaults to the URL above.

---

## 5. Verify schema

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
bash production/scripts/db_verify.sh
```

You should see checks for tables, indexes, hypertables, and continuous aggregates.

---

## 6. Environment and app

- Copy the env template and fill in values (especially if different from defaults):

  ```bash
  cp .env.example .env
  # Edit .env: DATABASE_URL, REDIS_URL, IBKR_*, etc.
  ```

- Defaults that match the setup above:
  - `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent`
  - `REDIS_URL=redis://localhost:6379/0`

- Install and run the app (see root [README.md](../README.md) Quick Start).

---

## Reference: What’s in the repo

| Item | Location |
|------|----------|
| Docker Compose (TimescaleDB + Dragonfly + Ollama) | `production/docker-compose.yml` |
| DB migrations (run in order) | `production/migrations/001_*.sql` … `006_*.sql` |
| Single-file schema (dev reference) | `production/schemas/create_schema.sql` |
| Apply migrations | `production/scripts/db_setup.sh` |
| Verify schema | `production/scripts/db_verify.sh` |
| Dragonfly sample config | `production/config/dragonfly.conf` |
| Env template | `.env.example` (repo root) |
| Quick Start (app + dashboard) | Root `README.md` |

### Current DB tables (from migrations)

- **market_data_ohlcv** – OHLCV bars (hypertable). Used by API and cold path.
- **technical_indicators** – Indicator values (hypertable).
- **features**, **intelligence** – Hypertables for I1/I2 and intelligence (migrations create them; used for future/cold storage).
- **trading_signals**, **instruments** – In `schemas/create_schema.sql`; migrations may add or extend.
- **Continuous aggregates** – backtesting_data_5m, ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d (verified by `db_verify.sh`).

### Current Redis streams (from `src/core/stream_keys.py`)

All stream names use an optional env prefix (e.g. `development:` or empty). Then:

- **ticks:SYMBOL:live** – Live tick data from IBKR.
- **market:SYMBOL:TIMEFRAME** – OHLCV bars (1m, 5m, 15m, 1h, 4h, 1d).
- **indicators:SYMBOL:TIMEFRAME** – I1 indicator output.
- **intelligence:SYMBOL:TIMEFRAME** – I3/I4/I5 plugin output.

No Redis schema or DB creation is required for streams; services create consumer groups as needed.

---

## Optional: Dragonfly with custom config

To use the sample config (e.g. persistence):

```bash
docker run -d --name dragonfly -p 6379:6379 \
  -v /path/to/indicagent/production/config/dragonfly.conf:/etc/dragonfly.conf \
  docker.dragonflydb.io/dragonflydb/dragonfly \
  --redis-compatible yes --appendonly yes --dir /data --dbfilename dump.aof
```

Adjust the volume path to your repo location.
