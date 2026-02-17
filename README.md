# IndicAgent Trading Intelligence Platform

**Version:** 2.8.0  
**Last Updated:** 2026-02-12  
**Status:** I3 Structure + I4 Context + I5 Pattern Detection Complete

---

## What It Is

IndicAgent turns **live futures data** into **structured market intelligence** in real time. It ingests ticks from Interactive Brokers, builds bars and technical indicators, then runs a plugin-based pipeline that adds **market structure** (swings, support/resistance), **context** (volatility and trend regime), and **pattern detection** (divergence, squeeze, confluence). Results are published to Redis Streams and served to a live dashboard or downstream systems. The database is used for history and backtesting, not the real-time path, so latency stays low.

**In one sentence:** A production-ready, plugin-native platform that turns IBKR futures ticks into real-time indicators, structure, context, and patterns over Redis Streams, with a Next.js dashboard and a clear path to confluence scoring and AI-derived insights.

---

## At a Glance

| Aspect | Detail |
|--------|--------|
| **Data in** | IBKR TWS (ES, NQ, RTY, CL, GC, etc.), 100–500+ ticks/sec |
| **Data out** | Redis Streams (bars, indicators, structure, context, patterns); optional TimescaleDB for history |
| **Intelligence** | 22 plugins: 12 indicators (I1), 3 structure (I3), 3 context (I4), 4 patterns (I5). I6–I8 planned. |
| **Stack** | Python 3.13, FastAPI, LangGraph, DragonflyDB/Redis, TimescaleDB, Next.js 15 / React 19 |
| **Deployment** | Small independent services over streams; SSE or Socket.IO for the dashboard |

---

## How It Works

1. **Ingestion** – A daemon connects to IBKR TWS and publishes ticks and 1m bars to DragonflyDB (or Redis) streams.
2. **Processing** – Separate services consume those streams: one builds multi-timeframe bars (1m→5m→15m→1h→4h→1d), another computes technical indicators (with incremental math for speed), and the intelligence service runs I3/I4/I5 plugins (structure, context, patterns) on each bar.
3. **Distribution** – Results are written back to streams. The API and optional Socket.IO server expose them; the dashboard subscribes via SSE or WebSocket.
4. **Storage** – Persistence to PostgreSQL/TimescaleDB is off the hot path and used for cold storage and historical context.

So: **ticks → bars → indicators → structure/context/patterns → streams → dashboard (or your own consumer)**. No database in the live pipeline.

---

## Architecture

### Services (Microservices over Streams)

Services are independent processes that communicate only via Redis Streams:

| Role | Component | Notes |
|------|-----------|--------|
| Data collection | `high_frequency_tws_daemon.py` | IBKR live ticks and 1m bars |
| Indicators | `indicators_processor_service.py`, `indicators_enhanced_service.py` | Bar→indicators; enhanced = 141x faster incremental |
| Intelligence | `intelligence_processor_service.py` | I3/I4/I5 plugin orchestration |
| Timeframes | `timeframes_builder_service.py` | 1m→5m→15m→1h→4h→1d |
| Coordination | `coordination_parallel_service.py` | Parallel stream consumption |
| API | `src/api/main.py` | FastAPI, health, SSE, REST |
| Dashboard | `dashboard/` | Next.js 15 / React 19, SSE or Socket.IO |

Scaling, deployment, and fault isolation are per service; there are no direct service-to-service HTTP calls in the pipeline.

### Four Major Layers

The system is structured as four conceptual layers:

| Layer | Name | Contents | Status |
|-------|------|----------|--------|
| **1** | Data Foundation | Ingestion (IBKR), bar building, multi-timeframe aggregation, stream distribution | Operational |
| **2** | Mathematical Intelligence (I1–I4) | Indicators, composites, market structure, context/regime | Operational |
| **3** | Pattern Intelligence (I5–I7) | Pattern detection, confluence, trading outputs | I5 operational; I6–I7 next/planned |
| **4** | AI Intelligence (I8) | LLM synthesis, narratives, cost-controlled AI | Planned |

Layer 1 feeds Layer 2; Layer 2 feeds Layer 3; Layer 3 feeds Layer 4. Each layer adds context on top of the previous one.

### Intelligence Tiers (I1–I8)

I1–I8 are the tiers inside layers 2–4. Lower tiers feed into higher ones.

| Tier | Name | Purpose | Status |
|------|------|---------|--------|
| **I1** | Raw indicators | RSI, MACD, SMA, EMA, ATR, BB, OBV, VWAP, etc. (12 plugins) | Operational |
| **I2** | Composites | Crossovers, slopes, distances | Operational (composites/) |
| **I3** | Market structure | Swings (HH/HL/LH/LL), support/resistance, trend structure (3 plugins) | Operational |
| **I4** | Context | Volatility regime, trend regime, momentum context (3 plugins) | Operational |
| **I5** | Patterns | RSI divergence, Bollinger squeeze, volume divergence, confluence (4 plugins) | Operational |
| **I6** | Confluence & risk | Multi-factor scoring from I3+I4+I5 | Next |
| **I7** | Trading outputs | Setups, signals | Planned |
| **I8** | AI intelligence | LLM synthesis, narratives | Planned |

So today the platform is **data + I1–I5**; I6–I8 are the roadmap.

### Data Path: Hot / Warm / Cold

- **Hot** – Ticks and bars stay in DragonflyDB/Redis streams; sub-ms writes, no DB.
- **Warm** – Services read from streams, compute, publish back to streams; dashboard and API read from there (SSE/WebSocket).
- **Cold** – Optional background archival to TimescaleDB for history and backtesting.

---

## Quick Start

**Prerequisites:** Python 3.13, Node 20+ (for dashboard), Docker (for DB and Redis).

```bash
# Environment
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure
docker run -d --name timescaledb -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly

# Schema (optional, for cold path)
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
```

Run services (each in its own terminal or under systemd):

```bash
python production/daemons/high_frequency_tws_daemon.py --client-id 35
python services/indicators_processor_service.py --config config/indicator_processor_service.json
python services/indicators_enhanced_service.py --config config/enhanced_indicator_processor.json
python services/intelligence_processor_service.py --config config/intelligence_processor.json
python services/timeframes_builder_service.py --config config/timeframe_builder_service.json
python services/coordination_parallel_service.py --config config/parallel_coordinator.json
```

API and dashboard:

```bash
# Backend (from repo root)
uvicorn src.api.main:app --reload

# Dashboard
cd dashboard && npm install && npm run dev
```

Health: `curl http://localhost:9109/health` (indicator processor), `curl http://localhost:9110/health` (timeframe builder). See `docs/for-ai-assistants/CLAUDE.md` for full commands and systemd usage.

---

## Project Layout

```
src/
  api/                    # FastAPI, SSE, health, routes
  config/                  # Settings
  core/                    # Streams (facade, factory, mixins), stream_models, unified_market_processor, DB, tick publisher
  indicators/              # calculations.py (facade), calc_modules/, incremental_manager.py
  intelligence/            # plugins.py, contracts.py, register_plugins.py, dag.py, state.py
                           # indicators/, patterns/, structure/, context/, composites/
                           # langgraph_event_processor.py, langgraph_integration.py
  observability/           # metrics, otel
production/                # daemons, schemas, migrations, scripts
services/                  # Service entrypoints (indicators, intelligence, timeframes, coordination)
config/                    # JSON configs per service
dashboard/                 # Next.js 15 / React 19
tests/                     # unit, integration, run_all_tests.py
docs/                      # Architecture and planning
```

---

## Reference

### Supported Instruments (examples)

- **Equity index futures:** ES, NQ, RTY  
- **Commodities:** CL, NG, GC, SI, HG, PL  
- **Volatility:** VX  

### Tech Stack

- Python 3.13, pandas 3.0, redis 7.1, FastAPI 0.129  
- LangGraph 1.0, LangChain 1.2  
- DragonflyDB or Redis; TimescaleDB (PostgreSQL 15)  
- Next.js 15.4, React 19, Tailwind v4  

### Environment (main)

Copy `.env.example` to `.env` and fill in values, or set:

```bash
INDICAGENT_ENV=development
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent
REDIS_URL=redis://localhost:6379/0
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=35
```

### Tests and Quality

```bash
python tests/run_all_tests.py           # Full suite
python tests/run_all_tests.py --unit-only
.venv/bin/ruff check . --fix
.venv/bin/black .
.venv/bin/mypy src/ --ignore-missing-imports
```

### Current Status and Next Steps

- **Done:** I1–I5 (22 plugins), incremental indicators (141x), hot/warm/cold split, circuit breakers, Prometheus, 110 unit tests.
- **Next:** I6 Confluence & Risk (multi-factor scoring from I3+I4+I5), then multi-timeframe confluence, smart-money concepts, I7/I8.

More detail: `docs/current-status-and-priorities.md`, `docs/architecture/layered-architecture.md`, `docs/architecture/intelligence-tiers.md`.

---

## For Developers

- **Conventions and commands:** `docs/for-ai-assistants/CLAUDE.md`  
- **Stream keys and schemas:** `src/core/stream_keys.py`, `docs/architecture/stream-schemas.md`  
- **Plugin registry and DAG:** `docs/architecture/plugin-registry-and-dag-execution.md`  

---

**Version:** 2.8.0 | **Status:** I3 + I4 + I5 complete, 22 plugins | **Focus:** I6 Confluence & Risk
