# CLAUDE.md

Version: 5.3.0
Last Updated: 2026-02-22
Status: I1-I8 pipeline complete — 57 plugins + 4 aggregation components + service-separated pipeline + Dashboard Signal/Narrative Panel, 551 tests, 23 contracts

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

### Library & Framework Documentation
- Use `context7-plugin:docs` skill for any library/framework question — FastAPI, Next.js, SQLAlchemy, LangGraph, pytest, Redis, etc.
- Do not guess at API signatures or config options — check Context7 first (MCP + plugin both installed)

## Core Commands

### Development Setup
```bash
# Environment setup
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure
# PostgreSQL/TimescaleDB — runs natively (not Docker): sudo systemctl start postgresql
# Ollama — runs natively (not Docker): ollama serve
# DragonflyDB — runs via Docker only:
cd production && docker compose up -d dragonfly

# Database schema (base + numbered migrations in order)
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
for f in production/migrations/0*.sql; do psql -U postgres -d indicagent -f "$f"; done
```

### System Operations
```bash
# Runtime management (systemd)
sudo systemctl status indicagent-backend-api indicagent-websocket indicagent-hf-tws
sudo systemctl restart indicagent-backend-api indicagent-websocket indicagent-hf-tws
journalctl -u indicagent-hf-tws -f

# Health monitoring
curl http://localhost:9109/metrics   # Indicator Service metrics (Prometheus)
curl http://localhost:9110/health    # Timeframe Builder health
curl http://localhost:9110/metrics   # Timeframe Builder metrics (Prometheus)
curl http://localhost:9112/metrics   # Signal Generator metrics (Prometheus)
curl http://localhost:9114/metrics   # Market Analysis Service metrics (Prometheus)
curl http://localhost:9115/metrics   # Signal Tracker metrics (Prometheus)

# Individual services
python production/daemons/high_frequency_tws_daemon.py --client-id 35  # High-freq data (use unique client ID)
python services/indicator_service.py --config config/indicator_service.json                        # I1: all 23 indicators → indicators:SYMBOL:TF
python services/market_analysis_service.py --config config/market_analysis_service.json            # I3→I6: consumes indicators stream (Metrics: :9114)
python services/timeframes_builder_service.py --config config/timeframe_builder_service.json
python services/signal_generator_service.py --config config/signal_generator_service.json          # I7: generates signals (Metrics: :9112)
python services/signal_tracker_service.py --config config/signal_tracker_service.json              # Lifecycle: tracks open signals (Metrics: :9115)
python services/ai_narrative_service.py --config config/ai_narrative_service.json                  # I8: AI narratives (Metrics: :9113)

# Historical data seeding (simple_seeder.py RETIRED — superseded by historical_backfill.py)
python production/scripts/historical_backfill.py --days 90          # Stage 1+2: IBKR fetch → signal replay (686 lines)
python production/scripts/historical_backfill.py --fetch-only       # Stage 1 only: IBKR → TimescaleDB
python production/scripts/historical_backfill.py --replay-only      # Stage 2 only: DB → I1→I7 → signal_ledger
```

### Development & Testing
```bash
# Run tests
.venv/bin/python3 -m pytest tests/unit/ -v        # Unit tests (551 passing) — use .venv/bin/python3, not bare python/python3
.venv/bin/python -m pytest tests/integration/ -v # Integration tests (requires Redis + PostgreSQL)
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
- `services/indicator_service.py` - All 23 I1 plugins → combined OHLCV+indicators message to `indicators:SYMBOL:TF` (Metrics: `:9109`)
- `services/market_analysis_service.py` - I3→I4→I5→SMC→I6 pipeline: consumes `indicators:` stream, publishes to `intelligence:` (Metrics: `:9114`)
- `services/timeframes_builder_service.py` - Multi-timeframe aggregation service (Health: `:9110/health`)
- `services/signal_generator_service.py` - I7 signal generation: runs plugins, aggregates, persists to signal_ledger, publishes winner (Metrics: `:9112`)
- `services/signal_tracker_service.py` - Signal lifecycle tracking: evaluates open signals against market bars (Metrics: `:9115`)
- `services/ai_narrative_service.py` - I8 AI narrative synthesis: LLM narratives from selected signals via Ollama qwen3:8b, published to narratives:SYMBOL:TF stream (Metrics: `:9113`)
- `src/api/main.py` - FastAPI backend with health monitoring and SSE support
- `src/api/routes/sse.py` - Server-Sent Events for real-time dashboard communication
- `dashboard/` - Next.js React dashboard with live visualization

### Data Providers
- `src/providers/base.py` — `DataProvider` protocol (runtime_checkable), `Tick`, `OHLCVBar` normalized wire models
- `src/providers/ibkr.py` — `IBKRProvider`: all ib_insync logic isolated here (connect, qualify, fetch_historical_bars, stream_ticks, resolve_instrument)
- `src/providers/__init__.py` — exports `DataProvider`, `IBKRProvider`, `Tick`, `OHLCVBar`
- **Rule:** No `ib_insync` imports anywhere outside `src/providers/ibkr.py`

### Core Runtime
- `src/core/redis_streams_manager.py` - High-performance Redis Streams (3,200+ ops/sec)
- `src/core/database_manager.py` - PostgreSQL/TimescaleDB persistence with connection pooling
- `src/core/stream_keys.py` - Standardized Redis stream key management
- `src/indicators/incremental_manager.py` - State-based incremental indicator calculations (141x boost)
- `src/intelligence/` - Plugin-based intelligence framework with DAG execution

### Intelligence Framework
- `src/intelligence/plugins.py` - Plugin registry (`registry.indicators`, `registry.patterns`)
- `src/intelligence/dag.py` - DAG execution engine with dependency resolution
- `src/intelligence/register_plugins.py` - Centralized plugin registration (53 total)
- `src/intelligence/utils.py` - Shared utilities (peak/trough detection, helpers)

### Configuration
- `src/config/settings.py` - Centralized application configuration, instrument/contract definitions, and helper functions
- `src/observability/metrics.py` - Prometheus metrics collection and monitoring
- `src/api/routes/instruments.py` - REST endpoint serving instrument config from DB

## Data Flow Architecture

### HF Daemon: Dual-Stream Collection
The `hf_tws_daemon` collects two independent data streams from IBKR TWS simultaneously:

1. **1m OHLCV Bars** — two events per minute per symbol (low-latency design):
   - **Provisional bar** (`source: "tick_derived"`) at :00 — built from tick accumulator, triggers pipeline immediately (~1s latency)
   - **Authoritative bar** (`source: "authoritative"`) at :05 — from `reqHistoricalData`, silently corrects history in-place (5–10s latency)
   - Published to `market:SYMBOL:1m` streams; downstream services filter on `source` field

2. **Live Ticks** via `reqMktData` (real-time callbacks, tick list "233")
   - Price, bid, ask, volume updates at tick level
   - Published to `ticks:SYMBOL:live` streams (20,000 retention per symbol)
   - Also cached to `price:SYMBOL:latest` hash for instant UI lookups
   - Tick accumulator tracks per-minute OHLCV for provisional bar generation

### Bar Source Field (added 2026-02-19)
- `source: "tick_derived"` — provisional bar from tick accumulator, triggers pipeline (~1s latency)
- `source: "authoritative"` — confirmed bar from reqHistoricalData, updates history only (5–10s latency)
- Missing/other source — treated as tick_derived (backward compat with old daemon versions)

### Pipeline Flow
```
IBKR TWS ─┬─ reqHistoricalData (:05 each min) ─→ market:SYMBOL:1m (authoritative) ─→ history correction only
           │                                              ↓ (tick_derived at :00)
           │                                    Intelligence Processor ─→ insights:SYMBOL:TIMEFRAME
           │                                              ↓
           │                                    Timeframe Builder ─→ market:SYMBOL:5m/15m/1h/4h/1d
           │
           └─ reqMktData (live ticks) ─→ tick_accum → provisional bar at :00
                                       → ticks:SYMBOL:live ──→ SSE ──→ Dashboard
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
- **Intelligence:** `intelligence:SYMBOL:TIMEFRAME` — includes OHLCV + all feature fields (enriched 2026-02-18)
- **Signals (raw):** `signals:SYMBOL:TIMEFRAME`
- **Signals (aggregated):** `signals:SYMBOL:TIMEFRAME:aggregated`
- **Narratives:** `narratives:SYMBOL:TIMEFRAME` — AI narrative text stream (I8 output); `narrative:SYMBOL:TF:latest` hash (90s TTL)

## Plugin System (53 total)

### I1 Technical Indicators (23 plugins)
All with real incremental `compute_next()` — 141x performance boost:
- **Trend:** SMA/EMA, MACD, ADX/DMI, Parabolic SAR, Aroon
- **Momentum:** RSI, Stochastic, Williams %R, CCI, ROC/PPO, Stochastic RSI
- **Volatility:** Bollinger Bands, ATR, Keltner Channels, Donchian Channels, Chandelier Exit, Historical Volatility
- **Volume:** OBV, MFI, VWAP, CMF

### I3 Market Structure (3 plugins)
- Swing detector (HH/HL/LH/LL), support/resistance (pivot clustering), trend structure

### I4 Context Classification (5 plugins)
- Volatility regime, trend regime, momentum context, GARCH volatility (conditional vol forecast, 4 outputs)
- Kalman filter trend (adaptive trend estimation, fair value, 7 outputs)

### I5 Pattern Detection (8 plugins)
- RSI divergence, Bollinger squeeze, volume divergence, multi-indicator confluence, trend confluence
- Chart patterns: Double Top/Bottom (`patt_DoubleTB`), Head & Shoulders / Inverse H&S (`patt_HeadShoulders`), Triangle & Wedge (`patt_TriangleWedge`)

### I6 Smart Money Concepts (6 plugins)
- BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD change point, HMM regime classification

### I6 Cross-Timeframe Confluence (1 plugin)
- Trend/structure/regime/pattern alignment scoring across 1m/5m/15m/1h

### I7 Trading Setups — Phase 1+2+Phase0 (9 plugins)
- Phase 1: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion
- Phase 2: VWAPDeviation (2σ mean-reversion, VWAP T1/1σ-band T2), MomentumBreakout (triple-gate: ROC+vol+structure break), LiquidityHunt, SupplyDemandSetup
- **Phase 0 — GARCH/Kalman quality gates** (wired into 3 plugins, 2026-02-22):
  - MeanReversion: `abs(kalman_price_position) < 1.0σ` → no signal (price too near Kalman fair value)
  - VWAPDeviation: dynamic sigma threshold via `garch_vol_regime` — regime 0/1: 2.0σ, regime 2: 2.5σ, regime 3: 3.0σ
  - SqueezeExpansion: hard block when `garch_vol_regime == 3` (extreme vol, top 5th percentile)
- Regime-adaptive setup detection with signal.v1 schema
- ATR-based stop/target placement, confluence-weighted confidence scoring

### I7 Signal Aggregation — Phase 1.5 (4 components)
- **Signal Aggregator** (`src/intelligence/trading/aggregator.py`) — Rules-based conflict resolution with setup priority
- **Signal Ledger** (`src/intelligence/trading/signal_ledger.py`) — Repository for signal_ledger hypertable (insert/update/query)
- **Lifecycle Tracker** (`src/intelligence/trading/lifecycle_tracker.py`) — Pure-function state machine (pending→active→exit) with P&L
- **Position Sizer** (`src/intelligence/trading/position_sizer.py`) — Risk-based contract calculation

## Development Standards

### Primary Instruments (23 contracts)
**Equity Index Futures:** ES (S&P 500), NQ (Nasdaq), RTY (Russell 2000), YM (Dow)
**Energy:** CL (Crude Oil WTI), BZ (Brent Crude), NG (Natural Gas)
**Metals:** GC (Gold), SI (Silver), HG (Copper), PL (Platinum)
**Interest Rates:** ZN (10-Year T-Note), ZF (5-Year T-Note), ZB (30-Year T-Bond), ZT (2-Year T-Note), SR1 (SOFR 1-Month)
**Volatility:** VX (VIX Futures)
**Agriculture:** ZS (Soybeans), ZC (Corn), ZW (Wheat)
**FX/Currencies:** 6E (Euro FX), 6J (Japanese Yen)
**Crypto:** BTC (Bitcoin Futures)

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
- **IBKR**: Tick list `"233"` for futures. Unique client IDs (35+ range). VIX futures symbol is "VX" (not "VIX"). All ib_insync logic is isolated to `src/providers/ibkr.py`.
- **Instruments**: `Instrument` and `AssetClass` in `src/core/models.py` are the canonical types. `IBKRContract` is a deprecated alias (`IBKRContract = Instrument` in settings.py).
- **Mock gotcha**: Use `isinstance(val, (int, float))` not `if val` when checking numeric fields — MagicMock is truthy and `float(MagicMock())` returns 1.0.
- **Plugin tier lists — single source of truth**: `TIER_I1` … `TIER_I7` (plus `TIER_SMC`) constants in `src/intelligence/register_plugins.py` are the canonical lists. Services import them — do NOT define local string lists. Services call `registry.validate_tier()` at startup, which hard-crashes if any name is missing from the registry. Adding a new plugin: (1) register it in `register_all_plugins()`, (2) add it to the appropriate `TIER_*` constant — done everywhere automatically. Plugin names: use `grep 'name: str ='` to confirm exact value (`"ind_ParabolicSAR"`, `"smc_HMMRegime"`, etc.).
- **TimescaleDB aggregates**: `market_data_5m` and `market_data_15m` continuous aggregate views exist (migration 008). Query them like tables for higher-TF data; Python `aggregate_1m_to_tf()` is deleted.
- **Plugin protocol**: All plugins use `PatternPlugin` protocol. Register via `registry.register_indicator()` or `registry.register_pattern()` in `register_plugins.py`. Access via `registry.indicators` / `registry.patterns` (not private `_indicators`).
- **Git worktrees**: Use `git -C /absolute/path/to/worktree` — never relative `.worktrees/path` (gitignored, silently resolves to parent repo).
- **Pytest**: Use `.venv/bin/pytest` not `python -m pytest` (no module). Integration tests have pre-existing failures needing live infra — only unit tests are CI-clean.
- **References**: Stream schemas: `docs/architecture/stream-schemas.md`. Intelligence tiers: `docs/architecture/intelligence-tiers.md`.

## Environment Variables

```bash
INDICAGENT_ENV="development"    # development, staging, production
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
REDIS_URL="redis://localhost:6379/0"
IBKR_HOST="10.0.0.33"          # LAN: Windows host IP (set in .env)
IBKR_PORT=7497                 # TWS paper trading
IBKR_CLIENT_ID=35              # Unique client ID (35+ range)
OLLAMA_BASE_URL="http://localhost:11434"  # Local LLM inference (Docker)
OLLAMA_DEFAULT_MODEL="qwen3:8b"           # Default model for I8 AI tier
OPENROUTER_API_KEY="your_key"             # Cloud AI fallback (optional)
```

## Current Development Status

**Infrastructure:** Production-ready — IBKR collection, Redis streams, indicator calculations
**Plugin System:** 57 registered (23 indicators + 34 patterns/structure/context/smart_money/trading) + 4 aggregation components
**Test Status:** 551 unit tests passing, 0 ruff errors
**Pipeline:** I1 → I3 → I4 → I5 → SMC → I6 → I7 → Redis → SSE → Dashboard (fully wired)

### Intelligence Tiers
- **I1 Indicators** — 23 plugins with incremental compute_next() — WORKING
- **I2 Composites** — Crossovers, slopes, distances — WORKING
- **I3 Structure** — 3 plugins (swing, S/R, trend) — WORKING
- **I4 Context** — 5 plugins (vol regime, trend regime, momentum, GARCH vol, Kalman trend) — WORKING
- **I5 Patterns** — 8 plugins (RSI div, BB squeeze, vol div, confluence, trend confluence, Double Top/Bottom, Head & Shoulders, Triangle/Wedge) — WORKING
- **I6 Smart Money** — 6 plugins (BOS/CHoCH, FVG, OB, sweeps, BOCPD, HMM) — WORKING
- **I6 Confluence** — 1 plugin (cross-timeframe alignment) — WORKING
- **I7 Trading Outputs** — 9 plugins (Phase 1: TrendFollowing, MeanReversion, LiqSweepReclaim, MTFAlignment, SqueezeExpansion; Phase 2: VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup) — WORKING
- **I7 Signal Aggregation** — Phase 1.5: aggregator, signal ledger, lifecycle tracker, position sizer — WORKING
- **I7 Signal Orchestrator** — `SignalOrchestratorService`: runs 9 I7 plugins per bar, aggregates, persists all signals to `signal_ledger`, tracks lifecycle — WORKING (data collection active)
- **Dashboard Panel** — SignalPanel (per-symbol) + NarrativePanel (global AI feed) wired to SSE (`signals:aggregated` + `narratives:` streams) — WORKING
- **I8 AI Intelligence** — AINarrativeService: selected signals → Ollama qwen3:8b → human-readable narratives → narratives:SYMBOL:TF stream — WORKING

### Local LLM Infrastructure (Ollama)
5 models available at `http://localhost:11434` (native process, not Docker):
| Model | Size | Family | Quant | Notes |
|-------|------|--------|-------|-------|
| `qwen3:8b` | 5.2 GB | Qwen3 | Q4_K_M | **Default** — best quality, built-in thinking mode |
| `gemma3n:e4b` | 7.5 GB | Gemma3n | Q4_K_M | Google, good general reasoning |
| `qwen3:4b` | 2.5 GB | Qwen3 | Q4_K_M | Fast variant, thinking mode |
| `phi4-mini:3.8b` | 2.5 GB | Phi4 | Q4_K_M | Microsoft, fast inference |
| `deepscaler:1.5b` | 3.6 GB | Qwen2 | F16 | Smallest, math/reasoning focused |

**Note:** Qwen3 models use thinking mode by default — `content` field may be empty if `num_predict` is too low. Use `/no_think` prefix or set `num_predict` ≥ 500 for reliable output. Use the chat API (`/api/chat`) for multi-turn, generate API (`/api/generate`) for single-shot.

### Development Priorities
1. **I7 Phase 2 continued** — 7 more setup plugins remaining (Supply/Demand zones, Gap Analysis, Candlestick patterns, Session Extremes, etc. — see `docs/roadmap/MASTER_ROADMAP.md` Phase 4)
2. **ML scoring model** — Replace rules-based aggregator once 500+ signals collected in `signal_ledger` (~17 days at 30/day)

### Completed Phases
- **LG-1** — LangGraph event-driven workflows, circuit breakers
- **CQ-1** — Code quality: 1,323 lint fixes, formatting
- **PR-2** — Production: test runner, incremental_manager, parallel services, SSE
- **PI-1** — 16 indicator plugins with hybrid processing
- **T2** — Tier 2 refactor: calculations.py + redis_streams_manager.py → mixins
- **I3** — Market structure: 3 plugins
- **I4** — Context classification: vol regime, trend regime, momentum (3 original plugins)
- **I4-GARCH** — ctx_GARCHVolatility: GARCH(1,1) conditional vol forecast, 4 outputs (sigma, vol_ratio, vol_regime, shock)
- **I4-Kalman** — ctx_KalmanTrend: 1D Kalman filter (local level model), 7 outputs (trend, slope, price_position, uncertainty, upper, lower, gain), optional GARCH-adaptive R, 9 new tests
- **I5** — Pattern detection: 4 plugins
- **FH** — Foundation hardening: shared utils, temporal metadata, continuous scores
- **SMC** — Smart money: 6 plugins (BOS/CHoCH, FVG, OB, sweeps, BOCPD, HMM regime)
- **I6** — Cross-timeframe confluence: 1 plugin with intelligence_cache
- **Cleanup** — ~7,500 lines dead code removed across three rounds
- **Deps** — pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0, Next.js 15.5
- **I7-P1** — Trading setups Phase 1: 5 plugins, signal schema, SSE wiring, 35 new tests
- **I7-P1.5** — Signal aggregation: rules-based aggregator, signal ledger hypertable, lifecycle tracker, position sizer, 45 new tests
- **I7-SignalOrch** — SignalOrchestratorService: full bar→plugin→aggregate→persist→lifecycle pipeline, 19 new tests, intelligence stream enriched with OHLCV
- **I8-Narrative** — AINarrativeService: Ollama qwen3:8b synthesis, 9 new tests, narratives stream, stable consumer group, finally-xack pattern
- **I5-Charts** — 3 chart pattern plugins (DoubleTB, HeadShoulders, TriangleWedge): TDD with phantom-peak-aware pair/triplet iteration, dual lower trendline selection, 17 new tests
- **Track-A-I1** — 6 new I1 indicators (ParabolicSAR, StochRSI, CMF, Aroon, ChandelierExit, HistoricalVolatility), all incremental, 54 new tests
- **ServiceSep** — Service separation: indicator_service (all 23 I1 plugins), market_analysis_service (I3→I6), signal_generator_service (I7), signal_tracker_service (lifecycle); retired 3 old services; 9 new tests
- **Dashboard-Panel** — SSE wiring for signals:aggregated + narratives: streams, SignalPanel + NarrativePanel React components, 6 new tests
- **I7-P2** — VWAPDeviation + MomentumBreakout setup plugins, ROC_PPO added to I1_PLUGINS, 16 new tests
- **DataLayer** — DataProvider protocol, IBKRProvider (wraps all ib_insync), Instrument model, IBKRFetcher+aggregate_1m_to_tf deleted, TimescaleDB 5m/15m continuous aggregates, 17 new tests
- **I7-Phase0** — GARCH/Kalman quality gates wired into 3 I7 plugins: MeanReversion (Kalman displacement gate), VWAPDeviation (dynamic sigma via garch_vol_regime: 2.0/2.5/3.0σ), SqueezeExpansion (hard block at regime=3), 9 new tests (542→551)

## Key References

**Status & Planning:**
- `docs/STATUS.md` — Development status, ranked priorities, and completed phases
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
