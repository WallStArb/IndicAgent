# CLAUDE.md

Version: 5.11.0
Last Updated: 2026-03-03
Status: I1-I8 pipeline complete — 86 plugins + 2 aggregation components + feature store + typed intelligence bus, 1028 tests, 0 ruff errors, 24 contracts

This file provides guidance to Claude Code when working in this repository.

# IndicAgent Market Intelligence Platform

Real-time market intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

| Level | Location | Description |
|-------|----------|-------------|
| **Ideas** | `.planning/IDEAS.md` | Rough bullet captures |
| **Ideas (detailed)** | `docs/ideas/*.md` | Context, trade-offs, open questions |
| **Analysis** | `docs/plans/*.md` | Design docs, architecture decisions, brainstorming outputs |
| **Backlog** | `.planning/ROADMAP.md` → `## Backlog` | Milestone-scale features |
| **Todos** | `.planning/todos/pending/` | Fixes, refactors, small improvements |
| **Roadmap** | `.planning/ROADMAP.md` | Current milestone phases (GSD-managed) |
| **Plans** | `.planning/phases/*/PLAN.md` | Detailed TDD implementation plans |

Use `/gsd:add-todo` for implementation tasks. Use ROADMAP Backlog for milestone-scale features. GSD skills (`/gsd:plan-phase`, `/gsd:execute-phase`) take over from there.

## Required Workflows

### Pre-Commit Quality Gate (Mandatory)
Before committing: `/simplify` then `/coderabbit:code-review`.

### Post-Milestone Housekeeping
`git push origin main`, push tag (`git push origin vX.Y`), `/gsd:cleanup`, update README stats.

### Feature Development (any new plugin, service, or significant change)
**Mandatory skill chain — do not skip steps:**
1. `brainstorming` — design approval → save to `docs/plans/YYYY-MM-DD-<topic>-design.md`
2. `writing-plans` — TDD implementation plan
3. `executing-plans` — task-by-task with review checkpoints
4. `verification-before-completion` — full test suite + lint
5. `finishing-a-development-branch` — clean git history, decide merge/PR/cleanup

**Do NOT jump straight to coding.** Even "simple" plugins need the brainstorming step.

### Bug Fixes & Debugging
1. `systematic-debugging` — structured investigation before proposing fixes
2. `verification-before-completion` — confirm fix works before committing

### After Major Changes
`revise-claude-md` · `verification-before-completion` · `requesting-code-review`

### Library & Framework Documentation
Use `context7` MCP for FastAPI, SQLAlchemy, LangGraph, pytest, Redis, etc.

### Todo Management
`/gsd:add-todo` · `/gsd:check-todos` · `/gsd:review-todos`

## Core Commands

> Full reference: `docs/cheatsheet.md`

**Tests:** `.venv/bin/pytest tests/unit/ -v` · lint: `.venv/bin/ruff check . --fix` · format: `.venv/bin/black .`
**Dashboard dev:** `cd dashboard && npm run dev`
**Services** (systemd-managed, `Restart=always`):
- `sudo systemctl {status|restart|start} indicagent-{tws,indicator,market-analysis,signal-generator,signal-tracker,ai-narrative,feature-writer,api}`
- `journalctl -u indicagent-<name> -f` — live logs
- Metrics ports: indicator :9109, signal-gen :9112, ai-narrative :9113, market-analysis :9114, signal-tracker :9115, feature-writer :9116

**Backfill:** `.venv/bin/python production/scripts/historical_backfill.py [--fetch-only|--replay-only] [--days N] [--symbols SYM,SYM]`
**Direct run (debug only):** `.venv/bin/python services/<name>_service.py` · API: `uvicorn src.api.main:app`

## Architecture Overview

```
Layer 4: AI Intelligence (I8)              -> LLM analysis, Ollama qwen3:8b
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

**Intelligence Pipeline:**
```
IBKR TWS → indicator_service (I1) → market_analysis_service (I3→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer_service`.

## Key Components

### Active Services
| Service | Unit | Purpose | Metrics |
|---------|------|---------|---------|
| TWS Daemon | `indicagent-tws` | IBKR tick + bar collection | — |
| Indicator Service | `indicagent-indicator` | I1: 23 indicators → `indicators:SYMBOL:TF` | :9109 |
| Market Analysis | `indicagent-market-analysis` | I3→I6 pipeline → `intelligence:SYMBOL:TF` | :9114 |
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger` | :9112 |
| Signal Tracker | `indicagent-signal-tracker` | Signal lifecycle (pending→active→exit) | :9115 |
| AI Narrative | `indicagent-ai-narrative` | I8: LLM → `narratives:SYMBOL:TF` | :9113 |
| Feature Writer | `indicagent-feature-writer` | Redis → `intelligence_features` batch writer | :9116 |
| API | `indicagent-api` | FastAPI + SSE on :8000 | — |

### Core Runtime Files
- `src/core/stream_keys.py` — all Redis stream key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `PLUGIN_METRICS_SAMPLE_RATE`
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)

## Data Flow

### Stream Keys (env-prefixed: `development:` in dev)
- `indicators:SYMBOL:TF` — I1 output
- `intelligence:SYMBOL:TF` — typed IntelligenceEvent (I3→I6 output)
- `signals:SYMBOL:TF:aggregated` — selected I7 signal
- `narratives:SYMBOL:TF` — I8 AI narrative

### Hot/Warm/Cold Tiers
```
Hot:  IBKR TWS → DragonflyDB Streams → Services          (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV (backfill only)
- `intelligence_features` — full feature vectors per bar (ML training dataset)
- `signal_ledger` — I7 signals; JOIN via `(symbol, feature_ts, feature_tf)`
- Aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`

## Plugin System

86 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues.

### Key Rules
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Ruff**: always run `.venv/bin/ruff check .` from project root (not absolute paths).
- **Consumer groups**: use `ensure_consumer_group_with_reset(redis_client, stream, group)` from `src/core/stream_utils`.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests are CI-clean; integration requires live infra.
- **Services**: graceful SIGINT/SIGTERM, drain queues, `await` Redis close, idempotent consumer groups.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`.
- **IBKR**: VIX=`"VX"`, client IDs 35+. All ib_insync in `src/providers/ibkr.py` only. See `src/providers/CLAUDE.md` for asset-class details.
- **DragonflyDB**: No Redis modules (`TS.*`, RediSearch unavailable) — use TimescaleDB for time series.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## System Access

- **Sudo password:** `***REDACTED-SUDO-PASSWORD***`

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `REDIS_URL`, `IBKR_HOST=10.0.0.33`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3:8b`

## Current Status

**Tests:** 1028 passing · **Ruff:** 0 errors ✅
**Pipeline:** I1→I2→I3→I4→I5→SMC→I6→I7→I8 fully wired + feature store + CIS aggregator
**v1.2 complete** · **v1.3 in progress:** Phase 10 (CandlestickPatternSetup) + pipeline timing observability complete — see `.planning/ROADMAP.md`

## Key References

- `.planning/ROADMAP.md` — phases, backlog
- `.planning/IDEAS.md` — rough captures
- `docs/plans/` — design docs and architecture decisions
- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- IBKR TWS: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
