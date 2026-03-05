# IndicAgent Market Intelligence Platform

**Repository:** [github.com/WallStArb/IndicAgent](https://github.com/WallStArb/IndicAgent)

**Version:** 1.4.0-dev | **Status:** v1.3 complete · v1.4 in progress | 88 plugins · 1117 tests · 24 instruments

---

## Executive Summary

IndicAgent is an **institutional-grade, real-time market intelligence platform** built from the ground up around a plugin-native architecture, a typed intelligence bus, and a zero-database live pipeline that keeps end-to-end latency in the sub-millisecond range.

Where most indicator frameworks stop at RSI and MACD, IndicAgent runs a **layered intelligence pipeline across 8 tiers (I1–I8)**: raw technical indicators and composite event signals feed into market structure detection, which feeds into GARCH/Kalman volatility and trend regimes, which feed into pattern recognition and Smart Money Concepts (BOS/CHoCH, FVG, order blocks, liquidity sweeps, HMM regime, BOCPD, ICT killzones, AMD cycles, breaker/mitigation blocks), which converge in a cross-timeframe confluence engine that outputs **scored, structured market setups**. An AI narrative synthesis layer on top turns machine signals into natural language market analysis via a **3-tier LLM inference chain: ZAI GLM-5 (primary) → OpenRouter (100+ model fallback) → Ollama local (offline guarantee)**.

Every output at every tier is encoded into a **canonical `IntelligenceEvent`, a versioned typed Pydantic model**, published to DragonflyDB streams. This is the backbone of a **typed intelligence bus** that decouples producers from consumers, makes the pipeline replayable for historical backfill, and feeds a TimescaleDB **feature store** built for ML training.

The architecture is designed to be **externally consumable**: a FastAPI layer with JWT + API key auth exposes the full intelligence stream over SSE and REST, so downstream applications (a Vercel dashboard, a Slack bot, an algorithmic execution system, an ML scoring model) subscribe to the same vetted, structured signal stream. The 8 services are fully systemd-managed with Prometheus metrics on each, making production operation as straightforward as running any other infrastructure daemon.

The platform ingests 100–500+ ticks/sec across 24 instruments (equity index, energy, metals, rates, FX, agriculture, crypto), processes them through 88 intelligence plugins in a strict DAG, and delivers structured, AI-enriched market intelligence to any connected consumer. No database in the hot path.

---

## What Makes This Different

Most market intelligence systems are monolithic pipelines: one process reads prices, computes indicators, and emits signals. That works at small scale. It breaks at production scale — and it breaks in ways that are hard to debug, harder to extend, and impossible to reason about under load.

IndicAgent is built around three architectural principles that solve the hard problems directly.

### 1. Directed Acyclic Graph (DAG) execution — dependency ordering without chaos

**The problem:** 87 plugins across 8 tiers. RSI must complete before RSI Divergence can read it. HMM regime must complete before the CIS scorer gates on it. In a naive system, you manage execution order manually — and one wrong dependency creates silent data corruption, or worse, a circular loop that hangs the pipeline indefinitely.

**The solution:** Every plugin declares its inputs. The DAG engine runs Kahn's topological sort at startup, producing a guaranteed valid execution order. Cycles are impossible to introduce — the engine detects them and hard-crashes at startup, not silently at runtime. Adding a new plugin means declaring its dependencies; ordering is inferred automatically.

The result: a pipeline that always moves forward, where every value has a clear lineage back to raw OHLCV data, and where the execution order is a property of the dependency graph — not a convention someone has to remember.

```
Raw OHLCV
  └─► I1 Indicators (23 plugins, no dependencies)
        └─► I2 Composite Events (depend on I1)
  └─► I3 Structure (reads OHLCV directly)
        └─► I4 Context / Regime (reads I3 + OHLCV)
  └─► I5 Patterns (reads I1 features)
  └─► I6 SMC + Confluence (reads I1–I5, cross-timeframe)
        └─► I7 Setups (reads I2–I6, regime-gated)
              └─► I8 AI Narrative (reads I7 signals)
```

→ [DAG Execution](docs/concepts/dag-execution.md)

### 2. Microservices over streams — isolation without coupling

**The problem:** A monolithic process that computes indicators, detects patterns, scores setups, tracks signal lifecycle, and generates AI narratives is operationally fragile. Restart the process to deploy a new plugin and you lose the in-flight state of every open signal. A bug in the AI narrative step causes backpressure that delays the indicator calculation. Scaling one stage means scaling all of them.

**The solution:** Each stage is a separate process that reads from Redis streams and writes to Redis streams. No service calls another service directly — there are no HTTP calls between services in the pipeline. Services communicate only through the stream layer.

This means: restarting `market_analysis_service` to deploy a new I5 pattern plugin has zero effect on `signal_lifecycle_service` tracking open trades. The AI narrative service can fall behind without slowing indicator calculation. A new consumer (a Slack bot, an ML scoring model, a second dashboard) subscribes to the existing `intelligence:SYMBOL:TF` stream without any change to the producers.

The streams are the API. Services are stateless workers that consume and produce messages. The typed `IntelligenceEvent` Pydantic model is the contract between them.

```
IBKR TWS → [DragonflyDB streams] → indicator_service
                                  → market_analysis_service
                                  → signal_generator_service → signal_lifecycle_service
                                  → feature_writer_service
                                  → ai_narrative_service
                                  → api_service → SSE → Dashboard
```

Each arrow is a Redis stream. No service knows the others exist.

→ [Data Pipeline](docs/concepts/data-pipeline.md)

### 3. Composite Intelligence Score (CIS) — signal selection under uncertainty

**The problem:** On a typical bar during an active session, 5–8 I7 setup plugins fire simultaneously — a TrendFollowing setup, a VWAPDeviation setup, and a CHoCHReversal with conflicting directions. Highest-confidence-wins is fragile: a high-confidence mean-reversion signal in a trending market still loses. Priority ordering goes stale as market regimes shift.

**The solution:** CIS aggregates evidence from the *entire* pipeline — not just the I7 plugins — into a single directional score using 6 weighted buckets:

| Bucket | Reads from | Weight |
|--------|-----------|--------|
| **Trend** | Kalman slope, trend regime, SMC trend, cross-TF alignment | 0.20 |
| **Momentum** | RSI deviation, MACD histogram, ROC, momentum bias | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH events, CHoCHReversal plugin | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle completions | 0.05 |
| **Institutional** | Order blocks, FVG activity, supply/demand zones | 0.25 |
| **Regime** | HMM hidden state probabilities, BOCPD changepoint, vol regime | 0.15 |

CIS fires only when `|score| > 0.35` **and** at least 3 of 6 buckets agree on direction. A single strong bucket cannot override the rest — cross-tier confirmation is required.

When CIS fires, it selects the highest-priority I7 signal that matches its direction. If no signal matches, it overrides the direction of the best available signal. CIS never drops a signal — only the hard RR gate (risk:reward) and regime eligibility filter (HMM state mismatch) can do that.

The weights are currently hand-tuned bootstraps. The architecture is designed to replace them with learned weights: signal outcomes from `signal_ledger` become labeled training data, a logistic regression fits per-bucket weights, and CIS improves without code changes. Every signal carries its `weights_version` so all outcomes are traceable to the exact weight set that produced them.

→ [CIS Scoring](docs/concepts/cis-scoring.md)

---

## At a Glance

| Aspect | Detail |
|--------|--------|
| **Data in** | IBKR TWS: **ES**, **NQ**, **RTY**, **YM** (equity indices); **CL** (energy); **GC**, **SI**, **HG**, **PL** (metals); **ZN**, **ZF**, **ZB**, **ZT** (rates); **VX** (volatility); **ZS**, **ZC**, **ZW** (agriculture); **EURUSD**, **GBPUSD**, **USDJPY**, **USDCHF** (spot FX); **BTCUSD**, **ETHUSD**, **SOLUSD** (spot crypto). 24 instruments, 100–500+ ticks/sec |
| **Data out** | Redis Streams (bars, indicators, intelligence, signals, narratives, group narratives); TimescaleDB feature store |
| **Intelligence** | 88 plugins: I1 (23), I2 (6), I3 (7), I4 (7), I5 (14), I6 SMC (13), I6 confluence (1), I7 setups (17) + 2 aggregation components; CIS scorer, weight updater; I8 AI narratives (per-signal + group synthesis); Dashboard operational |
| **Stack** | Python 3.13, FastAPI, LangGraph, DragonflyDB/Redis, TimescaleDB, Next.js 16.1 / React 19.2, Ollama |
| **Deployment** | 8 systemd services over streams; SSE for dashboard; metrics on :9109/:9112/:9113/:9114/:9115/:9116 |

---

## How It Works

1. **Ingestion** – A daemon connects to IBKR TWS and publishes ticks and 1m bars to DragonflyDB (or Redis) streams.
2. **Processing** – Services consume streams: multi-timeframe bars (1m→5m→15m→1h→4h→1d), technical indicators (incremental), intelligence processor (I3/I4/I5/I6/I7 plugins), signal orchestrator (aggregation, ledger, lifecycle), and AI narrative service (ZAI GLM-5 → OpenRouter → Ollama narrative generation from signals).
3. **Distribution** – Results are written to streams (intelligence, signals, narratives). The API exposes SSE; the dashboard subscribes for live updates.
4. **Storage** – Persistence to PostgreSQL/TimescaleDB is off the hot path and used for cold storage and historical context.

So: **ticks → bars → indicators → structure/context/patterns/SMC/confluence → setups/signals → aggregation → AI narratives → streams → dashboard**. No database in the live pipeline.

---

## Architecture

### Services (Microservices over Streams)

Services are independent processes that communicate exclusively via Redis Streams, with no direct service-to-service HTTP calls in the pipeline. Each service has a single responsibility and can be restarted or redeployed without affecting others.

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
(23 I1 plugins, incremental; multi-TF bar aggregation; I2 composite events)
one combined indicators message per bar + TF
    │
    ▼
indicators:SYMBOL:TF
    │
    ▼
market_analysis_service
(I1 → I2 events → structure → context → patterns → SMC → confluence → IntelligenceEvent)
    │
    ▼
intelligence:SYMBOL:TF  ─────────────────────────► feature_writer_service
    │                                               → intelligence_features (TimescaleDB)
    ▼
signal_generator_service ──────────► signal_lifecycle_service
(I7 setup plugins + aggregation)     (zone activation, MAE/MFE,
    │                                 8-class outcome tracking)
    ▼
signals:SYMBOL:TF:aggregated
    │
    ▼
ai_narrative_service ──────────────► narratives:SYMBOL:TF
(ZAI GLM-5 / OpenRouter / Ollama    narratives:group:GROUP_NAME ──► SSE ──► Dashboard
 per-signal + group synthesis)
```

| Service | Single Responsibility | Port |
|---------|----------------------|------|
| `market_data_daemon` | IBKR connection, tick ingest, 1m bar formation | — |
| `indicator_service` | 23 I1 technical indicators + 6 I2 composite events (incremental) + multi-TF aggregation | 9109 |
| `market_analysis_service` | I3 structure, I4 context, I5 patterns, SMC, I6 confluence | 9114 |
| `signal_generator_service` | I7 setup plugins, signal aggregation, ledger inserts | 9112 |
| `signal_lifecycle_service` | Zone-aware signal lifecycle: activation, MAE/MFE, 8-class outcome | 9115 |
| `ai_narrative_service` | I8 LLM narrative synthesis (per-signal + group) via ZAI/OpenRouter/Ollama | 9113 |
| `feature_writer_service` | Redis consumer → batch write to `intelligence_features` (TimescaleDB) | 9116 |
| `api_service` | FastAPI REST + SSE fan-out to dashboard | 8000 |

Full separation-of-duties reference: [`docs/architecture/service-separation.md`](docs/architecture/service-separation.md)

### Four Major Layers

The system is structured as four conceptual layers:

| Layer | Name | Contents | Status |
|-------|------|----------|--------|
| **1** | Data Foundation | Ingestion (IBKR), bar building, multi-timeframe aggregation, stream distribution | Operational |
| **2** | Mathematical Intelligence (I1–I4) | Indicators, composites, market structure, context/regime | Operational |
| **3** | Pattern Intelligence (I5–I7) | Pattern detection, SMC, confluence, market setups, signal aggregation | Operational |
| **4** | AI Intelligence (I8) | LLM narrative synthesis: ZAI GLM-5 (primary) → OpenRouter (fallback) → Ollama local (offline) | Operational |

Layer 1 feeds Layer 2; Layer 2 feeds Layer 3; Layer 3 feeds Layer 4. Each layer adds context on top of the previous one.

### Intelligence Tiers (I1–I8)

I1–I8 are the tiers inside layers 2–4. Lower tiers feed into higher ones.

| Tier | Name | Purpose | Status |
|------|------|---------|--------|
| **I1** | Raw indicators | RSI, MACD, SMA, EMA, ATR, BB, OBV, VWAP, Supertrend, PSAR, StochRSI, CMF, Aroon, etc. (23 plugins) | Operational |
| **I2** | Composite events | MACD crossovers, RSI events, Stochastic events, ADX events, Volume events, MomentumAcceleration (2nd-derivative RSI/MACD/ROC acceleration + inflection detection) (6 plugins) | Operational |
| **I3** | Market structure | Swing detector, S/R, trend structure, MarketProfile, SessionLevels, AnchoredVWAP, FibonacciZones (7 plugins) | Operational |
| **I4** | Context | Volatility/trend/momentum regime, GARCH volatility, Kalman trend, SessionContext, MTFVolatility (7 plugins) | Operational |
| **I5** | Patterns | RSI divergence, squeeze, vol divergence, confluence, trend confluence, chart patterns, volume profile, key level reaction (14 plugins) | Operational |
| **I6** | SMC + confluence | BOS/CHoCH, FVG, order blocks, HMM regime, liquidity pools, supply/demand, BOCPD, liquidity sweeps, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount, cross-timeframe confluence (13 SMC + 1 confluence) | Operational |
| **I7** | Market setups | 17 setup plugins: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysisSetup (opening gap fade/continuation), CandlestickPatternSetup (confluence-gated candlestick setups), SessionExtremesSetup (Asian session H/L fade London/NY); CISScorer 6-bucket aggregator + WeightUpdater | Operational |
| **I8** | AI intelligence | AI Narrative Service: ZAI GLM-5 → OpenRouter → Ollama (per-signal conf>0.7 + 6-group synthesis) | Operational |

The full I1–I8 pipeline is complete and operational as of v1.0 (shipped 2026-02-28).

### Signal Selection: The CIS Gate

When multiple I7 setup plugins fire on the same bar, the system needs to pick a winner and filter out noise when nothing is clearly dominant. That's the job of the **Composite Intelligence Score (CIS)**.

#### How it works

CIS aggregates six intelligence buckets, each drawing from different parts of the pipeline, into a single directional score in the range **[-1.0, +1.0]** (negative = bearish, positive = bullish):

| Bucket | What it reads | Top-level weight |
|--------|--------------|-----------------|
| **Trend** | `trend_regime`, Kalman slope, SMC trend direction, cross-TF alignment, trend confluence | 0.20 |
| **Momentum** | RSI deviation from 50, MACD histogram sign, ROC sign, momentum bias, DivergenceStack plugin | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH direction, CHoCHReversal plugin | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle breakout bias, PatternCompletion plugin | 0.05 |
| **Institutional** | Order block type×strength, FVG type×activity, supply/demand zone position, FVGFill + SupplyDemandSetup plugins | 0.25 |
| **Regime** | HMM hidden state probabilities, BOCPD changepoint stability, cross-TF regime agreement, vol regime, RegimeTransition plugin | 0.15 |

#### The gate: two conditions must be met

CIS only "fires" (overrides direction) when **both** of these hold:

1. **Threshold:** `|cis_score| > 0.35` (the composite score is meaningfully bullish or bearish, not noise)
2. **Agreement:** at least **3 of 6 buckets** push in the same direction as the score (each bucket must exceed a 0.10 noise floor to count)

If either condition fails, CIS is considered **neutral** and the system falls back to simpler rules: highest-priority plugin wins, with majority voting and HMM regime tiebreaking as backup.

#### The three decision paths

```
Multiple I7 plugins fire
        │
        ▼
  CIS gate check
        │
   ┌────┴─────────────────────────────────────┐
   │                                          │
CIS fires (|score|>0.35, ≥3 buckets agree)  CIS neutral → fallback rules
   │                                          │   priority → majority → regime tiebreak
   ▼                                          │
Pick highest-priority signal                  ▼
matching CIS direction                   Highest-priority signal wins
(if none match, force-override             (or no winner if direction conflict
direction on best available signal)         is unresolvable)
        │
        ▼
  RR gate (TradeFramer)
  Must be viable (risk:reward, zone quality)
  ↳ fails → signal dropped entirely
        │
        ▼
  Regime gate (HMM confidence ≥ 0.55, duration ≥ 3 bars)
  Filters out signals mismatched to the current macro regime
        │
        ▼
  Winner published to signal_ledger + stream
```

The RR gate and regime gate are the only hard drops. CIS itself never drops a signal outright; it redirects direction.

#### Adaptive weights (learning path)

The weights above are **bootstrap weights (version 0)**: fixed, manually tuned, and sufficient for early operation. The system is architected to replace them with **learned weights** from a `cis_weights` database table. When a weights row with `version > 0` is present, the scorer loads it at startup and tags every CIS result with that version number, so all signal outcomes are traceable to the exact weight set that produced them. This creates a closed loop: signal lifecycle outcomes (stop hit, target hit, TTL expired) from the `signal_ledger` become labeled training data, a future weight-learning step updates `cis_weights`, and the scorer improves without any code changes.

Bootstrap weights get the system running, outcome data trains the next version, and CIS gradually learns which market conditions precede profitable setups.

### Data Path: Hot / Warm / Cold

- **Hot** – Ticks and bars stay in DragonflyDB/Redis streams; sub-ms writes, no DB.
- **Warm** – Services read from streams, compute, publish back to streams; dashboard and API read from there (SSE/WebSocket).
- **Cold** – Optional background archival to TimescaleDB for history and backtesting.

---

## Quick Start

**Prerequisites:** Python 3.13, Node 20+ (for dashboard), Docker (for DB and Redis). I8 AI narratives use a 3-tier LLM chain: set `ZAI_API_KEY` in `.env` for the primary provider (GLM-5), `OPENROUTER_API_KEY` for the fallback, or install Ollama locally as the offline option.

```bash
# Environment
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure
docker run -d --name timescaledb -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly
# I8 LLM chain: ZAI_API_KEY (primary) + OPENROUTER_API_KEY (fallback) in .env
# Ollama is the offline last-resort: ollama run qwen3.5:9b

# Schema (optional, for cold path)
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
```

Run services (each in its own terminal, or use systemd in production):

```bash
.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/signal_lifecycle_service.py
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

Health: `:9109` (indicator), `:9112` (signal generator), `:9113` (AI narrative), `:9114` (market analysis), `:9115` (signal lifecycle), `:9116` (feature writer), `:8000` (API). See `docs/cheatsheet.md` for full commands and systemd usage.

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
services/                 # indicator, market_analysis, timeframes, signal_generator, signal_lifecycle, ai_narrative
config/                   # JSON configs per service
dashboard/                # Next.js 15 / React 19
tests/                    # unit, integration, run_all_tests.py
docs/                     # Architecture and planning
```

---

## Reference

### Supported Instruments (24)

- **Equity index futures:** ES, NQ, RTY, YM
- **Energy:** CL
- **Metals:** GC, SI, HG, PL
- **Rates:** ZN, ZF, ZB, ZT
- **Volatility:** VX
- **Agriculture:** ZS, ZC, ZW
- **FX:** EURUSD, GBPUSD, USDJPY, USDCHF (spot/IDEALPRO)
- **Crypto:** BTCUSD, ETHUSD, SOLUSD (spot/PAXOS)

### Tech Stack

- Python 3.13, pandas 3.0, redis 7.1, FastAPI 0.129
- LangGraph 1.0, LangChain 1.2; LLM providers: ZAI (GLM-5, primary), OpenRouter (fallback), Ollama (fallback)
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

### Current Status

**v1.3 complete 2026-03-04. v1.4 Quant Foundation in progress.**

- **I1–I8 pipeline:** Fully operational. 88 plugins (I1:23, I2:6, I3:7, I4:7, I5:14, I6 SMC:13, I6 confluence:1, I7:17), 2 aggregation components, typed intelligence bus, feature store, CIS scorer.
- **v1.3 delivered:** Phase 08 (MomentumAcceleration I2), Phase 09 (GapAnalysisSetup I7), Phase 10 (CandlestickPatternSetup I7), Phase 11 (SessionExtremesSetup I7) + Signal Lifecycle redesign (zone-aware lifecycle, 8-class outcome, MAE/MFE tracking).
- **v1.4 in progress:** Phase 12 Signal Integrity ✅ (regime gating, shadow signals, SIGINT-01–05); Phase 13 Data Completeness, Phase 14 Feedback Loop, Phase 15 Validated Alpha — next.
- **Dashboard:** Live: price hero, multi-TF intelligence panels, SMC panel (HMM regime, BSL/SSL zones), I7 signal drill panel (entry/SL/TP/RR), AI narrative cards.
- **AI Narratives:** Per-signal via ZAI GLM-5 / OpenRouter / Ollama (conf > 0.7, 5m/15m/1h); group synthesis across 6 asset groups.
- **Test suite:** 1117 passing, 0 ruff errors.
- **Next:** v1.4 (see [Roadmap](.planning/ROADMAP.md)).

More detail: See [STATUS.md](docs/STATUS.md) and [Roadmap](.planning/ROADMAP.md).

---

## Documentation

**→ [Full Documentation](docs/README.md)**
**→ [Current Status](docs/STATUS.md)**
**→ [Roadmap](.planning/ROADMAP.md)**
**→ [Quick Start](docs/getting-started/quickstart.md)**

**For AI Assistants:** [CLAUDE.md](CLAUDE.md)

---

**Version:** 1.4.0-dev | **Status:** v1.3 complete · v1.4 in progress · 88 plugins · 1117 tests | **Next:** Phase 13 Data Completeness
