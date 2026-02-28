# CLAUDE.md

Version: 5.5.0
Last Updated: 2026-02-26
Status: I1-I8 pipeline complete — 57 plugins + 4 aggregation components + feature store + typed intelligence bus, 602 tests, 23 contracts

This file provides guidance to Claude Code when working with this repository.

# IndicAgent Trading Intelligence Platform

Real-time futures trading intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

Ideas and plans live in a 6-level hierarchy:

```
IDEAS → ANALYSIS → BACKLOG → TODOS → ROADMAP → PLANS
```

| Level | Location | Description |
|-------|----------|-------------|
| **Ideas** | `.planning/IDEAS.md` | Rough captures — no structure required, no commitment |
| **Analysis** | `.planning/analysis/*.md` | Architecture decisions, trade-offs, design discussions |
| **Backlog** | `.planning/ROADMAP.md` → `## Backlog` | Milestone-scale features that would become their own phase |
| **Todos** | `.planning/todos/pending/` | Implementation tasks: fixes, refactors, small improvements — bundled into existing phases |
| **Roadmap** | `.planning/ROADMAP.md` | Current milestone phases (GSD-managed) |
| **Plans** | `.planning/phases/*/PLAN.md` | Detailed TDD implementation plans (GSD-managed) |

**When to file where:** Capture rough ideas in IDEAS.md immediately. Design discussions that produce decisions go to `analysis/`. Use `/gsd:add-todo` for implementation-level tasks (bug fixes, refactors, small improvements) — bundled into phase plans when relevant. Use ROADMAP.md `## Backlog` for milestone-scale features that would become their own phase (new service, ML model, auth layer). GSD skills (`/gsd:plan-phase`, `/gsd:execute-phase`) take over from there.

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

### Todo Management
- `/gsd:add-todo` — capture implementation tasks during a session
- `/gsd:check-todos` — select a todo and route to work
- `/gsd:review-todos` — review all todos: close done/won't-do, update stale content

## Core Commands

> Full command reference: `docs/cheatsheet.md`

**Tests:** `.venv/bin/pytest tests/unit/ -v` · lint: `.venv/bin/ruff check . --fix` · format: `.venv/bin/black .`
**Dashboard dev:** `cd dashboard && npm run dev`
**Services** (all systemd-managed, `Restart=always`):
- `sudo systemctl {status|restart|start} indicagent-{tws,indicator,market-analysis,signal-generator,signal-tracker,ai-narrative,feature-writer,api}`
- `journalctl -u indicagent-<name> -f` — live logs
- Metrics ports: indicator :9109, signal-gen :9112, ai-narrative :9113, market-analysis :9114, signal-tracker :9115, feature-writer :9116

**Backfill:** `.venv/bin/python production/scripts/historical_backfill.py [--fetch-only|--replay-only] [--days N] [--symbols SYM,SYM]`
**Direct run (debug only):** `.venv/bin/python services/<name>_service.py` · API: `uvicorn src.api.main:app`

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
| Feature Writer | `indicagent-feature-writer` | Redis → `intelligence_features` batch writer | :9116 |
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
- **DragonflyDB**: Does not support Redis modules — `TS.*` (TimeSeries) and RediSearch native module commands are unavailable. Use TimescaleDB for time series storage.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Plugin protocol**: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `REDIS_URL`, `IBKR_HOST=10.0.0.33`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3:8b`

## Current Status

**Tests:** 602 passing, 0 ruff errors
**Pipeline:** I1→I3→I4→I5→SMC→I6→I7→I8 fully wired + feature store (Phases 0–6 in progress)
**Roadmap:** See `.planning/ROADMAP.md` — Phase 7 (CIS) planned, ready to execute

### Phase 6 Status (dashboard-connected)
- ✅ 06-01: TimeframeBuilder dedup + per-TF min_history + `currency="USD"` qualify fix + Stochastic InputSpec wildcard
- ✅ 06-02: SSE `event.tf` bug fixed, session tracking, Price Hero bid/ask/last + dual % change + flash animation
- ✅ 06-03: SmartMoneyPanel extended with HMM regime + BSL/SSL liquidity zones
- ✅ 06-04 (partial): Dashboard UX — drill panel reads `intelligenceByTf[tf]`, signal panel shows entry/SL/TP/RR, TF-matched narrative cards, per-TF signals (1m/5m/15m/1h), AI narrative consumer group backlog fix (`"$"` + `xgroup_setid`)
- ⏸ 06-04: Human verification skipped — proceeding to Phase 7 CIS
- ❌ `indicagent-timeframes.service` — legacy service; import fails (`src.data` not `src.core`); non-blocking

### Phase 7 Status (composite-intelligence-score)
- ⏳ 07-01: 5 new I7 plugins (CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition) — Wave 1
- ⏳ 07-02: CIS bucket scorer + aggregator replacement + signal_ledger schema additions — Wave 2
- ⏳ 07-03: weight_updater.py + cis_weights table + bootstrap→learned transition — Wave 3
- ⏳ 07-04: at_limit / at_pullback entry types in trade_framer.py — Wave 2 (parallel with 07-02)
- Design doc: `docs/plans/2026-02-27-composite-intelligence-score-design.md`

### ai_narrative_service key facts
- Consumer group: stable `"ai_narrative"`, starts at `"$"` (skips backlog on restart)
- Timeframes: `["1m", "5m", "15m", "1h"]` — matches signal_generator_service
- Ollama timeout: 120s (qwen3:8b needs ~90s on CPU at num_predict=500)

### Local LLM (Ollama — native process, not Docker)
`qwen3:8b` (default), `gemma3n:e4b`, `qwen3:4b`, `phi4-mini:3.8b`, `deepscaler:1.5b`
**Gotcha:** Qwen3 uses thinking mode by default — `content` may be empty if `num_predict` < 500. Use `/no_think` prefix or set `num_predict ≥ 500`.

## Key References

**Planning (start here):**
- `.planning/ROADMAP.md` — current milestone phases, backlog
- `.planning/IDEAS.md` — rough idea captures
- `.planning/analysis/` — architecture decisions and design discussions

**Architecture:**
- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- `docs/architecture/plugin-registry-and-dag-execution.md`

**External APIs:**
- IBKR TWS: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
