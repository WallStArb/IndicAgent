# IndicAgent Trading Intelligence Platform

**Where technical indicators become agentic: autonomous pipelines from ticks to structure, signals, and narratives.**

**Repository:** [github.com/WallStArb/IndicAgent](https://github.com/WallStArb/IndicAgent)

**Version:** 4.9.1
**Last Updated:** 2026-02-22
**Status:** I1-I8 Pipeline Complete

---

## What It Is

IndicAgent turns **live futures data** into **structured market intelligence** in real time. It ingests ticks from Interactive Brokers, builds bars and technical indicators, then runs a plugin-based pipeline that adds **market structure** (swings, support/resistance), **context** (volatility and trend regime), **pattern detection** (divergence, squeeze, confluence), **smart money concepts** (BOS/CHoCH, FVG, order blocks, liquidity sweeps), **cross-timeframe confluence**, **trading setups and signals**, and **AI-generated narratives**. Results are published to Redis Streams and served to a live dashboard or downstream systems. The database is used for history and backtesting, not the real-time path, so latency stays low.

**In one sentence:** A production-ready, plugin-native platform that turns IBKR futures ticks into real-time indicators, structure, context, patterns, SMC, confluence, signals, and AI narratives over Redis Streams, with a Next.js dashboard.

---

## At a Glance

| Aspect | Detail |
|--------|--------|
| **Data in** | IBKR TWS futures: **ES**, **NQ**, **RTY** (equity indices); **CL**, **NG** (energy); **GC**, **SI**, **HG**, **PL** (metals); **VX** (volatility); **ZN**, **ZF**, **ZB**, **ZT** (rates). 100–500+ ticks/sec |
| **Data out** | Redis Streams (bars, indicators, intelligence, signals, narratives); optional TimescaleDB for history |
| **Intelligence** | 57 plugins: I1 (23), I3 (3), I4 (5), I5 (8), I6 SMC (8), I6 confluence (1), I7 setups (9); I7 signal aggregation + I8 AI narratives + Dashboard panel operational |
| **Stack** | Python 3.13, FastAPI, LangGraph, DragonflyDB/Redis, TimescaleDB, Next.js 15 / React 19, Ollama |
| **Deployment** | Small independent services over streams; SSE for dashboard; Signal Orchestrator (:9112), AI Narrative (:9113) |

---

## How It Works

1. **Ingestion** – A daemon connects to IBKR TWS and publishes ticks and 1m bars to DragonflyDB (or Redis) streams.
2. **Processing** – Services consume streams: multi-timeframe bars (1m→5m→15m→1h→4h→1d), technical indicators (incremental), intelligence processor (I3/I4/I5/I6/I7 plugins), signal orchestrator (aggregation, ledger, lifecycle), and AI narrative service (Ollama-generated narratives from signals).
3. **Distribution** – Results are written to streams (intelligence, signals, narratives). The API exposes SSE; the dashboard subscribes for live updates.
4. **Storage** – Persistence to PostgreSQL/TimescaleDB is off the hot path and used for cold storage and historical context.

So: **ticks → bars → indicators → structure/context/patterns/SMC/confluence → setups/signals → aggregation → AI narratives → streams → dashboard**. No database in the live pipeline.

---

## Architecture

### Services (Microservices over Streams)

Services are independent processes that communicate exclusively via Redis Streams — no
direct service-to-service HTTP calls in the pipeline. Each service has a single responsibility
and can be restarted or redeployed without affecting others.

```
IBKR TWS
    │
    ▼
market_data_daemon ──────────────────────────────► ticks:SYMBOL:live
    │                                              price:SYMBOL:latest
    ▼
market:SYMBOL:1m
    │
    ├──────────────────────────────────────────┐
    ▼                                          ▼
indicator_service                   bar_aggregator_service
(23 I1 plugins, incremental)        (1m → 5m/15m/1h/4h/1d)
one combined message per bar                  │
    │         ◄────────────────────────────────┘
    ▼
indicators:SYMBOL:TF
    │
    ▼
market_analysis_service
(structure → context → patterns → SMC → confluence)
    │
    ▼
intelligence:SYMBOL:TF
    │
    ▼
signal_generator_service ──────────► signal_tracker_service
(I7 setup plugins + aggregation)     (open signal lifecycle,
    │                                 reads market:SYMBOL:1m)
    ▼
signals:SYMBOL:TF:aggregated
    │
    ▼
narrative_service ──────────────────► narratives:SYMBOL:TF ──► SSE ──► Dashboard
(Ollama qwen3:8b)
```

| Service | Single Responsibility | Port |
|---------|----------------------|------|
| `market_data_daemon` | IBKR connection, tick ingest, 1m bar formation | — |
| `indicator_service` | 23 I1 technical indicators (incremental) | 9109 |
| `bar_aggregator_service` | 1m → 5m/15m/1h/4h/1d resampling | 9110 |
| `market_analysis_service` | I3 structure, I4 context, I5 patterns, SMC, I6 confluence | — |
| `signal_generator_service` | I7 setup plugins, signal aggregation, ledger inserts | 9112 |
| `signal_tracker_service` | Open signal lifecycle tracking (stop/target/TTL) | — |
| `narrative_service` | I8 LLM narrative synthesis via Ollama | 9113 |
| `api_service` | FastAPI REST + SSE fan-out to dashboard | 8000 |

Full separation-of-duties reference: [`docs/architecture/service-separation.md`](docs/architecture/service-separation.md)

### Four Major Layers

The system is structured as four conceptual layers:

| Layer | Name | Contents | Status |
|-------|------|----------|--------|
| **1** | Data Foundation | Ingestion (IBKR), bar building, multi-timeframe aggregation, stream distribution | Operational |
| **2** | Mathematical Intelligence (I1–I4) | Indicators, composites, market structure, context/regime | Operational |
| **3** | Pattern Intelligence (I5–I7) | Pattern detection, SMC, confluence, trading setups, signal aggregation | Operational |
| **4** | AI Intelligence (I8) | LLM synthesis, narratives (Ollama) | Working |

Layer 1 feeds Layer 2; Layer 2 feeds Layer 3; Layer 3 feeds Layer 4. Each layer adds context on top of the previous one.

### Intelligence Tiers (I1–I8)

I1–I8 are the tiers inside layers 2–4. Lower tiers feed into higher ones.

| Tier | Name | Purpose | Status |
|------|------|---------|--------|
| **I1** | Raw indicators | RSI, MACD, SMA, EMA, ATR, BB, OBV, VWAP, Supertrend, PSAR, StochRSI, CMF, Aroon, etc. (23 plugins) | Operational |
| **I2** | Composites | Crossovers, slopes, distances | Operational (composites/) |
| **I3** | Market structure | Swings (HH/HL/LH/LL), support/resistance, trend structure (3 plugins) | Operational |
| **I4** | Context | Volatility regime, trend regime, momentum context, GARCH, Kalman trend (5 plugins) | Operational |
| **I5** | Patterns | RSI divergence, Bollinger squeeze, volume divergence, confluence, chart patterns (8 plugins) | Operational |
| **I6** | SMC + confluence | BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD, HMM; cross-timeframe confluence | Operational |
| **I7** | Trading outputs | 7 setup plugins (incl. VWAPDeviation, MomentumBreakout); signal aggregation (ledger, aggregator, lifecycle, sizer); Signal Orchestrator service | Operational |
| **I8** | AI intelligence | AI Narrative Service (Ollama qwen3:8b from aggregated signals) | Working |

So today the platform is **data + I1–I8**; next focus is dashboard narrative panel, I7 Phase 2 setups, and ML scoring calibration.

### Data Path: Hot / Warm / Cold

- **Hot** – Ticks and bars stay in DragonflyDB/Redis streams; sub-ms writes, no DB.
- **Warm** – Services read from streams, compute, publish back to streams; dashboard and API read from there (SSE/WebSocket).
- **Cold** – Optional background archival to TimescaleDB for history and backtesting.

---

## Quick Start

**Prerequisites:** Python 3.13, Node 20+ (for dashboard), Docker (for DB and Redis), Ollama (optional, for I8 AI narratives).

```bash
# Environment
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure
docker run -d --name timescaledb -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly
# Optional for I8: install Ollama and run e.g. ollama run qwen3:8b

# Schema (optional, for cold path)
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
```

Run services (each in its own terminal or under systemd):

```bash
python production/daemons/high_frequency_tws_daemon.py --client-id 35
python services/indicator_service.py --config config/indicator_service.json
python services/market_analysis_service.py --config config/market_analysis_service.json
python services/timeframes_builder_service.py --config config/timeframe_builder_service.json
python services/signal_generator_service.py --config config/signal_generator_service.json
python services/signal_tracker_service.py --config config/signal_tracker_service.json
python services/ai_narrative_service.py --config config/ai_narrative_service.json
```

API and dashboard:

```bash
# Backend (from repo root)
uvicorn src.api.main:app --reload

# Dashboard
cd dashboard && npm install && npm run dev
```

Health: `:9109` (indicator processor), `:9110` (timeframe builder), `:9112` (signal orchestrator), `:9113` (AI narrative), `:8000` (API). See `docs/for-ai-assistants/CLAUDE.md` for full commands and systemd usage.

---

## Project Layout

```
src/
  api/                    # FastAPI, SSE, health, routes
  config/                 # Settings
  core/                   # Streams (facade, factory, mixins), stream_models, DB, tick publisher
  indicators/             # calculations.py (facade), calc_modules/, incremental_manager.py
  intelligence/           # plugins.py, contracts.py, register_plugins.py, dag.py, state.py
                          # indicators/, patterns/, structure/, context/, composites/
                          # smart_money/, confluence/, trading/ (setups, aggregator, ledger, lifecycle, sizer)
  observability/          # metrics, otel
production/               # daemons, schemas, migrations, scripts, docker-compose
services/                 # indicator, market_analysis, timeframes, signal_generator, signal_tracker, ai_narrative
config/                   # JSON configs per service
dashboard/                # Next.js 15 / React 19
tests/                    # unit, integration, run_all_tests.py
docs/                     # Architecture and planning
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

- **Done:** I1–I8 (57 plugins), incremental indicators (141x), hot/warm/cold split, circuit breakers, Prometheus, Signal Orchestrator, AI Narrative Service, Dashboard Signal/Narrative Panel, 542 unit tests.
- **Next:** I7 Phase 2 continued (5 more setup plugins), ML scoring model calibration (after 500+ signals with P&L).

More detail: See [STATUS.md](docs/STATUS.md) and [MASTER_ROADMAP.md](docs/roadmap/MASTER_ROADMAP.md).

---

## Documentation

**→ [Full Documentation](docs/README.md)**
**→ [Current Status](docs/STATUS.md)**
**→ [Roadmap](docs/roadmap/MASTER_ROADMAP.md)**
**→ [Quick Start](docs/getting-started/quickstart.md)**

**For AI Assistants:** [CLAUDE.md](docs/for-ai-assistants/CLAUDE.md)  

---

**Version:** 4.9.1 | **Status:** I1–I8 complete, 57 plugins, 542 tests | **Focus:** I7 Phase 2, ML scoring
