# CLAUDE.md

Version: 5.25.0
Last Updated: 2026-03-19
Status: v2.0 IN PROGRESS — Phase 39.1 complete, Phase 40 next

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
- **Never drop data that could contain signal.** Storage is the cheapest thing we own. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered. The only data we drop is confirmed-unused legacy tables with no signal value.

Apply this framing when: designing new features, choosing between approaches, deciding what to log, evaluating model/strategy performance, or questioning whether something is "good enough."

# IndicAgent Market Intelligence Platform

Real-time market intelligence platform with plugin-native architecture, Redpanda event-driven pipeline, and production-grade monitoring infrastructure.

## Knowledge Hierarchy

| Level | Location | Description |
|-------|----------|-------------|
| **Captures** | `.planning/IDEAS.md` | Bullet list of ideas; links to detailed files when fleshed out |
| **Research** | `docs/ideas/*.md` | Per-idea files — status/priority/milestone in frontmatter; reviewed by human + LLM |
| **Tech stack** | `docs/ideas/tech-stack.md` | Stack decisions with reasoning — living document |
| **Design docs** | `docs/plans/*.md` | `brainstorming` output — reviewed before planning |
| **Todos** | `.planning/todos/pending/` | Fixes, refactors, small improvements (`/gsd:add-todo`) |
| **Roadmap** | `.planning/ROADMAP.md` | Current milestone phases + backlog (GSD-managed) |
| **Plans** | `.planning/phases/*/PLAN.md` | Detailed TDD implementation plans (`/gsd:plan-phase`) |

> **`docs/ideas/` is a living research workspace** — files are actively reviewed, trimmed, and developed over time. Large ideas (e.g. Renaissance intelligence, MLAgent) are built incrementally: each session starts from the file to discuss what subset is feasible, too complex, or too compute-intensive, then plans/builds that slice. The file tracks what's shipped vs still future. Status/priority/milestone live in each file's frontmatter. No separate index.
> **When a subset is ready to build:** `brainstorming` → `docs/plans/` → `/gsd:plan-phase` → `/gsd:execute-phase`.

Use `/gsd:add-todo` for implementation tasks. Use ROADMAP Backlog for milestone-scale features.

## Required Workflows

### Pre-Commit Quality Gate (Mandatory)
Before committing: `/simplify` then `/coderabbit:code-review`.

### Post-Milestone Housekeeping
`git push origin main`, push tag (`git push origin vX.Y`), `/gsd:cleanup`, update README stats.
**Design doc archive:** After each phase ships, move its `docs/plans/*.md` to `docs/plans/archive/` if `Status: Shipped`. Do this as part of post-phase cleanup, not just at milestone boundaries.
**Todo store:** `.planning/todos/pending/` (active) and `.planning/todos/done/` (completed). GSD config reports `completed_dir` but actual dir on disk is `done/`.

### Feature Development (any new plugin, service, or significant change)
**Mandatory skill chain — do not skip steps:**
1. `brainstorming` — design approval → `docs/plans/YYYY-MM-DD-<topic>-design.md`
2. `writing-plans` — TDD implementation plan
3. `executing-plans` — task-by-task with review checkpoints
4. `verification-before-completion` — full test suite + lint
5. `finishing-a-development-branch` — clean git history, decide merge/PR/cleanup

**Do NOT jump straight to coding.** Even "simple" plugins need the brainstorming step.

### Refactoring Philosophy
Refactors should produce a **cleaner DAG** — modules with single responsibilities that compose upward into services. Never refactor just to reduce line count. Ask: *can this module be reused by another service? does it have exactly one job? does it make the dependency graph more explicit?* Monolithic services that accumulate logic over time are the anti-pattern to avoid.

### Plugin vs Service Boundary
**If it decides something about market data or signals → plugin/intelligence layer (`src/intelligence/`)**
**If it moves data between places → service layer (`services/`)**
Services should be thin: Redpanda consumer/producer + lifecycle wiring only. Regime gating, staleness scoring, confidence adjustments, TTL logic — all analytical, all belong in `src/intelligence/`. Plugins must never know about other plugins directly; cross-plugin communication goes through tier output schemas only. A plugin reusable in multiple contexts signals it should be a shared module, not duplicated.

### Bug Fixes & Debugging
1. `systematic-debugging` — structured investigation before proposing fixes
2. `verification-before-completion` — confirm fix works before committing

### After Major Changes
`revise-claude-md` · `verification-before-completion` · `requesting-code-review`

### Library & Framework Documentation
Use `context7` MCP for FastAPI, SQLAlchemy, pytest, Redpanda/Kafka, TimescaleDB, etc.

### Todo Management
`/gsd:add-todo` · `/gsd:check-todos` · `/gsd:review-todos`

## Core Commands

> Full reference: `docs/cheatsheet.md`

**Tests:** `.venv/bin/pytest tests/unit/ -v` · lint: `.venv/bin/ruff check . --fix` · format: `.venv/bin/black .`
**Dashboard dev:** `cd dashboard && npm run dev`
**Services** (systemd-managed, `Restart=always`):
- Config changes require restart: `sudo systemctl restart indicagent-<name>` to pick up `_load_config()` changes
- Services require restart after adding new contracts to `instruments` table — config loads once at startup
- New contracts require: (1) INSERT to `instruments` table, (2) restart services that consume symbols (indicator, market_analysis, feature_writer), (3) historical backfill: `.venv/bin/python production/scripts/historical_backfill.py --fetch-only --symbols SYM --days N`
- `sudo systemctl {status|restart|start} indicagent-{tws,indicator,market-analysis,signal-generator,signal-lifecycle,ai-narrative,feature-writer,llm-writer,cross-asset,api}`
- `journalctl -u indicagent-<name> -f` — live logs
- Metrics ports: indicator :9109, signal-gen :9112, ai-narrative :9113, market-analysis :9114, signal-lifecycle :9115, feature-writer :9116, llm-writer :9117, cross-asset :9118

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
IBKR TWS → indicator_service (I1) → market_analysis_service (I2→I6) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer_service`.

## Key Components

### Active Services
| Service | Unit | Purpose | Metrics |
|---------|------|---------|---------|
| TWS Daemon | `indicagent-tws` | IBKR tick + bar collection | — |
| Indicator Service | `indicagent-indicator` | I1: 25 indicators → `indicators:SYMBOL:TF` | :9109 |
| Market Analysis | `indicagent-market-analysis` | I3→I6 pipeline → `intelligence:SYMBOL:TF` | :9114 |
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger`; seeds `bar_history` from `intelligence_features` on startup — no warmup delay; falls back to ~50 live 1m bars (~50 min) if DB seed fails | :9112 |
| Signal Lifecycle | `indicagent-signal-lifecycle` | Zone-aware lifecycle: activation, MAE/MFE, 8-class outcome | :9115 |
| AI Narrative | `indicagent-ai-narrative` | I8: LLM → `narratives:SYMBOL:TF` | :9113 |
| Feature Writer | `indicagent-feature-writer` | Redpanda → `intelligence_features` batch writer | :9116 |
| LLM Writer | `indicagent-llm-writer` | `llm_calls:stream` → `llm_calls` hypertable + outcome back-fill + score cache | :9117 |
| Cross-Asset Service | `indicagent-cross-asset` | Cross-asset spread dynamics + I7 feed → `development.cross_asset` | :9118 |
| API | `indicagent-api` | FastAPI + SSE on :8000 | — |

### Core Runtime Files
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `PLUGIN_METRICS_SAMPLE_RATE`
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)

## Data Flow

### Hot/Warm/Cold Tiers
```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: feature_writer_service → TimescaleDB                (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV (backfill only; keep forever — ground truth). Live data flows through Redpanda topics only.
- `intelligence_features` — full feature vectors per bar incl. i7/i8 JSONB (ML training dataset; keep forever). Column name is `ts` not `feature_ts`.
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
- **`market_data_ohlcv` missing index**: `CREATE INDEX ON market_data_ohlcv (symbol, timeframe, timestamp DESC);` — without this, ORDER BY DESC LIMIT queries scan all 10k chunks and time out. Omit CONCURRENTLY (not supported on hypertables).
- **`instruments` table key is base symbol**: `symbol` column stores base (e.g., `PL`, `SOL`, `ES`), NOT the contract code. Contract code lives inside `contract_details->>'symbol'`. The API spreads `json.loads(contract_details)` so the JSONB `symbol` key overrides the DB key in API responses. To deactivate: `UPDATE instruments SET is_active = FALSE WHERE symbol IN ('PL', 'SOL')`.
- **`instruments.contract_details` is stored as a JSON string**: `jsonb` column stores a serialized string value, not a JSON object. `jsonb_typeof(contract_details)` returns `"string"`, so `->>'field'` operators don't work directly in SQL. Use Python `json.loads()` to parse, or in SQL: `(contract_details #>> '{}')::jsonb->>'field'`.

## Plugin System

111 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name
- **LLM provider rotation**: `ai_narrative_service.py` uses `LLMChain` with ordered fallback. Multiple free OpenRouter models (`:free` suffix) prevent rate limit failures. Define shared provider lists as module-level constants to avoid duplication across chains.

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues.
- **Enum migrations:** When replacing raw strings with enums, update function signatures to return the enum type (not `str`). Extend enum from `str` (e.g., `class SignalOutcome(str, Enum)`) for DB compatibility without migrations.
- **Hot-path optimization:** Extract repeated list/struct construction to module-level constant tuples to avoid allocation in loops. Use tuples for immutability.
- **Re-exports:** Use explicit `__all__` export list instead of `# noqa` comments for backward compatibility re-exports.
- **CodeRabbit limits**: 150 files max per review. Use `--base HEAD~N` to review recent commits. Process can get killed (exit code 137/OOM) on large diffs — review smaller chunks.
- **CodeRabbit on main**: `coderabbit review --plain -t all` fails with "no merge base" when on main. Use `-t uncommitted` instead.
- **Simplify workflow**: Launches 3 parallel agents (reuse, quality, efficiency) — finds duplication, missing utilities, inefficient patterns. Real issues found in this session (provider list duplication, datetime parsing reuse).
- **Documentation accuracy**: Docs may contain fabricated content (nonexistent classes, functions, DB tables) written as forward-looking specs never implemented. Always verify doc claims against actual code (`src/`) before trusting them — if a doc references a class or function, grep for it first.

### Naming Conventions

> Full reference: `docs/reference/documentation-standards.md`

**Python**
- Plugin classes: `PascalCase` + `Plugin` suffix — `MACDPlugin`, `BollingerPlugin`, `CHoCHReversalPlugin`
- Aggregator/result classes: `PascalCase`, no suffix required — `CISScorer`, `AggregatedResult`
- Service files: `snake_case_service.py` — `signal_generator_service.py`
- Plugin files: `snake_case.py`, short — `adx.py`, `bollinger.py`, `choch_reversal.py`
- Topic builder functions: `topic_<thing>()` — `topic_indicators()`, `topic_signals_aggregated()`
- Constants: `UPPER_SNAKE_CASE` — `TIER_I1`, `PLUGIN_METRICS_SAMPLE_RATE`
- Private attrs: `_snake_case` leading underscore — `_regime_cache`, `_plugin_states`

**Redpanda topics**: dots not colons — `development.indicators`, `development.intelligence.i7`. Always via `stream_keys.py`.

**Database**: tables/columns `snake_case`; migrations `NNN_description.sql` (zero-padded); views `<source>_<tf>` (`ohlcv_15m`).

**Systemd**: `indicagent-<name>.service`

**Tests**: `tests/unit/test_<module>.py`; functions as `test_<what>_<condition>`

**TypeScript**: components `PascalCase.tsx`, hooks `use-kebab-case.ts`, utils `kebab-case.ts`

**Docs**: kebab-case files, uppercase for `README.md`/`CLAUDE.md`/`CHANGELOG.md`; plan docs date-prefixed `YYYY-MM-DD-<topic>.md`

### Key Rules

**Documentation Framing**
- **Data source language**: IndicAgent is provider-agnostic — docs/READMEs must not describe it as "IBKR-powered" or tie the product identity to any specific broker. Use "real-time market data" or "any real-time source". IBKR is the current implementation detail and belongs only in technical/operational sections.

**Core Patterns**
- **Timestamps: always UTC.** All datetimes must be timezone-aware UTC — `datetime.now(UTC)` or `datetime.now(tz=UTC)`. Never `datetime.now()` (naive) or `datetime.utcnow()` (naive despite the name). When labeling a naive timestamp from an external source (e.g. IBKR bars), use `replace(tzinfo=UTC)` only if you are certain the source is already UTC — otherwise `astimezone(UTC)`. All DB columns are `timestamp with time zone`; all stream timestamps are UTC ISO-8601 (`Z` suffix). This is the global standard for all financial data systems (Renaissance, CME, IBKR, all major funds).
- **asyncpg batch inserts**: `execute_batch()` / `executemany()` requires Python `datetime` objects for `timestamptz` columns — ISO-8601 strings cause type mismatch. SQL `::timestamptz` casts work for single inserts but not batch mode. Use `_parse_ts()` from `feature_writer_service.py` or parse with `datetime.fromisoformat()` before inserting.
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **API route Settings cache**: `_resolve_contract()` in API routes must use `@lru_cache(maxsize=1)` on `_get_settings()` — not `Settings()` fresh per call. See `sse.py` for the canonical pattern.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests are CI-clean; integration requires live infra.
- **Ruff**: always run `.venv/bin/ruff check .` from project root (not absolute paths).

**Stream & Consumer Groups**
- **Boolean serialization**: verify current format after Redpanda migration — previously `"1"`/`"0"` in Redis streams, parsed with `Number(payload.field) > 0` in `use-market-stream.ts`. May have changed with Kafka serialization.

**Service & Test Patterns**
- **Services**: graceful SIGINT/SIGTERM, drain queues, idempotent consumer groups.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`. **All service logs go to `logs/<service>.log` via `setup_service_logging()` — NOT to journald.** journalctl only shows `print()` output. Read log files directly for structured service output.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().
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
- **Redpanda**: Kafka-compatible streaming backbone (replaced DragonflyDB). Use TimescaleDB for time series (no Redpanda time series modules). Topic naming: dots not colons — `development.market.bars`. Always via `stream_keys.py`.
- **Redpanda topic retention**: All `development.*` topics must have `retention.ms=604800000` (7 days) set explicitly — broker default is shorter and purges seeded I1 messages over weekends. Set with: `docker exec redpanda rpk topic alter-config <topic> --set retention.ms=604800000`. Confirmed set on `development.indicators` 2026-03-15.
- **TWS `bars_processed` freeze**: `seen_bar_timestamps` dedup caches all timestamps from initial poll — subsequent polls return 0 new bars. Symptom: counter stuck at N×60 forever. Fix: restart TWS service.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.

**Dashboard**
- **Dashboard 1s re-render tick**: `signal-card.tsx` calls `setInterval(1s)` via `useFormattedTimestamp` — any derived values (formatted strings, timestamps) must use `useMemo` to avoid per-second recomputation.
- **`format.ts` timing utils**: `fmtTimeHMS(iso)` → `HH:MM:SS` or null (guards invalid dates); `fmtLagSeconds(lagS)` → `"+1.2s"` or null (guards NaN).
- **SSE broadcaster `_latest` rebuild**: `KafkaSSEBroadcaster` uses stable `group_id="sse_broadcaster"` + `seek_to_beginning()` on startup so all topic history replays on each API restart, fully populating the snapshot cache. If dashboard shows "-" after an API restart, restart the API again — the broadcaster needs ~5s to replay.
- **`intelligence_i7` SSE domain**: `intelligence_i7:SYMBOL:TF` stream is subscribed in `_build_stream_list()` (alongside `intelligence:`); event name is `signal_scorecard`. Check must appear before `intelligence:` startswith check to prevent shadowing.
- **`signal_scorecard` event payload**: `{"ts": "...", "symbol": "ES", "tf": "1m", "data": "[{...}]"}` where `data` is a JSON-encoded string of `RankedSignal[]`. Parse with `JSON.parse(String(payload.data || "[]"))`.
- **`GET /api/signals/recent`**: `?symbol=&timeframe=&limit=` — returns `signal_ledger` rows with `setup_performance` LEFT JOIN, ordered by `computed_at DESC`. Drill panel fetches on mount and merges with SSE history deduplicated by `signal_id` (SSE version wins on conflict).
- **Dashboard layout modes**: `trading-dashboard.tsx` has two modes — `"focus"` (left `WatchlistRail` + single `SymbolCard`) and `"grid"` (`GroupedSymbolGrid` grouped by sector). Auto-switches to focus when profile > 12 instruments. Toggle in header.
- **Skeleton cards**: `SkeletonCard` renders a shimmer placeholder while `symbolData[sym]` is null on page load/SSE reconnect. Prevents blank card flash.
- **`symbol-config.ts` `loadConfig()`**: Fetches all asset classes from `/api/instruments` (not just `futures`). ETFs have `asset_class: "equity"` in the DB. `SymbolInfo.sector` is `string` (not a union) to accommodate all ETF sectors.
- **Signal alert strip**: `SignalAlertStrip` renders above content when any instrument has a signal ≥ 0.65 confidence. Scans all TFs per symbol; deduplicates to one pill per symbol (highest confidence).
- **`allowedDevOrigins` (Next.js dev)**: Next.js 16+ blocks cross-origin `/_next/*` HMR requests by default — causes full page reload every ~30-80s when accessing dev server from a non-localhost host. Fix: add all access origins (local IP, CF domains) to `allowedDevOrigins` in `next.config.ts`. Current: `["dash.indicagent.com", "www.indicagent.com", "192.168.1.158"]`.
- **`getApiBase()` runtime detection** (`src/lib/api.ts`): Returns the correct API base URL at runtime based on `window.location.hostname`. LAN/localhost → `http://<hostname>:8000`; any other host → `https://api.indicagent.com`. Use this instead of `NEXT_PUBLIC_API_BASE_URL` so both direct LAN access and CloudFlare tunnel work without config changes. `NEXT_PUBLIC_API_BASE_URL` still overrides if set.
- **SSE `Cache-Control` / `X-Accel-Buffering`**: `sse_events` StreamingResponse includes `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers — prevents reverse proxies (nginx, CF) from buffering the stream.

## System Access

- **Sudo:** `echo 'PASSWORD' | /usr/bin/sudo.ws -S <cmd>` — plain sudo active via `update-alternatives` (switched 2026-03-15; sudo-rs blocked stdin). For heredocs, write to `/tmp` first then `sudo cp`. Password stored in memory, not here.
- **Server IP:** `192.168.1.158` (Ethernet, `enp2s0`). IBKR TWS at `192.168.1.157` — if TWS connection refused, check trusted IPs in TWS API settings.

## Data Pipeline Debugging

When investigating "service not writing to database":
1. **Check service health metrics first** — `events_consumed` and `batches_written` in logs. If increasing, service is working.
2. **Check which symbols ARE in target table** — `SELECT DISTINCT symbol FROM intelligence_features WHERE ts > NOW() - INTERVAL '2 hours';`
3. **Trace data flow upstream** — TWS → bars → indicator → intelligence → feature_writer → DB
4. **Verify service configs include the symbol** — Check startup logs for `"symbols"` list
5. **Check prerequisite data exists** — New contracts need historical backfill before intelligence pipeline processes them

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `IBKR_HOST=192.168.1.157`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3.5:9b`

## Roadmap

**v1.9 IN PROGRESS** — Phases 31-34 shipped (CIS learning loop, stop architecture, 5 new I7 plugins, AVWAP+Volume Profile). Phase 38 next: automated futures roll detection.

Full history: `.planning/ROADMAP.md`
