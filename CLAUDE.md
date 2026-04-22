# CLAUDE.md

Version: 5.33.0 | Status: v2.2 IN PROGRESS — see `.planning/ROADMAP.md` for current phase.

## Renaissance Principles
- **Instrument everything.** No data point left uncaptured. If it happened, it should be measurable.
- **Let the system run.** Don't override data with intuition. Build the automation, then trust it.
- **Earn the right through proof.** No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Shadow mode first, always.
- **Segment relentlessly.** A rule that works globally is weaker than one that works in a specific regime. Always ask: "under what conditions does this hold?"
- **Degrade gracefully, adapt automatically.** Systems that require manual tuning are fragile. Build feedback loops that self-correct.
- **Data quality over model complexity.** Clean, complete data beats a smarter model on dirty data every time.
- **Never drop data that could contain signal.** Storage is the cheapest thing we own. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered.

**Agentic DAG Architecture:** ComputeAgents (I1-I6) are DB-ignorant, publish to tiered topics (`intelligence.i{N}`), DataWriterAgents manage persistence. WriterAgents use "Convergence Gate" (StreamMerger) for atomic persistence. All agents maintain DLQ (`intelligence.[domain].journal.dlq`). Scaling: systemd + Prometheus lag monitoring (no Kubernetes HPA).

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
.venv/bin/pytest tests/unit/ -v
.venv/bin/ruff check . --fix && .venv/bin/black .
sudo systemctl start indicagent-intelligence-pipeline
cd dashboard && npm run dev
/simplify && /coderabbit:code-review  # pre-commit mandatory
```

**Requires:** Python 3.11+, Docker (TimescaleDB, Redpanda), systemd, Node.js 18+.

## Core Commands

**Tests:** `.venv/bin/pytest tests/unit/ -v` · **Lint:** `.venv/bin/ruff check . --fix` · **Format:** `.venv/bin/black .`
**Dashboard:** `cd dashboard && npm run dev` (`:3000`)
**API:** `uvicorn src.api.main:app` (`:8000`)
**Service status:** `systemctl list-units --all | grep indicagent`
**Consumer lag:** `docker exec redpanda rpk group describe feature_pipeline -t`
**Full reference:** `docs/cheatsheet.md`

---

## Naming Conventions

**Principle (Renaissance rule):** A service's *concept name* (`snake_case`, no suffix) determines all its derived names across every layer. Given `feature_pipeline`, every layer's name is mechanically derivable — no lookup needed.

### Cross-Layer Transformation Rules

| Layer | Pattern | Example (`alpha_signal`) |
|-------|---------|------------------------------|
| Python file (Service) | `<concept>_service.py` | `alpha_signal_service.py` |
| Python file (Agent) | `<concept>_agent.py` | `alpha_signal_agent.py` |
| Python file (Plugin) | `src/intelligence/trading/<concept>.py` | `alpha_signal.py` |
| Python class (Service) | `PascalCase` + `Service` | `AlphaSignalService` |
| Python class (Agent) | `PascalCase` + agent role suffix | `AlphaSignalComputeAgent` |
| Python class (Plugin) | `PascalCase` + `Plugin` | `AlphaSignalPlugin` |
| Systemd unit | `indicagent-<concept-kebab>.service` | `indicagent-alpha-signal.service` |
| Kafka topic fn | `topic_<concept>()` in `stream_keys.py` | `topic_alpha_signal()` |
| Kafka topic string | `<env>.<domain>[.<sublayer>]` (dots only) | `dev.alpha_signal` |
| DB table | `snake_case` plural noun | `alpha_signals` |
| DB columns | `snake_case` | `ts`, `symbol`, `tf`, `i7` |

**Agent role suffixes:**
- `ProviderAgent` — external source→Kafka, no compute/DB
- `ComputeAgent` — math/stats transform, DB-ignorant
- `GeneratorAgent` — signal/trade fire
- `WriterAgent` — DB persistence
- `TrackerAgent` — business object lifecycle
- `AuditorAgent` — data integrity validation + self-healing

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
Layer 4: AI Intelligence (I8)              -> LLM analysis, Ollama gemma4:e4b
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

**Intelligence Pipeline:**
```
IBKR TWS → intelligence_pipeline_agent (I1-I7 unified, in-process) →
  signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer_service`.

## Key Components

### Active Services (key services — full list: `systemctl list-units --all | grep indicagent`)

| Service | Unit | Purpose |
|---------|------|---------|
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | I1-I7 unified in-process pipeline; subscribes to `market.bars` + `market.bars.htf`; outputs to `signal_ledger` + Kafka `intelligence.*` topics |
| IBKR Provider | `indicagent-ibkr-provider` | IBKR dual streams: 5s RTB → 1m aggregation + official reconciliation |
| Bar Aggregator | `indicagent-bar-aggregator` | 1m→HTF bar aggregation (5m-1d) via BarAccumulator |
| Feature Writer | `indicagent-feature-writer` | Redpanda → `intelligence_features` batch writer |
| Signal Writer | `indicagent-signal-writer` | `intelligence.*` → `signal_ledger` batch writer |
| Signal Tracker | `indicagent-signal-tracker-compute` | Zone-aware lifecycle (DB-ignorant compute); publishes transitions to `LifecycleWriterAgent` |
| Lifecycle Writer | `indicagent-lifecycle-writer` | Persists signal lifecycle transitions to `signal_ledger` |
| ML Data Quality | `indicagent-ml-data-quality` (timer) | Audits `intelligence_features` for training data quality |
| ML Discovery | `indicagent-ml-discovery` (timer) | Discovers ML training signal patterns |
| ML Orchestrator | `indicagent-ml-orchestrator` (timer) | Orchestrates ML training pipeline |
| Swarm Orchestrator | `indicagent-swarm-orchestrator` | Routes swarm tasks to specialist agents |
| Swarm Writer | `indicagent-swarm-writer` | Persists swarm outputs to DB |
| AI Narrative | `indicagent-ai-narrative` | I8: LLM → `narratives:SYMBOL:TF` |
| API | `indicagent-api` | FastAPI + SSE on :8000 |

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

**Signal lifecycle is a different concern from signal generation.** Generation is real-time compute (ms latency, per-bar). Lifecycle is business object tracking (minutes to days, state accumulates). The signal tracker is the only service that violates the compute→Kafka→writer DAG pattern — it reads and writes signal_ledger in the same process. Fix plan: `docs/plans/2026-04-10-pipeline-health-fixes-design.md`.

### TimescaleDB Tables
- `market_data_ohlcv` — raw OHLCV (backfill + live via BarWriterAgent; keep forever — ground truth). Primary time column is `timestamp` (not `ts`); columns: `timestamp`, `symbol`, `timeframe`, `open`, `high`, `low`, `close`, `volume`, `source`, `base`.
- `intelligence_features` — full feature vectors per bar incl. i7/i8 JSONB (ML training dataset; keep forever). Column name is `ts` not `feature_ts`.
- `signal_ledger` — ALL I7 signals per bar (not just winner) + lifecycle outcomes; JOIN via `(symbol, feature_ts, feature_tf)` (keep forever). Phase 49.1: signal_generator_service writes every signal to the ledger regardless of regime eligibility — winner published to stream separately.
- `llm_calls` — full LLM audit log per call; outcome back-filled by `llm_writer_service` (keep forever)
- `llm_model_scores` — per-model win rate / avg pnl_r / p-value; refreshed every 15 min
- `setup_performance` — per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); drives aggregator `perf_multiplier`; only rows with `sample_size >= 30` are written (FEED-02 gate)
- Aggregate views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`
- **Volume Profile field selection**: `poc_price`/`vah`/`val` = session VP (resets daily — use for 1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (structural — use for 15m/1h). `price_in_value_area`, `distance_to_vah_atr`, `distance_to_val_atr` already computed in I4Context — no recalculation needed downstream.

### TimescaleDB Gotchas
`docker exec timescaledb psql -U postgres -d indicagent` — `instruments.symbol` = base, contract code in `contract_details`. See `docs/operations/timescaledb-gotchas.md`

## Plugin System

128 plugins + 2 aggregation across tiers I1–I7 (I1=28, I2=11, I3=9, I4=13, I5=16, SMC=13, I6=1, I7=37). See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name
- **I7 utilities** (check before creating new): `atr_utils.py` (get_atr), `confidence_utils.py` (compose_confidence, capture_signal_features), `exhaustion_utils.py`, `microstructure_utils.py`, `plugin_utils.py`, `signal_schema.py`, `state_utils.py`, `volume_profile_utils.py`
- **Signal identity:** Never merge informationally distinct signals (OFI ≠ CVD, VWAP variants separate)
- **I6→I7 confluence:** Every I7 must consume relevant `ctf_*` sub-scores (trend→ctf_trend_alignment, mean-reversion→ctf_regime_agreement, SMC/FVG→ctf_fvg_alignment/ctf_ob_alignment)
- **Pipeline optimization status:** I1/I7 tiers are parallelized (via `asyncio.gather` + ThreadPoolExecutor in `intelligence_pipeline_agent.py`), but I2-I6 tiers remain sequential — this is the current bottleneck. GIL contention prevents threading from achieving true parallelism; individual plugin vectorization (e.g., OBVMomentum 46x faster) doesn't improve overall throughput.
- **When optimizing plugins:** Profile first with Renaissance principles — measure → fix biggest lever → measure. Don't optimize individual plugins without confirming the bottleneck is in that tier.

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues. See `docs/operations/infrastructure-reference.md` for CodeRabbit limits and pre-commit hook details.
- **Enum migrations:** When replacing raw strings with enums, update function signatures to return the enum type (not `str`). Extend enum from `str` (e.g., `class SignalOutcome(str, Enum)`) for DB compatibility without migrations.
- **Hot-path optimization:** Extract repeated list/struct construction to module-level constant tuples to avoid allocation in loops. Use tuples for immutability.
- **Documentation accuracy:** Docs may contain fabricated content (nonexistent classes, functions, DB tables) written as forward-looking specs never implemented. Always verify doc claims against actual code (`src/`) before trusting them — if a doc references a class or function, grep for it first.

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
- **intelligence_pipeline_agent subscribes to:** `topic_market_bars` (1m bars) AND `topic_market_bars_htf` (HTF bars from BarAggregatorComputeAgent). Each bar triggers an independent I1-I7 in-process pipeline run.
- **HTF bar flow:** TWS → 1m bars → market.bars → bar_aggregator_agent (BarAccumulator) → market.bars.htf → intelligence_pipeline_agent (I1-I7 unified) → signal_ledger + intelligence_features.
- **Logging**: `structlog` with fields `timestamp`, `service`, `symbol`, `timeframe`, `level`. **All service logs go to `logs/<service>.log` via `setup_service_logging()` — NOT to journald.** journalctl only shows `print()` output. Read log files directly for structured service output.
- **`PYTHONUNBUFFERED=1` required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing even from print().
- **`setup_service_logging` requires full log path**: pass `"logs/<name>.log"` (e.g. `setup_service_logging("logs/signal_writer_agent.log")`), not a bare name — bare name causes runtime failure on log file creation.
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`**: `.labels(agent_id="my_agent")` — not `agent=`. Always check `src/observability/metrics.py` label names before using any labeled metric.
- **Mock gotcha**: `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0.
- **Async mock gotcha**: `AsyncMock` with instance-level `__aiter__` silently yields 0 iterations — Python dunder lookup is on the type. Define `__aiter__` at class level in a real class when mocking async iterables (e.g., AIOKafkaConsumer).
- **OTel carrier `get()` signature**: OTel's `DefaultGetter` calls `carrier.get(key, default)` with 2 args. Any `TextMapPropagator` carrier must accept `get(self, key, default=None)` or runtime `TypeError` occurs.
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise service silently fails mid-test with a misleading error.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.

**Data & Database**
- **TimescaleDB migration**: Never use pg_dump/restore for hypertables — chunks do not restore cleanly. Use raw volume copy: `docker run --rm -v old-vol:/src:ro -v new-vol:/dst alpine sh -c "cd /src && cp -a . /dst/"`. Also: `pg_dump` with `2>&1` corrupts `--Fc` binary output — always redirect stderr separately.
- **Disable compression order**: Must `SELECT decompress_chunk(...)` on all compressed chunks BEFORE `ALTER TABLE SET (timescaledb.compress = false)` — the ALTER fails if any chunk is still compressed.
- **signal_ledger columns**: `exit_at` (not `exit_ts`), `activated_at`, `outcome`, `exit_reason`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`. Primary time column is `timestamp` (not `ts` or `feature_ts`).
- **signal_ledger garbage cleanup**: When lifecycle tracker bootstrap fails, pending signals accumulate forever. Clean up with direct DELETE — never expire+mark. `DELETE FROM signal_ledger WHERE exit_reason IN ('bulk_startup_expire', 'orphaned_pre_restart');` then `DELETE FROM signal_ledger WHERE status = 'pending' AND exit_at IS NULL;`. Rule: always hard DELETE garbage rows, never leave stale data.
- **signal_ledger valid exit_reason values**: `ttl_expired`, `stop_loss`, `bulk_startup_expire`, `orphaned_pre_restart`. Valid outcome values: `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind` (see `chk_signal_ledger_outcome` constraint).
- **`bar_close_price` implicit**: no need to store in `signal_ledger` — JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` gives full bar OHLCV including close price.
- **_STANDARD_TFS configuration:** When adding new timeframes, update 2 locations: (1) `intelligence_pipeline_agent.py` `_STANDARD_TFS` tuple, (2) `BarAccumulator._TF_MINUTES` dict in `src/core/bar_accumulator.py`. BarAccumulator initialization auto-uses `_TF_MINUTES.keys()` as default. Missing one causes aggregation or warmup failures.
- **Canonical bar enforcement:** With continuous 1m bar flow (60 bars/hour), BarAccumulator emits: 24× 1h/day, 6× 4h/day, 1× 1d/day. Session break logic at RTH close prevents cross-session contamination. Overnight gaps don't skip bars—period boundary crossing on next 1m bar triggers emission of accumulated HTF bar.

**Signal Logic**
- **Terminal event payload**: `_publish_terminal_event` sends both `status` and `outcome` fields (identical values). Dashboard must read `payload.outcome` — `payload.status` works today but is semantically wrong and fragile if the two ever diverge.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"` are raw string literals across `signal_ledger.py`, `lifecycle_tracker.py`, `intelligence_pipeline_agent.py` — no enum. Avoid adding new status comparisons without consolidating.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts — raw `signals` never get `adjusted_rank` set. If `active` is derived from raw `signals`, `perf_weights` have zero effect on winner selection (only on `all_ranked` ordering). Always derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]`.

**Dashboard:** See `docs/dashboard/gotchas.md` for SSE re-render optimization, payload parsing, Next.js HMR, layout modes, and runtime API detection.

## Infrastructure

- **Server IP:** `192.168.68.53` (Ethernet, `enp2s0`). IBKR TWS at `192.168.1.157`.
- **IBKR**: VIX=`"VX"`, client IDs 35+. All ib_insync in `src/providers/ibkr.py` only.
- **Redpanda**: Kafka-compatible streaming backbone. Topic naming: dots not colons. Always via `stream_keys.py`.
- **Redpanda topic retention**: Redpanda is transport, not storage — once persisted to TimescaleDB, data is redundant. Retention tiers defined in `production/scripts/kafka_init_topics.py`: `_HOT_MS` (2h, ticks), `_BUFFER_MS` (1 day, everything persisted to DB), `_HTF_MS` (3 days, HTF bars need accumulation window). At 55 symbols, 7-day retention on intelligence topics consumed 89 GB — keep retention minimal.
- **Contracts**: always use `get_active_contracts()` from `src/config/settings.py` — never hardcode.
- **IBKRProviderAgent contract rollover**: Daemon reads contracts ONCE at startup. Restart on futures expiry: `sudo systemctl restart indicagent-ibkr-provider`.
- **Futures contract roll flow:** `RollComputeAgent` detects roll (volume z-score or calendar) → publishes `RollEvent` → `ContractMetadataWriterAgent` sets `is_front_month` in `contract_metadata` → `get_active_contracts()` reads that table → `IBKRProviderAgent` re-qualifies on restart. All four steps must complete. Always restart `indicagent-ibkr-provider` after any `contract_metadata` change.
- **Energy/metals futures expiry** (`src/config/contracts.py`): CME rule = 3 business days before the 25th of the month prior to delivery month (not "last business day of prior month"). Example: CLK6 (May delivery) expires ~April 21, not April 30. Wrong formula = roll_end computed 9 days late = roll never fires before expiry.
- **Manual roll recovery** (when roll agent missed a cycle): `INSERT INTO contract_metadata (symbol, base_symbol, asset_class, expiry_date, roll_from, roll_to, roll_date, exchange, is_front_month, roll_direction, roll_detected_at, confirmation_count) VALUES ('CLM6', 'CL', 'futures', '<expiry>+00', 'CLK6', 'CLM6', NOW(), 'NYMEX', true, 'unknown', NOW(), 0);` then `UPDATE contract_metadata SET is_front_month = false WHERE symbol = 'CLK6';` then restart `indicagent-ibkr-provider`.
- **Roll investigate:** `grep "calendar_roll_fired\|startup_sweep" logs/roll_compute_agent.log` — startup sweep fires overdue rolls at agent start; bar-loop fires during live trading.
- **Docker containers on reboot**: `timescaledb` and `redpanda` both have `restart: unless-stopped` — no manual start needed.
- **Systemd unit conventions:** `production/systemd/` is reference templates. Installed units in `/etc/systemd/system/` — check `systemctl status` for authoritative state.

> Sudo details, INDICAGENT_ENV mismatch, and debugging procedures: `docs/operations/infrastructure-reference.md`

## Roadmap

See `.planning/ROADMAP.md` for current milestone status and phase details.
