# CLAUDE.md

Version: 5.21.0
Last Updated: 2026-03-13
Status: I1-I8 pipeline complete — 101 plugins + 2 aggregation components + feature store + typed intelligence bus, 1659 passing, 167 ruff errors (E501 line-too-long, 64 fixable with --fix), 24 contracts

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
- **Never drop data that could contain signal.** Storage is the cheapest thing we own. Retention policies are for log files and legacy garbage — not intelligence data. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered, and you cannot discover patterns you didn't know to look for at collection time. The only data we drop is confirmed-unused legacy tables with no signal value.

Apply this framing when: designing new features, choosing between approaches, deciding what to log, evaluating model/strategy performance, or questioning whether something is "good enough."

# IndicAgent Market Intelligence Platform

Real-time market intelligence platform with plugin-native architecture, LangGraph event-driven workflows, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

| Level | Location | Description |
|-------|----------|-------------|
| **Ideas** | `.planning/IDEAS.md` | Rough bullet captures |
| **Ideas (detailed)** | `docs/ideas/*.md` | Context, trade-offs, open questions |
| **Ideas catalog** | `docs/ideas/IDEAS-INDEX.md` | **Primary lookup** for all research ideas, status, priority, search tags |
| **TradeAgent vision** | `docs/ideas/tradeagent-vision.md` | Autonomous trading app (separate repo): agents, broker-agnostic execution, learning, HITL, guardrails, dashboards. Consumes IndicAgent + QualAgent signals. |
| **QualAgent vision** | `docs/ideas/qualagent-vision.md` | Standalone qualitative intelligence platform (separate repo): macro regime, COT, prediction markets, news NLP, sentiment, QualScore, quantamental feedback loop. Build deferred. |
| **DerivAgent vision** | `docs/ideas/derivagent-vision.md` | Derivatives intelligence + autonomous options execution platform (separate repo, name confirmed): vol surface, GEX, VANNA/CHARM, VRP, skew, term structure + agentic strategy selection, multi-leg execution, Greeks management, lifecycle, learning loop. Build deferred. |
| **Platform architecture** | `docs/ideas/platform-architecture.md` | Unified platform architecture across all four products: hot/warm/cold data spine, canonical stream namespace, cross-product signal flow, portfolio/risk management, trade execution, strategy bots/automation. |
| **PrimeAgent vision** | `docs/ideas/primeagent-vision.md` | Portfolio management product (name confirmed): unified P&L across all execution products, portfolio Greek aggregation, capital allocation, Kelly sizing inputs, performance attribution by source/regime, multi-account/SMA/fund management. |
| **AegisAgent vision** | `docs/ideas/aegisagent-vision.md` | Independent risk management product (name confirmed): VaR, drawdown enforcement, margin monitoring, stress testing, pre-trade check protocol, emergency halt. Override authority over all execution products. Required before real capital deployed at scale. |
| **Tech stack** | `docs/ideas/tech-stack.md` | Stack decisions with reasoning: Redpanda vs DragonflyDB, pgvector, TimescaleDB consolidation strategy, migration timing, decision log. Living document — update when stack decisions are made. |
| **Renaissance framing** | `docs/ideas/renaissance-framing.md` | Philosophical and architectural framing of the entire product family through the Jim Simons / Medallion lens: all 10 principles mapped to platform decisions, the VRP as primary edge, unified model over siloed strategies, learning machine, compounding insight. |
| **Analysis** | `docs/plans/*.md` | Design docs and implementation plans — output of the brainstorming + writing-plans skill chain |
| **Backlog** | `.planning/ROADMAP.md` → `## Backlog` | Milestone-scale features |
| **Todos** | `.planning/todos/pending/` | Fixes, refactors, small improvements |
| **Roadmap** | `.planning/ROADMAP.md` | Current milestone phases (GSD-managed) |
| **Plans** | `.planning/phases/*/PLAN.md` | Detailed TDD implementation plans |

> **NOTE:** `.planning/IDEAS.md` is not defunct — it feeds GSD planning discovery. Both `.planning/IDEAS.md` and `docs/ideas/IDEAS-INDEX.md` should be kept in sync. When planning, check both sources.

> **Document graduation rule:** `docs/ideas/` is for research and open questions — things not yet ready to build. `docs/plans/` is the output of the brainstorming + writing-plans skill chain. Once an implementation plan lands in `docs/plans/`, add it to the ROADMAP Backlog immediately — that's the trigger to not lose it. `/gsd:plan-phase` then uses the `docs/plans/` doc as research context when creating the phase PLAN.md files.

Use `/gsd:add-todo` for implementation tasks. Use ROADMAP Backlog for milestone-scale features. GSD skills (`/gsd:plan-phase`, `/gsd:execute-phase`) take over from there.

## Required Workflows

### Pre-Commit Quality Gate (Mandatory)
Before committing: `/simplify` then `/coderabbit:code-review`.

### Post-Milestone Housekeeping
`git push origin main`, push tag (`git push origin vX.Y`), `/gsd:cleanup`, update README stats.

### Feature Development (any new plugin, service, or significant change)
**Mandatory skill chain — do not skip steps:**
1. `brainstorming` — design approval → `docs/plans/YYYY-MM-DD-<topic>-design.md`
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
- `sudo systemctl {status|restart|start} indicagent-{tws,indicator,market-analysis,signal-generator,signal-lifecycle,ai-narrative,feature-writer,llm-writer,api}`
- `journalctl -u indicagent-<name> -f` — live logs
- Metrics ports: indicator :9109, signal-gen :9112, ai-narrative :9113, market-analysis :9114, signal-lifecycle :9115, feature-writer :9116, llm-writer :9117

**Pipeline Reset** (housekeeping + fetch + replay — single entry point): `.venv/bin/python production/scripts/pipeline_reset.py [--dry-run|--keep-ohlcv|--clear-llm] [--symbols SYM,SYM]`
— TF depths: 1m=14d named, 5m=90d, 15m=180d, 1h=365d, 1d=2555d (7yr) continuous-adj. Pauses at stop/start boundaries and prints sudo commands to run.
**Gap-fill** (fetch + replay only missing days — no full reseed): `--days N` caps ALL TF fetch depths at N days and limits replay to the same window. Safe: `ON CONFLICT DO NOTHING` on both `intelligence_features` and `signal_ledger`.
```bash
.venv/bin/python production/scripts/historical_backfill.py --fetch-only --symbols SYM,SYM --days 2
.venv/bin/python production/scripts/historical_backfill.py --replay-only --symbols SYM,SYM --days 2
```
**Direct run (debug only):** `.venv/bin/python services/<name>_service.py` · API: `uvicorn src.api.main:app`

## Architecture Overview

```
Layer 4: AI Intelligence (I8)              -> LLM analysis, Ollama qwen3.5:9b
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
| Indicator Service | `indicagent-indicator` | I1: 24 indicators → `indicators:SYMBOL:TF` | :9109 |
| Market Analysis | `indicagent-market-analysis` | I3→I6 pipeline → `intelligence:SYMBOL:TF` | :9114 |
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger`; needs ~50 live 1m bars (~50 min) warmup after restart before signals fire | :9112 |
| Signal Lifecycle | `indicagent-signal-lifecycle` | Zone-aware lifecycle: activation, MAE/MFE, 8-class outcome | :9115 |
| AI Narrative | `indicagent-ai-narrative` | I8: LLM → `narratives:SYMBOL:TF` | :9113 |
| Feature Writer | `indicagent-feature-writer` | Redis → `intelligence_features` batch writer | :9116 |
| LLM Writer | `indicagent-llm-writer` | `llm_calls:stream` → `llm_calls` hypertable + outcome back-fill + score cache | :9117 |
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
- `signals:SYMBOL:TF:aggregated` — selected I7 signal (direction=0 = terminal/resolved event)
- `narratives:SYMBOL:TF` — I8 AI narrative
- `llm_calls:stream` — every LLM call (success + failure + counterfactual); maxlen=500
- `llm_outcomes:stream` — signal lifecycle exits with outcome/pnl_r/mae/mfe; maxlen=200

### Hot/Warm/Cold Tiers
```
Hot:  IBKR TWS → DragonflyDB Streams → Services          (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV (backfill only; keep forever — ground truth)
- `intelligence_features` — full feature vectors per bar incl. i7/i8 JSONB (ML training dataset; keep forever)
- `signal_ledger` — I7 signals + lifecycle outcomes; JOIN via `(symbol, feature_ts, feature_tf)` (keep forever)
- `llm_calls` — full LLM audit log per call; outcome back-filled by `llm_writer_service` (keep forever)
- `llm_model_scores` — per-model win rate / avg pnl_r / p-value; refreshed every 15 min
- `setup_performance` — per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); drives aggregator `perf_multiplier`; only rows with `sample_size >= 30` are written (FEED-02 gate)
- Aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`

### TimescaleDB Gotchas
- **DB shell:** `docker exec timescaledb psql -U postgres -d indicagent` — container is `timescaledb`
- **VACUUM:** Cannot run inside a transaction block — use a standalone `psql -c "VACUUM ..."` command
- **Autovacuum on hypertables:** `ALTER TABLE hypertable SET (autovacuum_...)` only applies to new chunks. Cover existing chunks by iterating `timescaledb_information.chunks`: `FOR r IN SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks WHERE hypertable_name = '...' AND hypertable_schema = 'public' LOOP EXECUTE format('ALTER TABLE %I.%I SET (...)', r.chunk_schema, r.chunk_name); END LOOP` — use `record` type (not `text`) to avoid ambiguous column name conflicts with `chunk_name`
- **pg_stat_statements:** Enabled (2026-03-05). Slow query analysis: `SELECT calls, round(mean_exec_time::numeric,2) AS mean_ms, query FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10`
- **`pg_stat_user_indexes.idx_scan` is always 0 for hypertable parents** — chunk-level indexes are tracked separately. Never use idx_scan=0 to identify unused indexes on hypertables; use pg_stat_statements and EXPLAIN instead.
- **`pg_class` shows near-zero size for hypertable parents** — use `hypertable_size('table')` for real sizes and `timescaledb_information.hypertables` for num_chunks.
- **Applying psql migrations via `docker exec`**: `docker exec timescaledb psql ... -f /dev/stdin <<'EOF'` does NOT work. Always `docker cp file.sql timescaledb:/tmp/file.sql` then `docker exec timescaledb psql -U postgres -d indicagent -f /tmp/file.sql`.

## Plugin System

101 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues.
- **CodeRabbit on main**: `coderabbit review --plain -t all` fails with "no merge base" when on main. Use `-t uncommitted` instead.


### Key Rules

**Core Patterns**
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **API route Settings cache**: `_resolve_contract()` in API routes must use `@lru_cache(maxsize=1)` on `_get_settings()` — not `Settings()` fresh per call. See `sse.py` for the canonical pattern.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests are CI-clean; integration requires live infra.
- **Ruff**: always run `.venv/bin/ruff check .` from project root (not absolute paths).

**Stream & Consumer Groups**
- **Consumer groups**: use `ensure_consumer_group_with_reset(redis_client, stream, group)` from `src/core/stream_utils`. Gotcha: `xgroup_create(..., "$")` silently fails when group exists → stale position → processes old backlog. Fix in `except`: call `xgroup_setid(stream, group, "$")` to force-reset.
- **Redis stream booleans**: serialize as `"1"`/`"0"` (not `"true"`/`"false"`), parse with `Number(payload.field) > 0` — matches `vol_expanding`, `bb_squeeze` pattern in `use-market-stream.ts`.

**Service & Test Patterns**
- **Services**: graceful SIGINT/SIGTERM, drain queues, `await` Redis close, idempotent consumer groups.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise service silently fails mid-test with a misleading error.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

**Data & Database**
- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **`bar_close_price` implicit**: no need to store in `signal_ledger` — JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` gives full bar OHLCV including close price.

**Signal Logic**
- **Terminal event payload**: `_publish_terminal_event` sends both `status` and `outcome` fields (identical values). Dashboard must read `payload.outcome` — `payload.status` works today but is semantically wrong and fragile if the two ever diverge.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"` are raw string literals across `signal_ledger.py`, `lifecycle_tracker.py`, `signal_generator_service.py`, `signal_lifecycle_service.py` — no enum. Avoid adding new status comparisons without consolidating.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts — raw `signals` never get `adjusted_rank` set. If `active` is derived from raw `signals`, `perf_weights` have zero effect on winner selection (only on `all_ranked` ordering). Always derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]`.

**External Systems**
- **IBKR**: VIX=`"VX"`, client IDs 35+. All ib_insync in `src/providers/ibkr.py` only. See `src/providers/CLAUDE.md` for asset-class details.
- **DragonflyDB**: No Redis modules (`TS.*`, RediSearch unavailable) — use TimescaleDB for time series. No `--config`/`--flagfile` flag — pass all settings as CLI args only.
- **Redis CLI**: `redis-cli` not installed — test/debug with `.venv/bin/python -c "import redis; print(redis.Redis().ping())"` or `redis.Redis().xlen(key)`.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.

**Dashboard**
- **Dashboard 1s re-render tick**: `signal-card.tsx` calls `setInterval(1s)` via `useFormattedTimestamp` — any derived values (formatted strings, timestamps) must use `useMemo` to avoid per-second recomputation.
- **`format.ts` timing utils**: `fmtTimeHMS(iso)` → `HH:MM:SS` or null (guards invalid dates); `fmtLagSeconds(lagS)` → `"+1.2s"` or null (guards NaN).
- **`intelligence_i7` SSE domain**: `intelligence_i7:SYMBOL:TF` stream is subscribed in `_build_stream_list()` (alongside `intelligence:`); event name is `signal_scorecard`. Check must appear before `intelligence:` startswith check to prevent shadowing.
- **`signal_scorecard` event payload**: `{"ts": "...", "symbol": "ES", "tf": "1m", "data": "[{...}]"}` where `data` is a JSON-encoded string of `RankedSignal[]`. Parse with `JSON.parse(String(payload.data || "[]"))`.
- **`GET /api/signals/recent`**: `?symbol=&timeframe=&limit=` — returns `signal_ledger` rows with `setup_performance` LEFT JOIN, ordered by `computed_at DESC`. Drill panel fetches on mount and merges with SSE history deduplicated by `signal_id` (SSE version wins on conflict).

## System Access

- **Sudo password:** `!123Angelina` — `sudo-rs` (Rust sudo) does NOT support `-S` stdin. Ask user to run sudo commands in their terminal directly.

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `REDIS_URL`, `IBKR_HOST=10.0.0.33`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3.5:9b`

## Current Status

**Tests:** 1613 passing (Phase 28: +110 new tests across phases 27–28)
I1→I2→I3→I4→I5→SMC→I6→I7→I8 fully wired + feature store + CIS aggregator + signal gate + second-derivative intelligence + CIS data repair infrastructure + signal lifecycle stream events + full dashboard (Signal Scorecard, DB signal history, GARCH/Kalman I4, SMC detail, tier tooltips)
**v1.7 SHIPPED 2026-03-12** — see `.planning/ROADMAP.md`

## Roadmap Position

- v1.0 SHIPPED 2026-02-28 — milestone archived (`de075f7`), tagged `v1.0`
- v1.1 SHIPPED 2026-03-01 — milestone archived, tagged `v1.1`
- v1.2 SHIPPED 2026-03-02 — milestone archived, tagged `v1.2`
- v1.3 SHIPPED 2026-03-04 — milestone archived, tagged `v1.3`
- v1.4 SHIPPED 2026-03-07 — milestone archived (`de075f7`), tagged `v1.4`
- v1.5 SHIPPED 2026-03-07 — milestone archived (`c927b3e`), tagged `v1.5`
- v1.6 SHIPPED 2026-03-10 — milestone archived, tagged `v1.6`
- **v1.7 SHIPPED 2026-03-11** — milestone archived, tagged `v1.7`

- Next: `/gsd:new-milestone` to define v1.8

## Key References

- `.planning/ROADMAP.md` — phases, backlog
- `.planning/IDEAS.md` — rough captures
- `docs/plans/` — design docs and implementation plans (brainstorm + writing-plans output)
- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- IBKR TWS: https://interactivebrokers.github.io/tws-api/
- TimescaleDB: https://docs.timescale.com/
- DB Maintenance Runbook: `docs/reference/db-maintenance.md` — weekly slow-query review, vacuum health, monthly storage audit; automated weekly ANALYZE via TimescaleDB job 1020 (Sundays 02:00 UTC)
