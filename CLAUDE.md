# CLAUDE.md

Version: 5.32.0
Last Updated: 2026-03-25
Status: v2.1 IN PROGRESS — see `.planning/ROADMAP.md` for current phase.

## Renaissance Foundation Principles
- **Instrument everything.** No data point left uncaptured. If it happened, it should be measurable.
- **Let the system run.** Don't override data with intuition. Build the automation, then trust it.
- **Earn the right through proof.** No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Shadow mode first, always.
- **Segment relentlessly.** A rule that works globally is weaker than one that works in a specific regime. Always ask: "under what conditions does this hold?"
- **Degrade gracefully, adapt automatically.** Systems that require manual tuning are fragile. Build feedback loops that self-correct.
- **Data quality over model complexity.** Clean, complete data beats a smarter model on dirty data every time.
- **Never drop data that could contain signal.** Storage is the cheapest thing we own. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered.

## Renaissance Agentic DAG Principles (v2.1)
- **Agentic DAG Architecture:** All pipeline nodes must be autonomous, event-driven Agents. Compute Agents (I1-I6) are DB-ignorant and publish to domain-specific Tiered Topics (`intelligence.i{N}`). DataWriterAgents manage all persistence.
- **The Persistence DAG:** WriterAgents must use the "Convergence Gate" (StreamMerger) to join tiered streams into a single, unified journal entry before persistence, ensuring atomic data integrity.
- **Resilience & Observability:** 
    - All agents must be instrumented with the "Golden Signals" (Traffic, Latency, Errors, Saturation) via Prometheus + Grafana.
    - Persistence agents must track `persistence_batch_latency` and `persistence_consumer_lag`.
- **Lifecycle Management:** 
    - Agents must implement `SIGTERM` handlers for graceful drain and maintain a DLQ (`intelligence.[domain].journal.dlq`) for unprocessable payloads.
- **Taxonomy:** All persistence logic resides in `src/persistence/repository/` (Repositories) and `src/persistence/writer/` (WriterAgents).
- **Scaling:** Scaling is managed via systemd process management and Prometheus-based lag monitoring. No manual Kubernetes HPA management.

Apply this framing when: designing new features, choosing between approaches, deciding what to log, evaluating model/strategy performance, or questioning whether something is "good enough."

# IndicAgent Market Intelligence Platform

Real-time market intelligence platform with plugin-native architecture, Redpanda event-driven pipeline, and production-grade monitoring infrastructure.

## Quick Start

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
.venv/bin/pytest tests/unit/ -v

# Code quality
.venv/bin/ruff check . --fix    # Lint
.venv/bin/black .                # Format

# Start services
sudo systemctl start indicagent-feature-compute  # or other services
sudo systemctl status indicagent-signal-generator

# Dashboard
cd dashboard && npm run dev  # Runs on http://localhost:3000

# Pre-commit workflow (mandatory before committing)
/simplify                    # Review for reuse/quality/efficiency
/coderabbit:code-review      # Run AI code review
```

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
2. **Reproduce first (Mandatory)** — Create a standalone `reproduce_bug.py` script that demonstrates the failure before writing any fix.
3. `verification-before-completion` — confirm fix works (and reproduction script now passes) before committing.

### Inquiry vs. Directive Protocol (Gemini & Claude)
To prevent premature or "helpful" code changes during the research phase:
- **Inquiry:** If asked "How should we...?" or "What's the best approach?", research and propose in a `docs/ideas/` or `docs/research/` file. **Do NOT modify codebase.**
- **Directive:** Only when an explicit instruction to "Implement X" or "Execute phase Y" is given, move to implementation and code changes.

### After Major Changes
`revise-claude-md` · `verification-before-completion` · `requesting-code-review`

### Library & Framework Documentation
Use `context7` MCP for FastAPI, SQLAlchemy, pytest, Redpanda/Kafka, TimescaleDB, etc.

### Todo Management
`/gsd:add-todo` · `/gsd:check-todos` · `/gsd:review-todos`

## Core Commands

> Full reference: `docs/cheatsheet.md` (pipeline reset, backfill scripts, service management, metrics ports)

**Consumer debugging:** `docker exec redpanda rpk group describe feature_pipeline -t` — shows consumer lag per topic. `docker exec redpanda rpk topic consume development.market.bars.htf` — verify HTF bars are being published correctly.

**Roadmap consistency check:** `node gsd-tools.cjs roadmap analyze` — detects disk-vs-roadmap mismatches. Run after any phase completion.

**Tests:** `.venv/bin/pytest tests/unit/ -v` · lint: `.venv/bin/ruff check . --fix` · format: `.venv/bin/black .`
**Dashboard dev:** `cd dashboard && npm run dev`
**New contracts:** (1) INSERT to `instruments` table, (2) restart `indicagent-{ibkr-provider,feature-compute,signal-generator,feature-writer}`, (3) backfill: `.venv/bin/python production/scripts/historical_backfill.py --fetch-only --symbols SYM --days N`
**Direct run (debug only):** `.venv/bin/python services/<name>_service.py` · API: `uvicorn src.api.main:app`

## Naming Conventions

**Principle (Renaissance rule):** A service's *concept name* (`snake_case`, no suffix) determines all its derived names across every layer. Given `feature_pipeline`, every layer's name is mechanically derivable — no lookup needed.

### Cross-Layer Transformation Rules

| Layer | Pattern | Example (`alpha_signal`) |
|-------|---------|------------------------------|
| Python file (Service) | `<concept>_service.py` | `alpha_signal_service.py` |
| Python file (Agent) | `<concept>_agent.py` | `alpha_signal_agent.py` |
| Python file (Plugin) | `src/intelligence/trading/<concept>.py` | `alpha_signal.py` |
| Python class (Service) | `PascalCase` + `Service` | `AlphaSignalService` |
| Python class (Agent) | `PascalCase` + agent role suffix (see below) | `AlphaSignalComputeAgent` |
| Python class (Plugin) | `PascalCase` + `Plugin` | `AlphaSignalPlugin` |
| Systemd unit | `indicagent-<concept-kebab>.service` | `indicagent-alpha-signal.service` |
| Log file | `logs/<python_filename>.log` | `logs/alpha_signal_agent.log` |
| Kafka topic fn | `topic_<concept>()` in `stream_keys.py` | `topic_alpha_signal()` |
| Kafka topic string | `<env>.<domain>[.<sublayer>]` (dots only) | `dev.alpha_signal` |
| DB table | `snake_case` plural noun | `alpha_signals` |
| DB columns | `snake_case` | `ts`, `symbol`, `tf`, `i7` |

**Agent role suffixes** (from `docs/architecture/AGENT_STANDARD.md`): `ProviderAgent` (external source→Kafka, no compute/DB), `ComputeAgent` (math/stats transform, DB-ignorant), `GeneratorAgent` (signal/trade fire), `WriterAgent` (DB persistence), `TrackerAgent` (business object lifecycle), `AuditorAgent` (data integrity validation + self-healing). Use `_agent.py` / `PascalCaseRoleAgent` for any service that is DB-ignorant and publishes to a Kafka topic. Use `_service.py` / `PascalCaseService` for services with mixed concerns or DB access.

### Active Service Map

See "Active Services" table in Key Components section below. Source service files: `services/*.service`. Installed: `/etc/systemd/system/`. `production/systemd/` is a reference template — NOT what's installed.

### Per-Layer Naming Rules

**Python**
- Plugins: `snake_case.py` file (short name) / `PascalCasePlugin` class — `adx.py` → `ADXPlugin`
- Aggregators/results: `PascalCase` no suffix — `CISScorer`, `AggregatedResult`
- Functions/methods: `snake_case`. Constants: `UPPER_SNAKE_CASE`. Private attrs: `_snake_case`.

**Kafka topics** (always via `src/core/stream_keys.py`, never hardcoded)
- Functions: `topic_<output_domain>()` — singular noun describing what flows in the topic
- Strings: `<env>.<domain>` or `<env>.<domain>.<sublayer>` — **dots only, never colons**
- Consumer groups: `<concept>_consumer` (idempotent on restart)

**Database**
- Tables: `snake_case` plural nouns. Columns: `snake_case` — timestamp is `ts` (not `feature_ts`); always `symbol`, `tf`
- Views: `<source_table>_<timeframe>` — `ohlcv_15m`, `market_data_5m`. Migrations: `NNN_description.sql`.

**Systemd / Infrastructure**
- Units: installed in `/etc/systemd/system/`; source files in `services/`. `production/systemd/` is a reference dir — do not treat as authoritative.
- Logs: `logs/<python_service_filename>.log` — read directly for structured output (journald shows only `print()`)

**Tests / TypeScript / Docs**
- Tests: `tests/unit/test_<module>.py`; functions `test_<what>_<condition>`
- TypeScript: components `PascalCase.tsx`, hooks `use-kebab-case.ts`, utils `kebab-case.ts`
- Docs: `kebab-case.md`; plan docs `YYYY-MM-DD-<topic>.md`; uppercase `README.md`/`CLAUDE.md`/`CHANGELOG.md`

## Architecture Overview

```
Layer 4: AI Intelligence (I8)              -> LLM analysis, Ollama qwen3.5:9b
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

**Intelligence Pipeline:**
```
IBKR TWS → feature_compute_agent (I1-I6 unified) →
  signal_generator_service (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer_service`.

## Key Components

### Active Services
| Service | Unit | Purpose | Metrics |
|---------|------|---------|---------|
| IBKR Provider | `indicagent-ibkr-provider` | IBKR dual streams: 5s RTB → 1m aggregation + official reconciliation; publishes to `market.bars.raw.ibkr` | :9129 |
| Provider Merger | `indicagent-provider-merger` | Routes `market.bars.raw.<provider>` → `market.bars`; auto-failover on primary silence; ProviderQualityEvent quality side-channel | :9130 |
| Bar Aggregator | `indicagent-bar-aggregator-compute` | 1m→HTF bar aggregation (5m-1d) via BarAccumulator; publishes to `market.bars.htf` | :9120 |
| Bar Writer | `indicagent-bar-writer` | market.bars + market.bars.htf → market_data_ohlcv batch writer | :9121 |
| Bar Auditor | `indicagent-bar-auditor` | Gap detection → market.events.gap_requests | :9123 |
| Feature Compute | `indicagent-feature-compute` | I1-I6 unified pipeline; subscribes to `market.bars` + `market.bars.htf` → `intelligence:SYMBOL:TF` | :9125 |
| Intelligence Compute | `indicagent-intelligence-compute` | I7/I8 standalone (DB-ignorant compute loop; warmup via `BarHistorySeeder`) → `intelligence:SYMBOL:TF` | :9114 |
| Signal Generator | `indicagent-signal-generator` | I7: setups → `signal_ledger`; bar_history fed from IntelligenceEvent stream | :9112 |
| Signal Tracker | `indicagent-signal-tracker` | Zone-aware lifecycle: activation, MAE/MFE, 8-class outcome (Phase 52.4: renamed from signal-lifecycle, inherits BaseAgent) | :9115 |
| AI Narrative | `indicagent-ai-narrative` | I8: LLM → `narratives:SYMBOL:TF` | :9113 |
| Feature Writer | `indicagent-feature-writer` | Redpanda → `intelligence_features` batch writer | :9116 |
| LLM Writer | `indicagent-llm-writer` | `llm.calls` → `llm_calls` hypertable + outcome back-fill + score cache | :9117 |
| Cross-Asset Service | `indicagent-cross-asset` | Cross-asset spread dynamics + I7 feed → `development.cross_asset` | :9118 |
| API | `indicagent-api` | FastAPI + SSE on :8000 | — |

### Core Runtime Files
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `PLUGIN_METRICS_SAMPLE_RATE`
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)

## Data Flow

### Hot/Warm/Cold Tiers
```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: BarWriterAgent + feature_writer_service → TimescaleDB (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV (backfill + live via BarWriterAgent; keep forever — ground truth).
- `intelligence_features` — full feature vectors per bar incl. i7/i8 JSONB (ML training dataset; keep forever). Column name is `ts` not `feature_ts`.
- `signal_ledger` — ALL I7 signals per bar (not just winner) + lifecycle outcomes; JOIN via `(symbol, feature_ts, feature_tf)` (keep forever). Phase 49.1: signal_generator_service writes every signal to the ledger regardless of regime eligibility — winner published to stream separately.
- `llm_calls` — full LLM audit log per call; outcome back-filled by `llm_writer_service` (keep forever)
- `llm_model_scores` — per-model win rate / avg pnl_r / p-value; refreshed every 15 min
- `setup_performance` — per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); drives aggregator `perf_multiplier`; only rows with `sample_size >= 30` are written (FEED-02 gate)
- Aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`
- **Volume Profile field selection**: `poc_price`/`vah`/`val` = session VP (resets daily — use for 1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (structural — use for 15m/1h). `price_in_value_area`, `distance_to_vah_atr`, `distance_to_val_atr` already computed in I4Context — no recalculation needed downstream.

### TimescaleDB Gotchas (Common)
- **DB shell:** `docker exec timescaledb psql -U postgres -d indicagent` — container is `timescaledb`
- **VACUUM:** Cannot run inside a transaction block — use standalone `psql -c "VACUUM ..."`
- **`instruments` table key is base symbol**: `symbol` column stores base (e.g., `PL`, `SOL`, `ES`), NOT the contract code. Contract code lives inside `contract_details->>'symbol'`. The API spreads `json.loads(contract_details)` so the JSONB `symbol` key overrides the DB key in API responses. To deactivate: `UPDATE instruments SET is_active = FALSE WHERE symbol IN ('PL', 'SOL')`.
- **`instruments.contract_details` is stored as a JSON string**: `jsonb` column stores a serialized string value, not a JSON object. `jsonb_typeof(contract_details)` returns `"string"`, so `->>'field'` operators don't work directly in SQL. Use Python `json.loads()` to parse, or in SQL: `(contract_details #>> '{}')::jsonb->>'field'`.
- **`market_data_ohlcv` missing index**: `CREATE INDEX ON market_data_ohlcv (symbol, timeframe, timestamp DESC);` — without this, ORDER BY DESC LIMIT queries scan all 10k chunks and time out. Omit CONCURRENTLY (not supported on hypertables).
- **Advanced patterns:** See `docs/operations/timescaledb-gotchas.md` for autovacuum, chunk iteration, materialized views, compression jobs, pg_stat_statements, and migration patterns.

## Plugin System

121 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name
- **LLM provider rotation**: `ai_narrative_service.py` uses `LLMChain` with ordered fallback. Multiple free OpenRouter models (`:free` suffix) prevent rate limit failures. Define shared provider lists as module-level constants to avoid duplication across chains.
- **`order_blocks.py` pre-filters to unmitigated OBs**: `_check_mitigated()` runs before output — `ob_type/top/bottom` always represents an unmitigated block. Downstream scoring (I6, trade_framer) does not need to re-check mitigation status.
- **`cross_timeframe.py` already has multi-TF data**: `compute_full(frames)` iterates `intel_<tf>` keys (lines 89-92) — FVG/OB/VP outputs from all active TFs flow through automatically. Cross-TF scoring only needs the scoring function, no new data routing.
- **HTF frame injection pattern**: `signal_generator_service._cross_asset_cache: dict[str, dict]` (tf → payload) is the canonical pattern for injecting per-TF external data into plugin frames before `compute_full()`. Replicate for any new per-TF source (e.g., `_htf_intel_cache`). Zero new subscriptions — populate cache from existing stream, inject into `frames` dict.
- **I7 utilities** (check before creating new): `exhaustion_utils.py` (`apply_exhaustion_boost`, `apply_exhaustion_guard`); `signal_schema.py` (`make_signal`, `validate_signal`); `plugin_utils.py` (`no_signal`, `extract_ohlcv`, `signal_type_for_direction`); `atr_utils.py` (`get_atr` — null-safe I1 accessor, never recompute ATR in I7); `state_utils.py` (`track_consecutive_state`, `reset_consecutive_state`); `confidence_utils.py` (`compose_confidence` — ALL I7 confidence values must route through this; `capture_signal_features` — writes shadow dict for ML training); `microstructure_utils.py` (`detect_spike_signal` — shared OFI/CVD spike logic); `volume_profile_utils.py` (`check_reversal_gate`, `format_reversal_supporting_factors`). `composites/common.py` utilities (`is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`) are I2-only — evaluate before using in I7.

### Signal Identity Preservation (Renaissance Principle)

**Never merge informationally distinct signals into a parameterized class.** OFI (order book intent) and CVD (aggressive execution) are separate ML feature columns — `trad_OFIDivergence` and `trad_CVDDivergence` must remain independent. Same rule for VWAP (3 plugins), liquidity (3 plugins). Extract shared *computation* to utilities; never collapse *identity*.

### I6 → I7 Confluence Obligation (Renaissance Principle)

**Every I7 plugin must consume relevant I6 `ctf_*` sub-scores in its confidence calculation.** Weight by setup family:
- **Trend-following** → `ctf_trend_alignment`, `ctf_score` (heavy weight)
- **Mean-reversion** → `ctf_regime_agreement`, `ctf_structure_alignment`
- **SMC/FVG** → `ctf_fvg_alignment`, `ctf_ob_alignment`
- **Microstructure** (OFI/CVD) → `ctf_score` as a *gate* (suppress signal if CTF disagrees)

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues.
- **Enum migrations:** When replacing raw strings with enums, update function signatures to return the enum type (not `str`). Extend enum from `str` (e.g., `class SignalOutcome(str, Enum)`) for DB compatibility without migrations.
- **Hot-path optimization:** Extract repeated list/struct construction to module-level constant tuples to avoid allocation in loops. Use tuples for immutability.
- **Re-exports:** Use explicit `__all__` export list instead of `# noqa` comments for backward compatibility re-exports.
- **CodeRabbit limits**: 150 files max per review. Use `--base HEAD~N` to review recent commits. Process can get killed (exit code 137/OOM) on large diffs — review smaller chunks.
- **CodeRabbit on main**: `coderabbit review --plain -t all` fails with "no merge base" when on main. Use `-t uncommitted` instead.
- **Simplify workflow**: Launches 3 parallel agents (reuse, quality, efficiency) — finds duplication, missing utilities, inefficient patterns.
- **Documentation accuracy**: Docs may contain fabricated content (nonexistent classes, functions, DB tables) written as forward-looking specs never implemented. Always verify doc claims against actual code (`src/`) before trusting them — if a doc references a class or function, grep for it first.

### Key Rules

**Documentation Framing**
- **Data source language**: IndicAgent is provider-agnostic — docs/READMEs must not describe it as "IBKR-powered" or tie the product identity to any specific broker. Use "real-time market data" or "any real-time source". IBKR is the current implementation detail and belongs only in technical/operational sections.

**Core Patterns**
- **`KafkaProducerClient` / `KafkaConsumerClient`**: Infrastructure utilities in `src/core/` — not Agents or Services. `Client` suffix is correct; do not apply `PascalCaseService` or `PascalCaseAgent` rules to them.
- **Timestamps: always UTC.** All datetimes must be timezone-aware UTC — `datetime.now(UTC)` or `datetime.now(tz=UTC)`. Never `datetime.now()` (naive) or `datetime.utcnow()` (naive despite the name). When labeling a naive timestamp from an external source (e.g. IBKR bars), use `replace(tzinfo=UTC)` only if you are certain the source is already UTC — otherwise `astimezone(UTC)`. All DB columns are `timestamp with time zone`; all stream timestamps are UTC ISO-8601 (`Z` suffix).
- **asyncpg batch inserts**: `execute_batch()` / `executemany()` requires Python `datetime` objects for `timestamptz` columns — ISO-8601 strings cause type mismatch. SQL `::timestamptz` casts work for single inserts but not batch mode. Use `_parse_ts()` from `feature_writer_service.py` or parse with `datetime.fromisoformat()` before inserting.
- **Async Database Operations (Default)**: Use `asyncpg` for all new database code — never `psycopg2`. Connection: `conn = await asyncpg.connect(settings.database_url)` or pool context `async with asyncpg.create_pool(settings.database_url) as pool:`. Scripts: wrap entry point in `asyncio.run(_amain(args))`. All DB calls use `async/await`. JSONB: asyncpg returns Python `dict` (no `json.loads()` needed). Timestamps: asyncpg returns `datetime` objects (no parsing for `timestamptz`).
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **API route Settings cache**: `_resolve_contract()` in API routes must use `@lru_cache(maxsize=1)` on `_get_settings()` — not `Settings()` fresh per call. See `sse.py` for the canonical pattern.
- **Metrics**: create via `src/observability/metrics.py` to prevent duplicate registration.
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests are CI-clean; integration requires live infra.
- **Ruff**: always run `.venv/bin/ruff check .` from project root (not absolute paths).

**Service & Test Patterns**
- **Services**: graceful SIGINT/SIGTERM, drain queues, idempotent consumer groups.
- **feature_compute_agent subscribes to:** `topic_market_bars` (1m bars) AND `topic_market_bars_htf` (HTF bars from BarAggregatorComputeAgent). Each bar triggers an independent I1-I6 pipeline run. BarAccumulator extraction (Phase 53.2) eliminated the feedback loop concern.
- **HTF bar flow:** TWS → 1m bars → market.bars → bar_aggregator_agent (BarAccumulator) → market.bars.htf → feature_compute_agent (I1-I6) + signal_generator (I7) → intelligence_features.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`. **All service logs go to `logs/<service>.log` via `setup_service_logging()` — NOT to journald.** journalctl only shows `print()` output. Read log files directly for structured service output.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Async mock gotcha**: `AsyncMock` with instance-level `__aiter__` silently yields 0 iterations — Python dunder lookup is on the type. Define `__aiter__` at class level in a real class when mocking async iterables (e.g., AIOKafkaConsumer).
- **OTel carrier `get()` signature**: OTel's `DefaultGetter` calls `carrier.get(key, default)` with 2 args. Any `TextMapPropagator` carrier must accept `get(self, key, default=None)` or runtime `TypeError` occurs.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise service silently fails mid-test with a misleading error.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

**Data & Database**
- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **`bar_close_price` implicit**: no need to store in `signal_ledger` — JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` gives full bar OHLCV including close price.
- **_STANDARD_TFS configuration:** When adding new timeframes, update 2 locations: (1) `feature_compute_agent.py` `_STANDARD_TFS` tuple, (2) `BarAccumulator._TF_MINUTES` dict in `src/core/bar_accumulator.py`. BarAccumulator initialization auto-uses `_TF_MINUTES.keys()` as default. Missing one causes aggregation or warmup failures.
- **Canonical bar enforcement:** With continuous 1m bar flow (60 bars/hour), BarAccumulator emits: 24× 1h/day, 6× 4h/day, 1× 1d/day. Session break logic at RTH close prevents cross-session contamination. Overnight gaps don't skip bars—period boundary crossing on next 1m bar triggers emission of accumulated HTF bar.

**Signal Logic**
- **Terminal event payload**: `_publish_terminal_event` sends both `status` and `outcome` fields (identical values). Dashboard must read `payload.outcome` — `payload.status` works today but is semantically wrong and fragile if the two ever diverge.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"` are raw string literals across `signal_ledger.py`, `lifecycle_tracker.py`, `signal_generator_service.py`, `signal_lifecycle_service.py` — no enum. Avoid adding new status comparisons without consolidating.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts — raw `signals` never get `adjusted_rank` set. If `active` is derived from raw `signals`, `perf_weights` have zero effect on winner selection (only on `all_ranked` ordering). Always derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]`.

**Dashboard:** See `docs/dashboard/GOTCHAS.md` for SSE re-render optimization, payload parsing, Next.js HMR, layout modes, and runtime API detection.

## Infrastructure

- **Sudo:** `echo 'PASSWORD' | /usr/bin/sudo.ws -S <cmd>` — plain sudo active via `update-alternatives` (switched 2026-03-15; sudo-rs blocked stdin). For heredocs, write to `/tmp` first then `sudo cp`. Password stored in memory, not here.
- **Server IP:** `192.168.1.158` (Ethernet, `enp2s0`). IBKR TWS at `192.168.1.157` — if TWS connection refused, check trusted IPs in TWS API settings.
- **IBKR**: VIX=`"VX"`, client IDs 35+. All ib_insync in `src/providers/ibkr.py` only. See `src/providers/CLAUDE.md` for asset-class details.
- **Redpanda**: Kafka-compatible streaming backbone. Topic naming: dots not colons — `development.market.bars`. Always via `stream_keys.py`.
- **Redpanda topic retention**: All `development.*` topics must have `retention.ms=604800000` (7 days) set explicitly — broker default is shorter and purges seeded I1 messages over weekends. Set with: `docker exec redpanda rpk topic alter-config <topic> --set retention.ms=604800000`. Confirmed set on `development.indicators` 2026-03-15.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.
- **IBKRProviderAgent contract rollover**: Daemon reads contracts ONCE at startup. When futures expire (H6→M6/J6), restart: `sudo systemctl restart indicagent-ibkr-provider`. Verify: `journalctl -u indicagent-ibkr-provider | grep "KafkaProducerClient started"`
- **Docker containers on reboot**: `timescaledb` and `redpanda` containers have no restart policy and exit on server reboot — all indicagent services fail immediately. Fix: `docker start timescaledb redpanda` then restart services. Long-term: add `restart: unless-stopped` to both containers.

## Data Pipeline Debugging

When investigating "service not writing to database":
1. **Check service health metrics first** — `events_consumed` and `batches_written` in logs. If increasing, service is working.
2. **Check which symbols ARE in target table** — `SELECT DISTINCT symbol FROM intelligence_features WHERE ts > NOW() - INTERVAL '2 hours';`
3. **Trace data flow upstream** — TWS → bars → indicator → intelligence → feature_writer → DB
4. **Verify service configs include the symbol** — Check startup logs for `"symbols"` list
5. **Check prerequisite data exists** — New contracts need historical backfill before intelligence pipeline processes them
6. **Kafka/IBKRProvider verification** — `docker exec redpanda rpk topic consume development.market.bars --offset N` (or `--from-end`). Provider emissions: `journalctl -u indicagent-ibkr-provider --since "2 minutes ago" | grep "1m bar emitted"`. If bars emitted but Kafka stale: `grep "Published to Kafka successfully"`. Merger routing: `journalctl -u indicagent-provider-merger --since "2 minutes ago"`.

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `IBKR_HOST=192.168.1.157`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=qwen3.5:9b`

## Roadmap

**v2.0 SHIPPED 2026-03-22** — Phases 39-47. DAG refactor, feature pipeline unification, I6/I7 confluence wiring, shadow mode graduation.
**v2.1 IN PROGRESS** — Phases 48-53.3. Phase 48 complete; 49.1/49.2 complete; 52.1/52.2/52.3 complete. Phases 52.4/52.5/53.1/53.2/53.3 planned. See `.planning/ROADMAP.md` for active phase details.
**v2.2 PLANNED** — Phase 54: auth + external access. Plans in `.planning/phases/53-auth-external-access/`. Revisit Cloudflare Access vs JWT before executing.
**v2.3 DEFERRED** — Phases 55-56: ML scoring + Renaissance observability. Requires 30+ days clean signal data from v2.1.
