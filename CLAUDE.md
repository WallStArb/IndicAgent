# CLAUDE.md

Version: 5.14.0
Last Updated: 2026-03-05
Status: I1-I8 pipeline complete — 88 plugins + 2 aggregation components + feature store + typed intelligence bus, 1117 tests, 0 ruff errors, 24 contracts

This file provides guidance to Claude Code when working in this repository.

## Decision Framework: What Would Jim Simons Do?

When evaluating any design, feature, or architectural decision, apply this filter:

> **What would Jim Simons and Renaissance Capital demand?**

Renaissance principles that govern this codebase:
- **Instrument everything.** No data point left uncaptured. If it happened, it should be measurable.
- **Let the system run.** Don't override data with intuition. Build the automation, then trust it.
- **Earn the right through proof.** No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Shadow mode first, always.
- **Segment relentlessly.** A rule that works globally is weaker than one that works in a specific regime. Always ask: "under what conditions does this hold?"
- **Degrade gracefully, adapt automatically.** Systems that require manual tuning are fragile. Build feedback loops that self-correct.
- **Data quality over model complexity.** Clean, complete data beats a smarter model on dirty data every time.

Apply this framing when: designing new features, choosing between approaches, deciding what to log, evaluating model/strategy performance, or questioning whether something is "good enough."

# IndicAgent Market Intelligence Platform

Real-time market intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

| Level | Location | Description |
|-------|----------|-------------|
| **Ideas** | `.planning/IDEAS.md` | Rough bullet captures |
| **Ideas (detailed)** | `docs/ideas/*.md` | Context, trade-offs, open questions |
| **TradeAgent vision** | `docs/ideas/tradeagent-vision.md` | Autonomous trading app (separate repo): agents, broker-agnostic execution, learning, HITL, guardrails, dashboards. Consumes IndicAgent + QualAgent signals. |
| **QualAgent vision** | `docs/ideas/qualagent-vision.md` | Standalone qualitative intelligence platform (separate repo): macro regime, COT, prediction markets, news NLP, sentiment, QualScore, quantamental feedback loop. Build deferred. |
| **DerivAgent vision** | `docs/ideas/derivagent-vision.md` | Derivatives intelligence + autonomous options execution platform (separate repo, name confirmed): vol surface, GEX, VANNA/CHARM, VRP, skew, term structure + agentic strategy selection, multi-leg execution, Greeks management, lifecycle, learning loop. Build deferred. |
| **Platform architecture** | `docs/ideas/platform-architecture.md` | Unified platform architecture across all four products: hot/warm/cold data spine, canonical stream namespace, cross-product signal flow, portfolio/risk management, trade execution, strategy bots/automation. |
| **PrimeAgent vision** | `docs/ideas/primeagent-vision.md` | Portfolio management product (name confirmed): unified P&L across all execution products, portfolio Greek aggregation, capital allocation, Kelly sizing inputs, performance attribution by source/regime, multi-account/SMA/fund management. |
| **AegisAgent vision** | `docs/ideas/aegisagent-vision.md` | Independent risk management product (name confirmed): VaR, drawdown enforcement, margin monitoring, stress testing, pre-trade check protocol, emergency halt. Override authority over all execution products. Required before real capital deployed at scale. |
| **Tech stack** | `docs/ideas/tech-stack.md` | Stack decisions with reasoning: Redpanda vs DragonflyDB, pgvector, TimescaleDB consolidation strategy, migration timing, decision log. Living document — update when stack decisions are made. |
| **Renaissance framing** | `docs/ideas/renaissance-framing.md` | Philosophical and architectural framing of the entire product family through the Jim Simons / Medallion lens: all 10 principles mapped to platform decisions, the VRP as primary edge, unified model over siloed strategies, learning machine, compounding insight. |
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
**Pipeline Reset:** `.venv/bin/python production/scripts/pipeline_reset.py [--dry-run|--keep-ohlcv] [--symbols SYM,SYM]`
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
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger`; needs ~50 live 1m bars (~50 min) warmup after restart before signals fire | :9112 |
| Signal Lifecycle | `indicagent-signal-lifecycle` | Zone-aware lifecycle: activation, MAE/MFE, 8-class outcome | :9115 |
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

### TimescaleDB Gotchas
- **DB shell:** `docker exec timescaledb psql -U postgres -d indicagent` — container is `timescaledb`
- **VACUUM:** Cannot run inside a transaction block — use a standalone `psql -c "VACUUM ..."` command
- **Autovacuum on hypertables:** `ALTER TABLE hypertable SET (autovacuum_...)` only applies to new chunks. Cover existing chunks by iterating `timescaledb_information.chunks`: `FOR r IN SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks WHERE hypertable_name = '...' AND hypertable_schema = 'public' LOOP EXECUTE format('ALTER TABLE %I.%I SET (...)', r.chunk_schema, r.chunk_name); END LOOP` — use `record` type (not `text`) to avoid ambiguous column name conflicts with `chunk_name`
- **pg_stat_statements:** Enabled (2026-03-05). Slow query analysis: `SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms, query FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10`

## Plugin System

88 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues.

### Key Rules
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Ruff**: always run `.venv/bin/ruff check .` from project root (not absolute paths).
- **Consumer groups**: use `ensure_consumer_group_with_reset(redis_client, stream, group)` from `src/core/stream_utils`. Gotcha: `xgroup_create(..., "$")` silently fails when group exists → stale position → processes old backlog. Fix in `except`: call `xgroup_setid(stream, group, "$")` to force-reset.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests are CI-clean; integration requires live infra.
- **Services**: graceful SIGINT/SIGTERM, drain queues, `await` Redis close, idempotent consumer groups.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`.
- **IBKR**: VIX=`"VX"`, client IDs 35+. All ib_insync in `src/providers/ibkr.py` only. See `src/providers/CLAUDE.md` for asset-class details.
- **DragonflyDB**: No Redis modules (`TS.*`, RediSearch unavailable) — use TimescaleDB for time series. No `--config`/`--flagfile` flag — pass all settings as CLI args only.
- **Redis CLI**: `redis-cli` not installed — test/debug with `.venv/bin/python -c "import redis; print(redis.Redis().ping())"` or `redis.Redis().xlen(key)`.
- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks don't restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in the test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise the service silently fails mid-test with a misleading error.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"` are raw string literals across `signal_ledger.py`, `lifecycle_tracker.py`, `signal_generator_service.py`, `signal_lifecycle_service.py` — no enum. Avoid adding new status comparisons without consolidating.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

## System Access

- **Sudo password:** `***REDACTED-SUDO-PASSWORD***` — `sudo-rs` (Rust sudo) does NOT support `-S` stdin. Ask user to run sudo commands in their terminal directly.

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `REDIS_URL`, `IBKR_HOST=10.0.0.33`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3.5:9b`

## Current Status

**Tests:** 1182 passing · **Ruff:** 0 errors ✅
**Pipeline:** I1→I2→I3→I4→I5→SMC→I6→I7→I8 fully wired + feature store + CIS aggregator
**v1.3 complete** · **v1.4 in progress:** Quant Foundation (Phase 12 Signal Integrity ✅, Data Completeness, Feedback Loop, Validated Alpha) — see `.planning/ROADMAP.md`

## Key References

- `.planning/ROADMAP.md` — phases, backlog
- `.planning/IDEAS.md` — rough captures
- `docs/plans/` — design docs and architecture decisions
- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- IBKR TWS: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
