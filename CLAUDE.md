# CLAUDE.md

Version: 4.2.0
Last Updated: 2026-02-17
Status: I1-I7 Phase 1.5 complete — 38 plugins + 4 aggregation components, 258 tests, full pipeline operational

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# IndicAgent Trading Intelligence Platform

Real-time futures trading intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Required Workflows

### Feature Development (any new plugin, service, or significant change)
**Mandatory skill chain — do not skip steps:**
1. `brainstorming` — Explore context, clarify requirements, propose approaches, get design approval. Save design to `docs/plans/YYYY-MM-DD-<topic>-design.md`
2. `writing-plans` — Create TDD implementation plan with bite-sized tasks. Save to `docs/plans/YYYY-MM-DD-<topic>.md`
3. `executing-plans` — Execute plan task-by-task with review checkpoints between batches
4. `verification-before-completion` — Run full test suite + lint before claiming done
5. `finishing-a-development-branch` — Clean git history, decide merge/PR/cleanup

**Do NOT jump straight to coding.** Even "simple" plugins need the brainstorming step to validate design decisions.

### Bug Fixes & Debugging
1. `systematic-debugging` — Structured investigation before proposing fixes
2. `verification-before-completion` — Confirm fix works before committing

### After Major Changes
- `revise-claude-md` — Update this file with session learnings (plugin counts, new gotchas, etc.)
- `requesting-code-review` — Review own work quality before merge

### Documentation Updates
- `claude-md-improver` — Periodic CLAUDE.md quality audit (run when numbers feel stale)

## Core Commands

### Development Setup
```bash
# Environment setup
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure (Docker)
docker run -d --name timescaledb -e POSTGRES_PASSWORD=postgres -p 5432:5432 timescale/timescaledb:latest-pg15
docker run -d --name dragonfly -p 6379:6379 docker.dragonflydb.io/dragonflydb/dragonfly
docker run -d --name ollama --gpus=all -v ollama:/root/.ollama -p 127.0.0.1:11434:11434 ollama/ollama

# Database schema
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
```

### System Operations
```bash
# Runtime management (systemd)
sudo systemctl status indicagent-backend-api indicagent-websocket indicagent-hf-tws
sudo systemctl restart indicagent-backend-api indicagent-websocket indicagent-hf-tws
journalctl -u indicagent-hf-tws -f

# Health monitoring
curl http://localhost:9109/health    # Indicator Processor health
curl http://localhost:9109/metrics   # Indicator Processor metrics (Prometheus)
curl http://localhost:9110/health    # Timeframe Builder health
curl http://localhost:9110/metrics   # Timeframe Builder metrics (Prometheus)

# Individual services
python production/daemons/high_frequency_tws_daemon.py --client-id 35  # High-freq data (use unique client ID)
python services/indicators_processor_service.py --config config/indicator_processor_service.json
python services/indicators_enhanced_service.py --config config/enhanced_indicator_processor.json  # 141x faster incremental calculations
python services/timeframes_builder_service.py --config config/timeframe_builder_service.json
python services/coordination_parallel_service.py --config config/parallel_coordinator.json  # Service coordination

# Historical data seeding
python production/scripts/simple_seeder.py --client-id 55 --days 7
```

### Development & Testing
```bash
# Run tests
python -m pytest tests/unit/ -v                  # Unit tests (258 passing)
python -m pytest tests/integration/ -v           # Integration tests (requires Redis + PostgreSQL)
python tests/run_all_tests.py                    # Full suite with infrastructure checks
python tests/run_all_tests.py --unit-only        # Unit tests only
python tests/run_all_tests.py --coverage         # With coverage reporting

# Code quality
.venv/bin/ruff check . --fix                     # Linting (0 errors on new code)
.venv/bin/black .                                # Code formatting
.venv/bin/mypy src/ --ignore-missing-imports     # Type checking

# Dashboard development
cd dashboard && npm run dev                      # Frontend development server
```

## Architecture Overview

**Plugin-Native Intelligence Platform** with LangGraph event-driven workflows and configuration-driven processing:

### 4-Layer Intelligence Architecture
```
Layer 4: AI Intelligence (I8)              -> LLM analysis, multi-modal processing, cost controls
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence analysis, signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, composite analysis, context
Layer 1: Data Foundation                   -> High-frequency collection, aggregation, distribution
```

### Intelligence Pipeline (operational)
```
OHLCV → I1 Indicators → I3 Structure → I4 Context → I5 Patterns → SMC Smart Money → I6 Confluence → Redis → SSE → Dashboard
```

## Key Components

### Production Services (Active)
- `production/daemons/high_frequency_tws_daemon.py` - Dual-stream data collection (see Data Flow below)
- `services/indicators_processor_service.py` - Production indicator calculation daemon (Health: `:9109/health`)
- `services/indicators_enhanced_service.py` - Enhanced service with incremental calculations (141x faster)
- `services/timeframes_builder_service.py` - Multi-timeframe aggregation service (Health: `:9110/health`)
- `services/coordination_parallel_service.py` - Parallel service coordination
- `src/api/main.py` - FastAPI backend with health monitoring and SSE support
- `src/api/routes/sse.py` - Server-Sent Events for real-time dashboard communication
- `dashboard/` - Next.js React dashboard with live visualization

### Core Runtime
- `src/core/redis_streams_manager.py` - High-performance Redis Streams (3,200+ ops/sec)
- `src/core/database_manager.py` - PostgreSQL/TimescaleDB persistence with connection pooling
- `src/core/stream_keys.py` - Standardized Redis stream key management
- `src/indicators/incremental_manager.py` - State-based incremental indicator calculations (141x boost)
- `src/intelligence/` - Plugin-based intelligence framework with DAG execution

### Intelligence Framework
- `src/intelligence/plugins.py` - Plugin registry (`registry.indicators`, `registry.patterns`)
- `src/intelligence/dag.py` - DAG execution engine with dependency resolution
- `src/intelligence/register_plugins.py` - Centralized plugin registration (33 total)
- `src/intelligence/utils.py` - Shared utilities (peak/trough detection, helpers)

### Configuration
- `src/config/settings.py` - Centralized application configuration, instrument/contract definitions, and helper functions
- `src/observability/metrics.py` - Prometheus metrics collection and monitoring
- `src/api/routes/instruments.py` - REST endpoint serving instrument config from DB

## Data Flow Architecture

### HF Daemon: Dual-Stream Collection
The `hf_tws_daemon` collects two independent data streams from IBKR TWS simultaneously:

1. **1m OHLCV Bars** via `reqHistoricalData` (polled every 60s)
   - IBKR server-side aggregated bars (authoritative OHLCV + volume)
   - Published to `market:SYMBOL:1m` streams
   - Foundation for all indicator calculations and timeframe building
   - NOT built from ticks — these are IBKR's own bar data

2. **Live Ticks** via `reqMktData` (real-time callbacks, tick list "233")
   - Price, bid, ask, volume updates at tick level
   - Published to `ticks:SYMBOL:live` streams (20,000 retention per symbol)
   - Also cached to `price:SYMBOL:latest` hash for instant UI lookups
   - Used for sub-second dashboard updates within a candle

### Pipeline Flow
```
IBKR TWS ─┬─ reqHistoricalData (60s poll) ─→ market:SYMBOL:1m ─→ Timeframe Builder ─→ market:SYMBOL:5m/15m/1h/4h/1d
           │                                        ↓
           │                              Indicator Processor ─→ indicators:SYMBOL:TIMEFRAME
           │                                        ↓
           │                              Intelligence Processor ─→ insights:SYMBOL:TIMEFRAME
           │                                        ↓
           └─ reqMktData (live ticks) ───→ ticks:SYMBOL:live ──→ SSE ──→ Dashboard
                                          price:SYMBOL:latest
```

### Hot/Warm/Cold Data Tiers
```
Hot:  IBKR TWS → hf_tws_daemon → DragonflyDB Streams → Services (sub-ms latency)
Warm: Streams → indicator_processor → timeframe_builder → intelligence_processor → Dashboard
Cold: Services → Background Archival → TimescaleDB → Historical Analysis / Backtesting
```

**Key:** Real-time flow never touches database. Stream-first, database-later.

### Redis Streams Format
- **Live Ticks:** `ticks:SYMBOL:live` — raw tick data from reqMktData
- **Latest Price:** `price:SYMBOL:latest` — hash with current price/bid/ask (120s TTL)
- **Market Data:** `market:SYMBOL:TIMEFRAME` (1m, 5m, 15m, 1h, 4h, 1d)
- **Indicators:** `indicators:SYMBOL:TIMEFRAME`
- **Patterns:** `patterns:SYMBOL:TIMEFRAME`
- **Intelligence:** `insights:SYMBOL:TIMEFRAME`
- **Signals (raw):** `signals:SYMBOL:TIMEFRAME`
- **Signals (aggregated):** `signals:SYMBOL:TIMEFRAME:aggregated`

## Plugin System (38 total)

### I1 Technical Indicators (16 plugins)
All with real incremental `compute_next()` — 141x performance boost:
- **Trend:** SMA/EMA, MACD, ADX/DMI
- **Momentum:** RSI, Stochastic, Williams %R, CCI, ROC/PPO
- **Volatility:** Bollinger Bands, ATR, Keltner Channels, Donchian Channels
- **Volume:** OBV, MFI, VWAP

### I3 Market Structure (3 plugins)
- Swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure

### I4 Context Classification (3 plugins)
- Volatility regime, trend regime, momentum context

### I5 Pattern Detection (4 plugins)
- RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence

### I6 Smart Money Concepts (6 plugins)
- BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime classification

### I6 Cross-Timeframe Confluence (1 plugin)
- Trend/structure/regime/pattern alignment scoring across 1m/5m/15m/1h

### I7 Trading Setups — Phase 1 (5 plugins)
- TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion
- Regime-adaptive setup detection with signal.v1 schema
- ATR-based stop/target placement, confluence-weighted confidence scoring

### I7 Signal Aggregation — Phase 1.5 (4 components)
- **Signal Aggregator** (`src/intelligence/trading/aggregator.py`) — Rules-based conflict resolution with setup priority
- **Signal Ledger** (`src/intelligence/trading/signal_ledger.py`) — Repository for signal_ledger hypertable (insert/update/query)
- **Lifecycle Tracker** (`src/intelligence/trading/lifecycle_tracker.py`) — Pure-function state machine (pending→active→exit) with P&L
- **Position Sizer** (`src/intelligence/trading/position_sizer.py`) — Risk-based contract calculation

## Development Standards

### Primary Instruments (14 contracts)
**Equity Index Futures:** ES (S&P 500), NQ (Nasdaq), RTY (Russell 2000)
**Energy:** CL (Crude Oil), NG (Natural Gas)
**Metals:** GC (Gold), SI (Silver), HG (Copper), PL (Platinum)
**Interest Rates:** ZN (10-Year T-Note), ZF (5-Year T-Note), ZB (30-Year T-Bond), ZT (2-Year T-Note)
**Volatility:** VX (VIX Futures)

### Naming Conventions
- **Files:** `[domain]_[purpose]_[suffix].py`
- **Redis Streams:** `domain:SYMBOL:TIMEFRAME:type`
- **Plugin names:** `ind_*` (I1), `comp_*` (I2), `struct_*` (I3), `ctx_*` (I4), `patt_*` (I5), `smc_*` (I6), `i6_*` (I6 confluence)

### Standards (enforced)
- **Streams & env prefix**: Build stream names via `src/core/stream_keys.py`. Include `env_prefix` from `INDICAGENT_ENV`.
- **Configuration**: Use `src/config/Settings`. Avoid direct `os.environ` reads.
- **Metrics**: Create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: Place under `tests/unit`, `tests/integration`, `tests/e2e`; pytest with asyncio auto. Prefer live data over mocks for integration tests.
- **Services**: Graceful SIGINT/SIGTERM, drain queues, close async Redis with `await`, idempotent consumer groups, `/health` and `/metrics` endpoints.
- **Logging**: `structlog` with fields: `timestamp`, `service`, `symbol`, `timeframe`, `level`, `message`.
- **Error Handling**: Circuit breakers for external deps. Exponential backoff. Correlation IDs.
- **Performance**: <10ms indicator calc, >500 ticks/sec, <50ms dashboard updates.
- **Data Architecture**: Hot/warm/cold. Never write to database in hot path.
- **IBKR**: Tick list `"233"` for futures. Unique client IDs (35+ range). IBKR uses "VIX" not "VX" for VIX futures symbol.
- **Plugin protocol**: All plugins use `PatternPlugin` protocol. Register via `registry.register_indicator()` or `registry.register_pattern()` in `register_plugins.py`. Access via `registry.indicators` / `registry.patterns` (not private `_indicators`).
- **References**: Stream schemas: `docs/architecture/stream-schemas.md`. Intelligence tiers: `docs/architecture/intelligence-tiers.md`.

## Environment Variables

```bash
INDICAGENT_ENV="development"    # development, staging, production
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
REDIS_URL="redis://localhost:6379/0"
IBKR_HOST="172.18.176.1"       # WSL: Windows host IP
IBKR_PORT=7497                 # TWS paper trading
IBKR_CLIENT_ID=35              # Unique client ID (35+ range)
OLLAMA_BASE_URL="http://localhost:11434"  # Local LLM inference (Docker)
OLLAMA_DEFAULT_MODEL="qwen3:8b"           # Default model for I8 AI tier
OPENROUTER_API_KEY="your_key"             # Cloud AI fallback (optional)
```

## Current Development Status

**Infrastructure:** Production-ready — IBKR collection, Redis streams, indicator calculations
**Plugin System:** 38 registered (16 indicators + 22 patterns/structure/context/smart_money/trading) + 4 aggregation components
**Test Status:** 258 unit tests passing, 0 ruff errors
**Pipeline:** I1 → I3 → I4 → I5 → SMC → I6 → I7 → Redis → SSE → Dashboard (fully wired)

### Intelligence Tiers
- **I1 Indicators** — 16 plugins with incremental compute_next() — WORKING
- **I2 Composites** — Crossovers, slopes, distances — WORKING
- **I3 Structure** — 3 plugins (swing, S/R, trend) — WORKING
- **I4 Context** — 3 plugins (vol regime, trend regime, momentum) — WORKING
- **I5 Patterns** — 4 plugins (RSI div, BB squeeze, vol div, confluence) — WORKING
- **I6 Smart Money** — 6 plugins (BOS/CHoCH, FVG, OB, sweeps, BOCPD, HMM) — WORKING
- **I6 Confluence** — 1 plugin (cross-timeframe alignment) — WORKING
- **I7 Trading Outputs** — 5 Phase 1 plugins (TrendFollowing, MeanReversion, LiqSweepReclaim, MTFAlignment, SqueezeExpansion) — WORKING
- **I7 Signal Aggregation** — Phase 1.5: aggregator, signal ledger, lifecycle tracker, position sizer — WORKING
- **I8 AI Insights** — LLM synthesis — NOT IMPLEMENTED (Ollama infrastructure ready)

### Local LLM Infrastructure (Ollama)
5 models available at `http://localhost:11434` (Docker, GPU-accelerated):
| Model | Size | Family | Quant | Notes |
|-------|------|--------|-------|-------|
| `qwen3:8b` | 5.2 GB | Qwen3 | Q4_K_M | **Default** — best quality, built-in thinking mode |
| `gemma3n:e4b` | 7.5 GB | Gemma3n | Q4_K_M | Google, good general reasoning |
| `qwen3:4b` | 2.5 GB | Qwen3 | Q4_K_M | Fast variant, thinking mode |
| `phi4-mini:3.8b` | 2.5 GB | Phi4 | Q4_K_M | Microsoft, fast inference |
| `deepscaler:1.5b` | 3.6 GB | Qwen2 | F16 | Smallest, math/reasoning focused |

**Note:** Qwen3 models use thinking mode by default — `content` field may be empty if `num_predict` is too low. Use `/no_think` prefix or set `num_predict` ≥ 500 for reliable output. Use the chat API (`/api/chat`) for multi-turn, generate API (`/api/generate`) for single-shot.

### Development Priorities
1. **More regime models** — GARCH volatility, Kalman filter trend, chart patterns (see `docs/plans/future-indicators-backlog.md`)
2. **I7 Trading Outputs Phase 2** — 9 more setup plugins (VWAP, momentum, chart patterns)
3. **I8 AI Intelligence** — LLM interpretation with cost controls

### Completed Phases
- **LG-1** — LangGraph event-driven workflows, circuit breakers
- **CQ-1** — Code quality: 1,323 lint fixes, formatting
- **PR-2** — Production: test runner, incremental_manager, parallel services, SSE
- **PI-1** — 16 indicator plugins with hybrid processing
- **T2** — Tier 2 refactor: calculations.py + redis_streams_manager.py → mixins
- **I3** — Market structure: 3 plugins
- **I4** — Context classification: 3 plugins
- **I5** — Pattern detection: 4 plugins
- **FH** — Foundation hardening: shared utils, temporal metadata, continuous scores
- **SMC** — Smart money: 6 plugins (BOS/CHoCH, FVG, OB, sweeps, BOCPD, HMM regime)
- **I6** — Cross-timeframe confluence: 1 plugin with intelligence_cache
- **Cleanup** — ~7,500 lines dead code removed across three rounds
- **Deps** — pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, Next.js 15.5
- **I7-P1** — Trading setups Phase 1: 5 plugins, signal schema, SSE wiring, 35 new tests
- **I7-P1.5** — Signal aggregation: rules-based aggregator, signal ledger hypertable, lifecycle tracker, position sizer, 45 new tests

## Key References

**Status & Planning:**
- `docs/current-status-and-priorities.md` — Development status and ranked priorities
- `docs/plans/future-indicators-backlog.md` — Detailed plugin specs for GARCH, Kalman, chart patterns, and batched indicators
- `docs/architecture/intelligence-tiers.md` — I1-I8 framework
- `docs/architecture/plugin-registry-and-dag-execution.md` — Plugin framework design
- `docs/architecture/stream-schemas.md` — Redis stream data format specifications

**API Documentation:**
- IBKR TWS API: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
- DragonflyDB: https://www.dragonflydb.io/docs/
- FastAPI: https://fastapi.tiangolo.com/
- Next.js: https://nextjs.org/docs

**Key Dependency Versions:**
- pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, LangChain 1.2, OpenAI SDK 2.20, Next.js 15.5
