# CLAUDE.md

Version: 5.38.0 | Status: v2.5 PARTIAL — Phases 69+71+72+73+74+75+76+77 shipped; Phase 78 at 6/7 (078-07 pending). Phase 70 deferred (~May 10 data gate). Phase 64 core complete; 03C+04 deferred (~May 10 data gate). Next: 078-07 (NarrativeComputeAgent → API endpoint) + ~May 10 data gate.

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
**Full reference:** `docs/cheatsheet.md` · **Roadmap:** `.planning/ROADMAP.md`

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

### Service DAG

The canonical service registry is `_DAG_ORDER` in `services/service_auditor_agent.py`. That dict is the single source of truth — it drives restart priority, lag monitoring, and health escalation. Never maintain a parallel list here.

**Live state:** `systemctl list-units --all | grep indicagent`
**Monitoring:** Grafana `:3001` → `indicagent_service_up` gauge per unit (1=active, 0=failed)
**Health audit trail:** `service_health_events` TimescaleDB table + `system.health.events` Kafka topic
**Self-healing:** `indicagent-service-auditor` auto-discovers units, monitors Prometheus lag, restarts in DAG order, escalates after 3 failures in 10 min

DAG layers (from `_DAG_ORDER`):
```
L1  ibkr-provider                       — data ingestion
L2  provider-merger                      — stream merge
L3  bar-aggregator, bar-auditor          — bar processing
L4  bar-writer                           — OHLCV persistence
L5  intelligence-pipeline, cross-asset,
    macro-compute                        — I1-I7 compute + context
L6  feature-writer, signal-writer,
    signal-tracker-compute, lifecycle-
    writer, lineage-writer,
    contract-metadata-writer             — persistence writers (parallel)
L7  alpha-swarm, ai-narrative,
    llm-writer                           — AI/LLM layer
L8  roll-compute, signal-metrics-*,
    graduation-*, feature-snapshot-writer — analytics + rolling metrics
L9  signal-auditor, parity-auditor,
    alerting-agent                       — audit, parity, alerting
L10 service-auditor                      — meta: monitors + restarts all above
```

ML timers (gated by data quality — inactive between runs):
- `indicagent-ml-data-quality` · `indicagent-ml-discovery` · `indicagent-ml-orchestrator`

### Core Runtime Files
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `PLUGIN_METRICS_SAMPLE_RATE`
- `src/core/ai/` — universal AI agent infrastructure (BaseAIAgent, BaseGroupService, AIContext, AgentOutput, SafeAgentWrapper, LineageRecorder)
- `src/intelligence/ai/` — mandate-based agent groups (alpha, narrative, risk)
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

128 plugins + 2 aggregation across tiers I1–I7 (I1=27, I2=10, I3=8, I4=12, I5=16, SMC=13, I6=6, I7=36). See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing name
- **I7 utilities** (check before creating new): `atr_utils.py` (get_atr), `confidence_utils.py` (compose_confidence, capture_signal_features), `exhaustion_utils.py`, `microstructure_utils.py`, `plugin_utils.py`, `signal_schema.py`, `state_utils.py`, `volume_profile_utils.py`
- **Signal identity:** Never merge informationally distinct signals (OFI ≠ CVD, VWAP variants separate)
- **Shadow governance:** `shadow_registry` DB table is the single source of truth for shadow state. All TIER_I7 plugins auto-enroll at startup (`SHADOW_SKIP: ClassVar[bool] = True` to opt out). Promotion gate: `n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r, alpha=0.05) > 0.0`. Demotion gate: EV[R] < -0.05 for 3 consecutive 30-min audit cycles. `ShadowAuditorAgent` runs every 30 min. ML capture key: `signal["features_snapshot"]` (renamed from `signal["_shadow"]` in Phase 75).
- **I6→I7 confluence:** Every I7 must consume relevant `ctf_*` sub-scores (trend→ctf_trend_alignment, mean-reversion→ctf_regime_agreement, SMC/FVG→ctf_fvg_alignment/ctf_ob_alignment)
- **Pipeline optimization status:** I1/I7 tiers are parallelized (via `asyncio.gather` + ThreadPoolExecutor in `intelligence_pipeline_agent.py`), but I2-I6 tiers remain sequential — this is the current bottleneck. GIL contention prevents threading from achieving true parallelism; individual plugin vectorization (e.g., OBVMomentum 46x faster) doesn't improve overall throughput.
- **When optimizing plugins:** Profile first with Renaissance principles — measure → fix biggest lever → measure. Don't optimize individual plugins without confirming the bottleneck is in that tier.

## Adding an AI Agent

Five steps. Full protocol in `src/intelligence/ai/AUTHORING.md`. Skeleton
in `src/intelligence/ai/TEMPLATE_agent.py`. Canonical reference: `skeptic_agent.py`.

1. **Class attributes** (mandatory five): `agent_id`, `group`, `tiers_needed`,
   `latency_budget_ms`, `shadow_only`. See AUTHORING.md for semantics.
2. **File location**: `src/intelligence/ai/<group>/<name>_agent.py` plus a
   paired `<name>_prompts.py`.
3. **tiers_needed**: Use `Tier` enum. Tiers drive `AIContextCache.build()`
   — only requested tiers populate.
4. **`_compute()` contract**: Build prompt -> call LLM -> parse -> return
   `AgentOutput`. Never raise; use `self._neutral(error=...)` on failure.
   Include `prompt_version` in payload so LineageRecorder attribution is correct.
5. **Prompt file convention**: `<name>_prompts.py` exposes `PROMPT_REGISTRY: dict`
   and `ACTIVE_VERSION: str`. Build function takes the typed AIContext (v2 pattern).

After adding the agent class, register it in the relevant group service
(e.g., `AlphaSwarmComputeAgent._agents`) and call `shadow_registry_ensure()`
at startup so the graduation loop tracks it.

## Development Standards

**Code Quality:** No bandit/safety/snyk installed — `/coderabbit:code-review` catches security issues. See `docs/operations/infrastructure-reference.md` for CodeRabbit limits and pre-commit hook details.
- **Pre-commit hook:** `.githooks/pre-commit` (tracked in git). Covers: plugin class naming, file naming, I7 regime_type, ruff lint (auto-fix), black format (auto-format). Fresh clone requires `git config core.hooksPath .githooks` once to activate. Hook is also installed at `.git/hooks/pre-commit`.
- **Enum migrations:** When replacing raw strings with enums, update function signatures to return the enum type (not `str`). Extend enum from `str` (e.g., `class SignalOutcome(str, Enum)`) for DB compatibility without migrations.
- **Hot-path optimization:** Extract repeated list/struct construction to module-level constant tuples to avoid allocation in loops. Use tuples for immutability.
- **Documentation accuracy:** Docs may contain fabricated content (nonexistent classes, functions, DB tables) written as forward-looking specs never implemented. Always verify doc claims against actual code (`src/`) before trusting them — if a doc references a class or function, grep for it first.

### Key Rules

**Documentation Framing**
- **Data source language**: IndicAgent is provider-agnostic — docs/READMEs must not describe it as "IBKR-powered" or tie the product identity to any specific broker. Use "real-time market data" or "any real-time source". IBKR is the current implementation detail and belongs only in technical/operational sections.

**Core Patterns**
- **`KafkaProducerClient` / `KafkaConsumerClient`**: Infrastructure utilities in `src/core/` — not Agents or Services. `Client` suffix is correct; do not apply `PascalCaseService` or `PascalCaseAgent` rules to them.
- **Kafka is transport, not state store.** Never use a compacted Kafka topic to persist agent state. Hot indicator state (plugin_states, kalman, tod_priors) belongs in a local file checkpoint (`cache/pipeline_checkpoint.json`); bar history belongs in TimescaleDB. The `intelligence.pipeline.state` topic was deleted — do not recreate it.
- **Timestamps: always UTC.** All datetimes must be timezone-aware UTC — `datetime.now(UTC)` or `datetime.now(tz=UTC)`. Never `datetime.now()` (naive) or `datetime.utcnow()` (naive despite the name). When labeling a naive timestamp from an external source (e.g. IBKR bars), use `replace(tzinfo=UTC)` only if you are certain the source is already UTC — otherwise `astimezone(UTC)`. All DB columns are `timestamp with time zone`; all stream timestamps are UTC ISO-8601 (`Z` suffix).
- **asyncpg batch inserts**: `execute_batch()` / `executemany()` requires Python `datetime` objects for `timestamptz` columns — ISO-8601 strings cause type mismatch. Use `_parse_ts()` from `feature_writer_service.py` or parse with `datetime.fromisoformat()` before inserting.
- **Async Database Operations (Default)**: Use `asyncpg` for all new database code — never `psycopg2`. Connection: `conn = await asyncpg.connect(settings.database_url)` or pool context `async with asyncpg.create_pool(settings.database_url) as pool:`. Scripts: wrap entry point in `asyncio.run(_amain(args))`. All DB calls use `async/await`. JSONB: asyncpg returns Python `dict` (no `json.loads()` needed). Timestamps: asyncpg returns `datetime` objects (no parsing for `timestamptz`). UUIDs: asyncpg returns `uuid.UUID` objects — always `str()` before JSON serialization or Kafka publish.
- **`topic_intelligence_i7_signals` payload uses raw pipeline field names**: `setup_plugin` (not `plugin`), `pre_quality_confidence` (not `raw_confidence`), no `signal_id`. Use `signal_dict_to_ranked()` from `src/intelligence/schemas.py` to deserialize — never `RankedSignal(**raw_signal)` directly.
- **structlog `event` kwarg collision**: `event` is structlog's reserved positional argument. Never pass `event=<value>` as a keyword to `.info()`/`.warning()`/`.error()` — causes "multiple values for argument 'event'" at runtime. Use `signal=`, `payload=`, `data=`, etc.
- **Service registry = `_DAG_ORDER` in `services/service_auditor_agent.py`**: single source of truth for all services, restart priority, and lag thresholds. When adding a service, update `_DAG_ORDER`, `_LAG_THRESHOLDS` (if Kafka consumer), and `_AGENT_ID_TO_UNIT` (maps `agent_id` metric label → unit name). Never maintain a parallel list in CLAUDE.md.
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **`INDICAGENT_ENV` must be consistent across ALL services**: Every systemd unit must use the same `INDICAGENT_ENV` value (or omit it entirely). Mixed env prefixes cause services to subscribe to different Kafka topics — producers write to `market.bars` while consumers read from `development.market.bars`, resulting in zero data flow. Verify with: `for svc in /etc/systemd/system/indicagent-*.service; do printf "%-50s %s\n" "$(basename $svc)" "$(grep INDICAGENT_ENV $svc 2>/dev/null | sed 's/.*=//' || echo 'unset')"; done`
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
- **Service test `__new__` pattern**: `tests/unit/service_tests/` uses `ServiceClass.__new__(ServiceClass)` to bypass `__init__`. Any new instance attribute added in `__init__` must also be manually set in test (e.g., `svc._regime_cache = defaultdict(dict)`), otherwise service silently fails mid-test with a misleading error.
- **Pytest**: `.venv/bin/pytest` not bare `python -m pytest`.
- **GSD phase directory padding**: `gsd-sdk` returns `phase_dir` without zero-padding (e.g., `67-observability-alerting-automation`) but actual directories use padded names (`067-*`). If init returns `plan_count: 0` but plan files exist, check both directory variants.
- **ServiceSpec fields in tests**: `ServiceSpec(unit, metrics_port, lag_threshold_messages, dag_order, market_hours_only)` — check `services/service_auditor_agent.py` for current fields before constructing test fixtures.
- **Systemd watchdog discipline**: Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files.

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

**Dashboard:** SSE re-render optimization, payload parsing, Next.js HMR, layout modes, and runtime API detection are documented inline in `dashboard/src/`.

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
- **Docker containers on reboot**: All 11 containers have `restart: unless-stopped`, but this only takes effect after first creation. After adding new services to `docker-compose.yml`, run `cd production && docker compose up -d` once to create them. Full stack: timescaledb, redpanda, ollama, prometheus, grafana, loki, tempo, otel-collector, alertmanager, mlflow, langfuse.
- **Prometheus rule files**: Must be explicitly volume-mounted into the Prometheus container — Prometheus silently loads zero rules if the file isn't present (no error, no warning). Pattern: `./alertmanager-rules.yml:/etc/prometheus/alertmanager-rules.yml:ro`. Verify: `docker exec indicagent-prometheus wget -qO- http://localhost:9090/api/v1/rules`.
- **Visualization stack (four layers):** Grafana (:3001) = ops/time-series (Prometheus metrics, system health); Next.js (:3000) = real-time market intelligence; Python (matplotlib/plotly) = research/analytical output; Apache Superset (:8088, in progress) = SQL analytics against TimescaleDB read-only (like Tableau). Design doc: `docs/ideas/bi-analytics-layer-design.md`.
- **Systemd unit conventions:** `production/systemd/` is reference templates. Installed units in `/etc/systemd/system/` — check `systemctl status` for authoritative state.

> Sudo details, INDICAGENT_ENV mismatch, and debugging procedures: `docs/operations/infrastructure-reference.md`

