# CLAUDE.md

Version: 5.4.0
Last Updated: 2026-02-24
Status: I1-I8 pipeline complete — 57 plugins + 4 aggregation components + feature store + typed intelligence bus, 584 tests, 23 contracts

This file provides guidance to Claude Code when working with this repository.

# IndicAgent Trading Intelligence Platform

Real-time futures trading intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

Ideas and plans live in a 5-level hierarchy:

```
IDEAS → ANALYSIS → BACKLOG → ROADMAP → PLANS
```

| Level | Location | Description |
|-------|----------|-------------|
| **Ideas** | `.planning/IDEAS.md` | Rough captures — no structure required, no commitment |
| **Analysis** | `.planning/analysis/*.md` | Architecture decisions, trade-offs, design discussions |
| **Backlog** | `.planning/ROADMAP.md` → `## Backlog` | Decided but unscheduled; waiting for a phase slot |
| **Roadmap** | `.planning/ROADMAP.md` | Current milestone phases (GSD-managed) |
| **Plans** | `.planning/phases/*/PLAN.md` | Detailed TDD implementation plans (GSD-managed) |

**When to file where:** Capture rough ideas in IDEAS.md immediately — they don't need to be polished. If a design discussion produces a decision (like today's continuous contracts analysis), save it to `analysis/`. When something is ready to build, move it to the Backlog section of ROADMAP.md. GSD skills (`/gsd:plan-phase`, `/gsd:execute-phase`) take over from there.

## Required Workflows

### Feature Development (any new plugin, service, or significant change)
**Mandatory skill chain — do not skip steps:**
1. `brainstorming` — Explore context, clarify requirements, propose approaches, get design approval. Save design to `.planning/analysis/YYYY-MM-DD-<topic>.md`
2. `writing-plans` — Create TDD implementation plan with bite-sized tasks
3. `executing-plans` — Execute plan task-by-task with review checkpoints between batches
4. `verification-before-completion` — Run full test suite + lint before claiming done
5. `finishing-a-development-branch` — Clean git history, decide merge/PR/cleanup

**Do NOT jump straight to coding.** Even "simple" plugins need the brainstorming step to validate design decisions.

### Bug Fixes & Debugging
1. `systematic-debugging` — Structured investigation before proposing fixes
2. `verification-before-completion` — Confirm fix works before committing

### After Major Changes
- `revise-claude-md` — Update this file with session learnings
- `requesting-code-review` — Review own work quality before merge

### Library & Framework Documentation
- Use `context7` MCP for any library/framework question — FastAPI, SQLAlchemy, LangGraph, pytest, Redis, etc.

## Core Commands

### Development Setup
```bash
source .venv/bin/activate
pip install -r requirements.txt

# Infrastructure
# PostgreSQL/TimescaleDB — native process: sudo systemctl start postgresql
# Ollama — native process: ollama serve
# DragonflyDB — Docker only:
cd production && docker compose up -d dragonfly

# Database schema
psql -U postgres -d indicagent -f production/schemas/create_schema.sql
for f in production/migrations/0*.sql; do psql -U postgres -d indicagent -f "$f"; done
```

### System Operations
```bash
# All 8 services are systemd-managed (Restart=always, start on boot)
sudo systemctl status 'indicagent-*'
sudo systemctl restart indicagent-tws          # TWS data daemon
sudo systemctl restart indicagent-indicator    # I1 indicators
sudo systemctl restart indicagent-market-analysis  # I3→I6 pipeline
sudo systemctl restart indicagent-signal-generator # I7 signals
sudo systemctl restart indicagent-signal-tracker   # signal lifecycle
sudo systemctl restart indicagent-ai-narrative     # I8 AI narratives
sudo systemctl restart indicagent-feature-writer   # Redis → intelligence_features writer
sudo systemctl restart indicagent-api              # FastAPI

journalctl -u indicagent-tws -f              # live logs for any service
journalctl -u indicagent-market-analysis -f

# Start all services (e.g. after reboot)
sudo systemctl start indicagent-tws indicagent-indicator indicagent-market-analysis \
  indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative \
  indicagent-feature-writer indicagent-api

# Health / metrics
curl http://localhost:9109/metrics   # Indicator Service (Prometheus)
curl http://localhost:9112/metrics   # Signal Generator
curl http://localhost:9113/metrics   # AI Narrative
curl http://localhost:9114/metrics   # Market Analysis
curl http://localhost:9115/metrics   # Signal Tracker

# Direct invocation (debugging only — normally use systemd)
.venv/bin/python production/daemons/high_frequency_tws_daemon.py --client-id 35
.venv/bin/python services/indicator_service.py
.venv/bin/python services/market_analysis_service.py
.venv/bin/python services/signal_generator_service.py
.venv/bin/python services/feature_writer_service.py
.venv/bin/python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

### Historical Data Backfill
```bash
# Full backfill — fetches multi-TF from IBKR then replays intelligence pipeline
.venv/bin/python production/scripts/historical_backfill.py

# Stage 1 only: IBKR → market_data_ohlcv (requires TWS running at 10.0.0.33:7497)
# Fetches: 1m(35d named), 5m(1yr continuous-adj), 15m(1yr), 1h(2yr), 1d(5yr)
.venv/bin/python production/scripts/historical_backfill.py --fetch-only

# Stage 2 only: DB → I1→I7 pipeline → signal_ledger + intelligence_features
.venv/bin/python production/scripts/historical_backfill.py --replay-only

# Override 1m depth or limit symbols
.venv/bin/python production/scripts/historical_backfill.py --days 60 --symbols ESH6,NQH6
```

### Development & Testing
```bash
.venv/bin/python -m pytest tests/unit/ -v        # Unit tests (584 passing)
.venv/bin/python -m pytest tests/integration/ -v # Integration (requires live Redis + PostgreSQL)
.venv/bin/ruff check . --fix                     # Linting (0 errors on new code)
.venv/bin/black .                                # Formatting
.venv/bin/mypy src/ --ignore-missing-imports     # Type checking
cd dashboard && npm run dev                      # Frontend dev server
```

## Architecture Overview

**Plugin-Native Intelligence Platform** with LangGraph event-driven workflows:

### 4-Layer Intelligence Architecture
```
Layer 4: AI Intelligence (I8)              -> LLM analysis, Ollama qwen3:8b
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

### Intelligence Pipeline
```
IBKR TWS → indicator_service (I1) → market_analysis_service (I3→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

### Typed Intelligence Bus (Phase 1+2)
- **`IntelligenceEvent`** (`src/intelligence/schemas.py`) — canonical Pydantic model; tiered JSONB (i1/i3/i4/i5/smc/i6), versioned, replaces flat string k/v stream messages
- **`intelligence_features`** hypertable — persists every IntelligenceEvent to TimescaleDB; GIN-indexed, 7-day compression; the ML training dataset
- **`feature_writer_service`** — async Redis consumer group `feature_writer:persist` → batch writes to `intelligence_features`

## Key Components

### Active Services (systemd-managed)
| Service | Unit | Purpose | Metrics |
|---------|------|---------|---------|
| TWS Daemon | `indicagent-tws` | IBKR tick + bar collection | — |
| Indicator Service | `indicagent-indicator` | I1: 23 indicators → `indicators:SYMBOL:TF` | :9109 |
| Market Analysis | `indicagent-market-analysis` | I3→I6 pipeline → `intelligence:SYMBOL:TF` | :9114 |
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger` | :9112 |
| Signal Tracker | `indicagent-signal-tracker` | Signal lifecycle (pending→active→exit) | :9115 |
| AI Narrative | `indicagent-ai-narrative` | I8: Ollama → `narratives:SYMBOL:TF` | :9113 |
| Feature Writer | `indicagent-feature-writer` | Redis → `intelligence_features` batch writer | :9115 |
| API | `indicagent-api` | FastAPI + SSE on :8000 | — |

### Data Providers
- `src/providers/ibkr.py` — all ib_insync logic isolated here. `fetch_historical_bars()` supports `continuous=True` for back-adjusted `ContFuture` data (used by backfill for multi-year history)
- **Rule:** No `ib_insync` imports outside `src/providers/ibkr.py`

### Core Runtime
- `src/core/stream_keys.py` — all Redis stream key construction (always use this, never hardcode)
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/intelligence/schemas.py` — `IntelligenceEvent`, `I1Indicators`, `I3Structure`, etc. (canonical typed bus)
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions

## Data Flow

### Stream Keys (env-prefixed: `development:` in dev)
- `indicators:SYMBOL:TF` — I1 indicators output
- `intelligence:SYMBOL:TF` — typed IntelligenceEvent (I3→I6 output)
- `signals:SYMBOL:TF:aggregated` — selected I7 signal
- `narratives:SYMBOL:TF` — I8 AI narrative text
- `development:ticks:SYMBOL:live` — raw ticks from TWS

### Hot/Warm/Cold Tiers
```
Hot:  IBKR TWS → DragonflyDB Streams → Services          (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV bars (1m named + 5m/15m/1h/1d continuous-adjusted)
- `intelligence_features` — full feature vectors per bar (ML training dataset)
- `signal_ledger` — all I7 signals with outcome tracking; JOIN to `intelligence_features` via `(symbol, feature_ts, feature_tf)`
- Continuous aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`

## Plugin System (57 total)

### I1 Technical Indicators (23 plugins) — all incremental `compute_next()`
Trend, Momentum, Volatility, Volume — full list in `src/intelligence/register_plugins.py:TIER_I1`

### I3 Structure (3) · I4 Context (5) · I5 Patterns (8) · I6 SMC (6) · I6 Confluence (1)
GARCH volatility + Kalman trend in I4. BOS/CHoCH, FVG, Order Blocks, HMM regime in I6 SMC.

### I7 Trading Setups (9 plugins) + Aggregation (4 components)
TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup. Signal aggregator, ledger, lifecycle tracker, position sizer.

**GARCH/Kalman quality gates** (Phase 0) wired into MeanReversion, VWAPDeviation, SqueezeExpansion.

### Plugin tier lists — single source of truth
`TIER_I1`…`TIER_I7` constants in `src/intelligence/register_plugins.py`. Services import them — do NOT define local string lists. `registry.validate_tier()` hard-crashes at startup on any missing name.

## Development Standards

### Current Contracts (23 — all H6/J6 front-month as of Feb 2026)
ES, NQ, RTY, YM (equity index) · CL, BZ, NG (energy) · GC, SI, HG, PL (metals) · ZN, ZF, ZB, ZT, SR1 (rates) · VX (volatility) · ZS, ZC, ZW (agriculture) · 6E, 6J (FX) · BTC (crypto)

**Always use `get_active_contracts()` from `src/config/settings.py` — never hardcode symbol lists.**

### Key Rules
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Use `.venv/bin/pytest`. Integration tests require live infra — unit tests are CI-clean.
- **Services**: graceful SIGINT/SIGTERM, drain queues, `await` Redis close, idempotent consumer groups.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`.
- **IBKR**: tick list `"233"` for futures. VIX symbol is `"VX"` (not "VIX"). Client IDs 35+ range. All ib_insync in `src/providers/ibkr.py` only.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Plugin protocol**: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## Environment Variables

```bash
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
REDIS_URL="redis://localhost:6379/0"
IBKR_HOST="10.0.0.33"          # Windows LAN host
IBKR_PORT=7497                 # TWS paper trading port
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_DEFAULT_MODEL="qwen3:8b"
```

## Current Status

**Tests:** 584 unit passing, 0 ruff errors
**Pipeline:** I1→I3→I4→I5→SMC→I6→I7→I8 fully wired + feature store (Phases 0–2 complete)
**Roadmap:** See `.planning/ROADMAP.md` — current milestone is Unified Data Bus (Phases 3–6 remaining)

### Local LLM (Ollama — native process, not Docker)
`qwen3:8b` (default), `gemma3n:e4b`, `qwen3:4b`, `phi4-mini:3.8b`, `deepscaler:1.5b`
**Gotcha:** Qwen3 uses thinking mode by default — `content` may be empty if `num_predict` < 500. Use `/no_think` prefix or set `num_predict ≥ 500`.

## Key References

**Planning (start here):**
- `.planning/ROADMAP.md` — current milestone phases, backlog
- `.planning/IDEAS.md` — rough idea captures
- `.planning/analysis/` — architecture decisions and design discussions

**Architecture:**
- `docs/architecture/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- `docs/architecture/plugin-registry-and-dag-execution.md`

**External APIs:**
- IBKR TWS: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
