# Codebase Structure

**Analysis Date:** 2026-03-11

## Directory Layout

```
indicagent/
├── .planning/                  # GSD phase planning, todos, roadmap
├── .env                        # Environment variables (secrets, not committed)
├── CLAUDE.md                   # Developer reference: tech stack, commands, gotchas
├── README.md                   # Project overview
├── package.json                # Dashboard deps (Next.js, TypeScript)
├── pyproject.toml              # Python project metadata
├── src/                        # Core Python source code
│   ├── api/                    # FastAPI application
│   ├── config/                 # Settings, instrument definitions
│   ├── core/                   # Infrastructure (DB, Redis, stream utils)
│   ├── indicators/             # Legacy indicator modules (kept for compatibility)
│   ├── intelligence/           # Plugin system, schemas, LLM providers
│   ├── observability/          # Prometheus metrics, logging setup
│   └── providers/              # IBKR TWS integration
├── services/                   # Asyncio service entry points (systemd-managed)
│   ├── indicator_service.py    # I1 plugin execution
│   ├── market_analysis_service.py  # I3-I6 plugin execution
│   ├── signal_generator_service.py  # I7 signal aggregation
│   ├── signal_lifecycle_service.py  # Signal activation/exit tracking
│   ├── ai_narrative_service.py      # I8 LLM narratives
│   ├── feature_writer_service.py    # Intelligence feature batch writer
│   ├── llm_writer_service.py        # LLM audit logger
│   └── timeframes_builder_service.py # Legacy multi-TF aggregation
├── dashboard/                  # Next.js frontend (TypeScript, Tailwind)
│   ├── src/
│   │   ├── app/               # Next.js pages (landing, dashboard)
│   │   ├── components/        # React components (signal cards, grids)
│   │   └── lib/               # Utilities (format.ts, hooks)
│   ├── public/                # Static assets
│   └── node_modules/          # npm dependencies
├── tests/                      # Test suites
│   ├── unit/                  # Unit tests (pytest)
│   ├── integration/           # Integration tests (requires live infra)
│   └── e2e/                   # End-to-end tests (if any)
├── production/                # Deployment & infrastructure
│   ├── docker-compose.yml     # PostgreSQL/TimescaleDB, DragonflyDB, Ollama
│   ├── systemd/               # Service unit files (systemd-managed)
│   ├── migrations/            # SQL schema migrations
│   ├── schemas/               # SQL table definitions
│   ├── scripts/               # Operational scripts (backfill, repairs)
│   ├── prometheus.yml         # Prometheus scrape config
│   └── grafana/               # Grafana dashboard definitions
└── docs/                       # Documentation
    ├── ideas/                 # Research ideas, vision docs
    ├── plans/                 # Design docs & implementation plans
    ├── concepts/              # Architecture concepts
    ├── reference/             # Technical references
    └── guides/                # How-to guides
```

## Directory Purposes

**src/api/:**
- Purpose: FastAPI web application for serving indicators, signals, market data
- Contains: Route handlers for `/indicators`, `/signals`, `/market-data`, SSE stream
- Key files: `main.py` (FastAPI app, lifespan), `routes/` (endpoint implementations), `dependencies.py` (shared resources)

**src/config/:**
- Purpose: Application configuration and contract definitions
- Contains: `settings.py` (pydantic-settings with env vars), instrument contracts (ES, NQ, CL, etc.)
- Key files: `settings.py` (single source of truth for all config)

**src/core/:**
- Purpose: Infrastructure and cross-cutting utilities
- Contains: Database manager (PostgreSQL/asyncpg), Redis streams manager, consumer group setup, plugin state management
- Key files:
  - `database_manager.py` — connection pooling, hypertable access
  - `stream_keys.py` — ALL stream key construction (env-prefixed, maxlen policies)
  - `stream_utils.py` — consumer group helpers, idempotent xgroup_create
  - `service_utils.py` — logging setup, min_bars_for_tf(), plugin metrics sampling
  - `timeframe_builder.py` — multi-TF bar aggregation (1m → 5m/15m/1h)

**src/intelligence/:**
- Purpose: Plugin system, intelligence event schemas, LLM providers
- Contains: Plugin registry, 91 plugins across I1–I7 + SMC, typed event bus (IntelligenceEvent)
- Sub-directories:
  - `indicators/` — 23 I1 technical indicator plugins
  - `composites/` — 11 I2 composite event plugins
  - `structure/` — 8 I3 structure analysis plugins
  - `context/` — 7 I4 context/regime plugins
  - `patterns/` — 14 I5 pattern detection plugins
  - `smart_money/` — 13 SMC/I6 smart money plugins
  - `confluence/` — 1 I6 cross-timeframe confluence plugin
  - `trading/` — 17 I7 trading setups + aggregator
- Key files:
  - `schemas.py` — canonical `IntelligenceEvent` model + all sub-models (I1–I6)
  - `register_plugins.py` — plugin registration + tier lists (TIER_I1, TIER_I3, etc.)
  - `plugins.py` — plugin registry base class
  - `llm_providers.py` — Z.ai, OpenRouter, Ollama provider chain
  - `setup_performance_updater.py` — reads `setup_performance` table, caches weights

**src/observability/:**
- Purpose: Metrics collection and logging
- Contains: Prometheus metric definitions, structured logging setup
- Key files: `metrics.py` (counter, gauge, histogram; per-plugin execution tracking)

**src/providers/:**
- Purpose: External system integrations
- Contains: IBKR TWS integration (ib_insync wrapper)
- Key files: `ibkr.py` (ALL IBKR logic isolated here; contract fetching, quote subscription)

**services/:**
- Purpose: Systemd-managed asyncio services (8 total)
- Each file is a complete service with:
  - `__init__()` — setup logging, plugins, Redis consumer groups
  - `_load_config()`, `_setup_logging()` — boilerplate
  - `run()` — main loop consuming stream messages
  - Signal handling (SIGINT, SIGTERM) with graceful shutdown
- Key files:
  - `indicator_service.py` (I1; reads market, runs indicators, publishes to indicators stream)
  - `market_analysis_service.py` (I3–I6; reads indicators stream, runs structure/context/patterns/SMC/confluence, publishes intelligence events)
  - `signal_generator_service.py` (I7; reads intelligence events, runs setups, aggregates, fires signals, writes to signal_ledger)
  - `signal_lifecycle_service.py` (lifecycle; reads market bars + signals, tracks activation/exit, computes MAE/MFE/outcome)
  - `ai_narrative_service.py` (I8; reads signals, calls LLM, publishes narratives, emits LLM audit events)
  - `feature_writer_service.py` (persistence; reads intelligence events + enrichments, batch writes to intelligence_features hypertable)
  - `llm_writer_service.py` (audit; reads llm_calls:stream + llm_outcomes:stream, writes to llm_calls hypertable + back-fills model scores)

**dashboard/src/:**
- Purpose: Next.js React frontend
- Contains: Signal display, real-time updates via SSE, live market context
- Sub-directories:
  - `app/` — page routes (landing page, dashboard)
  - `components/` — reusable React components (signal-card, indicator-grid, drill panel)
  - `lib/` — utilities (format.ts for time/value formatting, hooks for SSE)
  - `hooks/` — custom React hooks (useFormattedTimestamp, useMarketStream)

**production/:**
- Purpose: Deployment infrastructure
- Contains: Docker Compose, systemd unit files, database migrations, operational scripts
- Key files:
  - `docker-compose.yml` — PostgreSQL/TimescaleDB, DragonflyDB, Ollama containers
  - `systemd/` — service unit files (all 8 services + TWS daemon)
  - `migrations/` — numbered SQL files (001, 002, …, applied in order)
  - `scripts/pipeline_reset.py` — reset entire pipeline (fetch + replay with optional clear flags)
  - `scripts/historical_backfill.py` — fetch historical OHLCV + replay intelligence pipeline

**tests/unit/:**
- Purpose: Unit tests (CI-clean, no external deps)
- Organization mirrors `src/`:
  - `tests/unit/intelligence/` — plugin tests
  - `tests/unit/service_tests/` — service tests (using `ServiceClass.__new__()` pattern to bypass `__init__`)
  - `tests/unit/core/` — core infrastructure tests
  - `tests/unit/api/` — API endpoint tests

**tests/integration/:**
- Purpose: Integration tests (requires live PostgreSQL, Redis, IBKR)
- Contains: End-to-end service flow tests

**docs/ideas/:**
- Purpose: Research topics, vision documents, open questions
- Contains: Ideas not yet ready to build (e.g., TradeAgent, QualAgent, DerivAgent product visions)
- Key file: `IDEAS-INDEX.md` — primary lookup for all research

**docs/plans/:**
- Purpose: Design documents and implementation plans (output of brainstorming + writing-plans)
- Contains: TDD plans for features ready to build (design doc + phase breakdown)
- Format: `YYYY-MM-DD-<topic>-design.md` + corresponding phase PLAN.md files

**.planning/ROADMAP.md:**
- Purpose: Current milestone phases, backlog, version history
- Format: Version-indexed phases (v1.0 shipped, v1.1 shipped, …, v1.7 shipped, next: v1.8)
- GSD-managed: `/gsd:plan-phase` reads here; `/gsd:execute-phase` runs phases

## Key File Locations

**Entry Points:**
- `services/indicator_service.py` — starts I1 tier
- `services/market_analysis_service.py` — starts I3–I6 pipeline
- `services/signal_generator_service.py` — starts I7 signal generation
- `src/api/main.py` — FastAPI application
- `dashboard/src/app/dashboard/page.tsx` — Dashboard UI entry point

**Configuration:**
- `src/config/settings.py` — all env vars, contract definitions, LLM keys
- `production/docker-compose.yml` — service container config
- `production/systemd/*.service` — service startup args
- `.env` — environment file (secrets, not committed)

**Core Logic:**
- `src/intelligence/schemas.py` — canonical event schema
- `src/intelligence/register_plugins.py` — plugin registry + tier definitions
- `src/core/stream_keys.py` — stream name construction + maxlen policies
- `src/intelligence/trading/aggregator.py` — signal aggregation logic
- `src/intelligence/trading/lifecycle_tracker.py` — signal outcome classification

**Testing:**
- `tests/unit/` — unit test suites (one per module)
- `conftest.py` (if exists in test dirs) — pytest fixtures
- Test naming: `test_<function>_<scenario>.py`

**Database:**
- `production/schemas/create_schema.sql` — initial table creation (market_data_ohlcv, intelligence_features, signal_ledger, llm_calls)
- `production/migrations/00X_*.sql` — incremental migrations (ALTER, ADD COLUMN, etc.)

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `signal_generator_service.py`, `market_analysis_service.py`)
- Plugin files: `<plugin_name>.py` in tier subdirectory (e.g., `src/intelligence/indicators/rsi.py`, `src/intelligence/trading/trend_following.py`)
- Test files: `test_<module>.py` (e.g., `test_indicator_service.py`)
- Dashboard components: `<ComponentName>.tsx` in PascalCase (e.g., `signal-card.tsx` → export SignalCard)

**Directories:**
- Service-specific logic: lowercase with underscores (e.g., `signal_generator`, `market_analysis`)
- Plugin tiers: lowercase (e.g., `indicators`, `structure`, `patterns`, `trading`)
- Utility modules: lowercase (e.g., `core`, `observability`, `providers`)
- React components: PascalCase components, lowercase filenames (e.g., `signal-card.tsx` exports `SignalCard`)

**Functions:**
- All lowercase with underscores: `compute_rsi()`, `_build_i1_message()`, `ensure_consumer_group_with_reset()`
- Private functions: prefix with `_` (e.g., `_setup_logging()`)

**Classes:**
- PascalCase: `IndicatorService`, `MarketAnalysisService`, `IntelligenceEvent`, `LedgerEntry`
- Plugin class: Always `PatternPlugin` (enforced by registry)
- React components: PascalCase (e.g., `SignalCard`)

**Constants:**
- UPPERCASE_WITH_UNDERSCORES: `TIER_I1`, `_OHLCV_FIELDS`, `PLUGIN_METRICS_SAMPLE_RATE`
- Tier lists imported from `src/intelligence/register_plugins.py`: `TIER_I1`, `TIER_I2`, `TIER_I3`, `TIER_I4`, `TIER_I5`, `TIER_SMC`, `TIER_I6`, `TIER_I7`

**Stream Keys:**
- Pattern: `<prefix>:<entity>:<symbol>:<timeframe>` (via `src/core/stream_keys.py` helpers)
- Examples: `development:indicators:ESH6:1m`, `development:signals:NQH6:5m:aggregated`, `development:intelligence:CLJ6:15m`
- Env prefix: from `Settings.env_name` (e.g., "development", "" for production)

## Where to Add New Code

**New Feature (e.g., new I7 setup):**
- Primary code: `src/intelligence/trading/<setup_name>.py`
- Plugin class: Extend `PatternPlugin`, implement `inputs`, `outputs`, `compute_full()`
- Register: Add import + `registry.register_pattern(plugin)` in `src/intelligence/register_plugins.py`
- Add to tier: Update `TIER_I7` list in register_plugins.py
- Tests: `tests/unit/intelligence/trading/test_<setup_name>.py`
- Signal attributes: If new attributes needed, update `LedgerEntry` in `src/intelligence/trading/signal_ledger.py`

**New Indicator Plugin (I1):**
- Primary code: `src/intelligence/indicators/<indicator_name>.py`
- Register: Add import + `registry.register_indicator(plugin)` in register_plugins.py
- Add to tier: Update `TIER_I1` list
- Tests: `tests/unit/intelligence/indicators/test_<indicator_name>.py`
- Schema: If outputs need exposed in dashboard, add fields to `I1Indicators` in `src/intelligence/schemas.py`

**New Service:**
- Primary code: `services/<service_name>_service.py`
- Pattern: Copy `services/indicator_service.py` structure (init, logging, run loop, signal handling)
- Consumer group: Decide stream to consume, add `ensure_consumer_group_with_reset()` call in init
- Systemd unit: Add `production/systemd/indicagent-<service_name>.service`
- Metrics port: Claim a unique port in 9100–9199 range (see CLAUDE.md for assignments)
- Tests: `tests/unit/service_tests/test_<service_name>.py` using `ServiceClass.__new__()` pattern

**Utilities & Helpers:**
- Shared helpers: `src/core/` (stream utils, service utils, database manager)
- Plugin utilities: `src/intelligence/<tier>/` (e.g., `src/intelligence/trading/lifecycle_tracker.py`)
- If new infrastructure needed: add to `src/core/` (e.g., new DatabaseManager method)

**API Endpoints:**
- Primary code: `src/api/routes/<domain>.py` (e.g., `src/api/routes/signals.py`)
- Import in: `src/api/main.py` (`app.include_router()`)
- Tests: `tests/unit/api/test_<domain>.py`

**Dashboard Components:**
- New component: `dashboard/src/components/<ComponentName>.tsx`
- Utilities: `dashboard/src/lib/<utility>.ts`
- Hooks: `dashboard/src/hooks/use<HookName>.ts`
- Tests: `dashboard/src/lib/__tests__/<filename>.test.ts` (if test runner configured)

## Special Directories

**production/migrations/:**
- Purpose: Version controlled SQL schema changes
- Generated: No (manually written)
- Committed: Yes
- Format: `00X_<description>.sql` (001, 002, 003, …)
- Applied by: `pipeline_reset.py` at startup if `intelligence_features` table doesn't exist; manual `psql` runs for hot schema changes
- Gotcha: Cannot use `CREATE INDEX CONCURRENTLY` on hypertables — omit CONCURRENTLY

**production/scripts/:**
- Purpose: Operational tooling (backfill, repairs, diagnostics)
- Generated: No (version controlled)
- Committed: Yes
- Key scripts:
  - `pipeline_reset.py` — reset entire pipeline (fetch + replay with optional flags)
  - `historical_backfill.py` — fetch historical OHLCV + replay I1–I7
  - `repair_cis_nulls.py` — audit + repair NULL CIS scores in signal_ledger

**production/systemd/:**
- Purpose: Systemd service unit files (auto-start, restart policy)
- Generated: No (version controlled)
- Committed: Yes
- Format: `indicagent-<service_name>.service`
- One unit per service (indicator, market-analysis, signal-generator, signal-lifecycle, ai-narrative, feature-writer, llm-writer, tws)

**.planning/phases/:**
- Purpose: Per-phase implementation plans and task tracking
- Generated: Yes (by `/gsd:plan-phase`, `/gsd:execute-phase`)
- Committed: Yes (GSD writes phase PLAN.md files)
- Format: `<phase_id>-<phase_name>/PLAN.md`
- Archived after completion: moved to `.planning/milestones/v<version>-phases/`

---

*Structure analysis: 2026-03-11*
