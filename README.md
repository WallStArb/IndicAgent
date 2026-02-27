# IndicAgent Trading Intelligence Platform

**Repository:** [github.com/WallStArb/IndicAgent](https://github.com/WallStArb/IndicAgent)

**Version:** 5.5.0 | **Status:** I1–I8 Pipeline Complete | 57 plugins · 602 tests · 23 contracts

---

## Executive Summary

IndicAgent is an **institutional-grade, real-time market intelligence platform** for futures trading — built from the ground up around a plugin-native architecture, a typed intelligence bus, and a zero-database live pipeline that keeps end-to-end latency in the sub-millisecond range.

Where most indicator frameworks stop at RSI and MACD, IndicAgent runs a **layered intelligence pipeline across 8 tiers (I1–I8)**: raw technical indicators feed into market structure detection, which feeds into GARCH/Kalman volatility and trend regimes, which feed into pattern recognition and Smart Money Concepts (BOS/CHoCH, FVG, order blocks, liquidity sweeps, HMM regime, BOCPD), which converge in a cross-timeframe confluence engine that outputs **scored, structured trading setups** — capped by an LLM narrative synthesis layer that turns machine signals into natural language market analysis via a local Ollama model.

Every output at every tier is encoded into a **canonical `IntelligenceEvent` — a versioned, typed Pydantic model** published to DragonflyDB streams. This isn't a logging format; it's the backbone of a **typed intelligence bus** that decouples producers from consumers, makes the pipeline replay-able for historical backfill, and feeds a TimescaleDB **feature store** purpose-built for ML training.

The architecture is designed to be **externally consumable**: a FastAPI layer with JWT + API key auth exposes the full intelligence stream over SSE and REST, so any downstream application — a Vercel dashboard, a Slack bot, an algorithmic execution system, or an ML scoring model — subscribes to the same vetted, structured signal stream. The 8 services are fully systemd-managed with Prometheus metrics on each, making production operation as straightforward as running any other infrastructure daemon.

**The result:** a platform that ingests 100–500+ ticks/sec across 23 futures instruments (equity index, energy, metals, rates, FX, agriculture, crypto), processes them through 57 intelligence plugins in a strict DAG, and delivers structured, AI-enriched trading intelligence to any connected consumer — all without a database anywhere in the hot path.

---

## At a Glance

| Aspect | Detail |
|--------|--------|
| **Data in** | IBKR TWS futures: **ES**, **NQ**, **RTY**, **YM** (equity indices); **CL**, **BZ**, **NG** (energy); **GC**, **SI**, **HG**, **PL** (metals); **ZN**, **ZF**, **ZB**, **ZT**, **SR1** (rates); **VX** (volatility); **ZS**, **ZC**, **ZW** (agriculture); **6E**, **6J** (FX); **BTC** (crypto). 23 contracts, 100–500+ ticks/sec |
| **Data out** | Redis Streams (bars, indicators, intelligence, signals, narratives, group narratives); TimescaleDB feature store |
| **Intelligence** | 57 plugins: I1 (23), I3 (3), I4 (5), I5 (8), I6 SMC (6), I6 confluence (1), I7 setups (9); I7 signal aggregation + I8 AI narratives (per-signal + group synthesis) + Dashboard operational |
| **Stack** | Python 3.13, FastAPI, LangGraph, DragonflyDB/Redis, TimescaleDB, Next.js 16.1 / React 19.2, Ollama |
| **Deployment** | 8 systemd services over streams; SSE for dashboard; metrics on :9109/:9112/:9113/:9114/:9115/:9116 |

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
market:SYMBOL:1m + 5m/15m/1h/4h/1d (multi-TF)
    │
    ▼
indicator_service
(23 I1 plugins, incremental; multi-TF bar aggregation)
one combined indicators message per bar + TF
    │
    ▼
indicators:SYMBOL:TF
    │
    ▼
market_analysis_service
(structure → context → patterns → SMC → confluence → IntelligenceEvent)
    │
    ▼
intelligence:SYMBOL:TF  ─────────────────────────► feature_writer_service
    │                                               → intelligence_features (TimescaleDB)
    ▼
signal_generator_service ──────────► signal_tracker_service
(I7 setup plugins + aggregation)     (open signal lifecycle,
    │                                 reads market:SYMBOL:1m)
    ▼
signals:SYMBOL:TF:aggregated
    │
    ▼
ai_narrative_service ──────────────► narratives:SYMBOL:TF
(Ollama qwen3:8b per-signal +        narratives:group:GROUP_NAME ──► SSE ──► Dashboard
 phi4-mini:3.8b group synthesis)
```

| Service | Single Responsibility | Port |
|---------|----------------------|------|
| `market_data_daemon` | IBKR connection, tick ingest, 1m bar formation | — |
| `indicator_service` | 23 I1 technical indicators (incremental) + multi-TF aggregation | 9109 |
| `market_analysis_service` | I3 structure, I4 context, I5 patterns, SMC, I6 confluence | 9114 |
| `signal_generator_service` | I7 setup plugins, signal aggregation, ledger inserts | 9112 |
| `signal_tracker_service` | Open signal lifecycle tracking (stop/target/TTL) | 9115 |
| `ai_narrative_service` | I8 LLM narrative synthesis (per-signal + group) via Ollama | 9113 |
| `feature_writer_service` | Redis consumer → batch write to `intelligence_features` (TimescaleDB) | 9116 |
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
| **I7** | Trading outputs | 9 setup plugins; signal aggregation (ledger, aggregator, lifecycle, sizer); Signal Orchestrator service | Operational |
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

Run services (each in its own terminal, or use systemd in production):

```bash
.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/signal_tracker_service.py
.venv/bin/python services/ai_narrative_service.py
.venv/bin/python services/feature_writer_service.py
```

API and dashboard:

```bash
# Backend (from repo root)
uvicorn src.api.main:app --reload

# Dashboard
cd dashboard && npm install && npm run dev
```

Health: `:9109` (indicator), `:9112` (signal generator), `:9113` (AI narrative), `:9114` (market analysis), `:9115` (signal tracker), `:9116` (feature writer), `:8000` (API). See `docs/cheatsheet.md` for full commands and systemd usage.

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

### Supported Instruments (23 contracts)

- **Equity index futures:** ES, NQ, RTY, YM
- **Energy:** CL, BZ, NG
- **Metals:** GC, SI, HG, PL
- **Rates:** ZN, ZF, ZB, ZT, SR1
- **Volatility:** VX
- **Agriculture:** ZS, ZC, ZW
- **FX:** 6E, 6J
- **Crypto:** BTC

### Tech Stack

- Python 3.13, pandas 3.0, redis 7.1, FastAPI 0.129
- LangGraph 1.0, LangChain 1.2; LLM providers: Ollama (local) + OpenRouter (cloud)
- DragonflyDB (Redis protocol, Docker); TimescaleDB (PostgreSQL 15, native)
- Next.js 16.1, React 19.2, Tailwind v4.2

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

- **Done:** I1–I8 (57 plugins), incremental indicators, hot/warm/cold split, Prometheus metrics on all services, AI Narrative Service (Ollama qwen3:8b), feature store + historical backfill, typed intelligence bus, 602 unit tests. Phases 0–5 complete.
- **In Progress:** Phase 6 (Dashboard Connected) — live I1→I8 data flowing to dashboard. Signal generator and AI narrative service now emit per-TF signals (1m/5m/15m/1h). Dashboard drill panel, signal panel, and TF-matched narrative cards operational.

More detail: See [STATUS.md](docs/STATUS.md) and [Roadmap](.planning/ROADMAP.md).

---

## Documentation

**→ [Full Documentation](docs/README.md)**
**→ [Current Status](docs/STATUS.md)**
**→ [Roadmap](.planning/ROADMAP.md)**
**→ [Quick Start](docs/getting-started/quickstart.md)**

**For AI Assistants:** [CLAUDE.md](CLAUDE.md)

---

**Version:** 5.5.0 | **Status:** I1–I8 complete, 57 plugins, 602 tests | **Focus:** Dashboard Connected (Phase 6)
