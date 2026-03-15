# New Machine Setup: Redpanda, PostgreSQL, TimescaleDB

**Version:** 2.0.0
**Last Updated:** 2026-03-15
**Status:** Checklist for moving IndicAgent to a new machine

Use this when setting up infrastructure on a new machine. All scripts and configs referenced here live in the repo. DB and stream names below match the current codebase (`src/core/stream_keys.py`, migrations, `db_verify.sh`).

---

## 1. Prerequisites

- **Docker** (for PostgreSQL/TimescaleDB, Redpanda, and Ollama)
- **Python 3.13** and **Node 20+** (for app and dashboard)
- **psql** (PostgreSQL client) for running migrations and verify

---

## 2. Start Infrastructure (Docker Compose)

The single source of truth is `production/docker-compose.yml`. It starts TimescaleDB, Redpanda, and Ollama together:

```bash
cd /path/to/indicagent/production
docker compose up -d
```

With Docker Compose, the `indicagent` database is created automatically. Redpanda starts on ports 9092 (internal) and 19092 (external/localhost).

If you need to create the database manually:

```bash
docker exec timescaledb psql -U postgres -c "CREATE DATABASE indicagent;"
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
  # Edit .env: DATABASE_URL, KAFKA_BOOTSTRAP_SERVERS, IBKR_*, etc.
  ```

- Defaults that match the setup above:
  - `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent`
  - `KAFKA_BOOTSTRAP_SERVERS=localhost:19092`

- Install and run the app (see root [README.md](../README.md) Quick Start).

---

## Reference: What’s in the repo

| Item | Location |
|------|----------|
| Docker Compose (TimescaleDB + Redpanda + Ollama) | `production/docker-compose.yml` |
| DB migrations (run in order) | `production/migrations/001_*.sql` … `007_*.sql` |
| Single-file schema (dev reference) | `production/schemas/create_schema.sql` |
| Apply migrations | `production/scripts/db_setup.sh` |
| Verify schema | `production/scripts/db_verify.sh` |
| Dragonfly sample config | `production/config/dragonfly.conf` |
| Env template | `.env.example` (repo root) |
| Quick Start (app + dashboard) | Root `README.md` |

### Current DB tables (from migrations)

- **market_data_ohlcv** – OHLCV bars (hypertable). Used by API and cold path.
- **features**, **intelligence** – Hypertables for I1/I2 and intelligence (migrations create them; used for future/cold storage).
- **trading_signals**, **instruments** – In `schemas/create_schema.sql`; migrations may add or extend.
- **Continuous aggregates** – backtesting_data_5m, ohlcv_15m, ohlcv_1h, ohlcv_4h, ohlcv_1d (verified by `db_verify.sh`).

### Current Kafka topics (from `src/core/stream_keys.py`)

All topic names use an optional env prefix (e.g. `dev.` for development). Then:

- **market.ticks** – Live tick data from IBKR.
- **market.bars** – OHLCV bars (all timeframes; key=`SYMBOL:TF`).
- **indicators** – I1+I2 indicator output (key=`SYMBOL:TF`).
- **intelligence** – I3–I6 typed IntelligenceEvent (key=`SYMBOL:TF`).
- **signals.aggregated** – I7 selected signal (key=`SYMBOL:TF`).
- **narratives** – I8 AI narrative (key=`SYMBOL:TF`).

Redpanda creates topics automatically on first publish (auto-create enabled in docker-compose).
