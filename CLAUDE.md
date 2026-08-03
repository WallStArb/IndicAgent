# CLAUDE.md

Version: 5.54.3

**Project nature:** Passion/learning project — not a production system. Architectural decisions prioritize correctness, rigor, and institutional-grade thinking. Renaissance Capital / Jim Simons principles are the north star. When giving advice, apply the same rigor you would to a system built to last — do not hedge around operational risk that doesn't apply.

**Principles:** Instrument everything · shadow mode first · data quality over model complexity · never drop data that could contain signal · earn promotion through proof (p<0.05, sufficient N) · segment by regime · automate manual tasks · empirical over theoretical · resist overfitting. Full doc: `docs/foundation/principles.md`.
**Design mindset:** Think as a council of senior engineers at Renaissance Technologies. Data integrity is paramount. Ruthlessly eliminate complexity. Silent wrong answers are worse than loud crashes. Deterministic DAG topology — every node does one thing, data flows one direction, no cycles. SoC: compute ≠ persistence ≠ transport. Async-first. Before committing to a design: (1) survives 10x volume? (2) what fails silently or introduces hidden bias? (3) does the DAG still hold? (4) what manual step does this eliminate?
**5-Step mandate (Musk):** Make requirements less dumb → delete → simplify → accelerate → automate. Run in order. Don't optimize what should be deleted. Don't accelerate in the wrong direction. Don't automate what isn't proven. Full doc: `docs/foundation/musk-5-step-process.md`.
**Naming:** Concept name (`snake_case`) derives all layer names — `signal_tracker` → `SignalTracker`, `indicagent-signal-tracker.service`, `topic_signal_tracker()`, `signal_trackers` table. **Ring rule:** `src/core/`, `src/observability/` = Ring 0 portable infrastructure (no domain vocab, no imports from `services/`); `src/intelligence/` = Ring 1 domain; `services/` = Ring 2 daemons. Topics: dots only, via `stream_keys.py`. Full spec: `docs/foundation/naming-system.md`.
**Glossary:** Every domain term has exactly one definition. Check before naming new concepts; glossary wins over existing code on collision. Full spec: `docs/foundation/glossary.md`.
**Doc locations:** `docs/foundation/` canonical home. `docs/` root is index only. `docs/research/` docs can go filename-stable (edited in place, no longer re-dated on rewrite) — check for a stale `YYYY-MM-DD-<name>.md` fork of an undated doc before citing or editing either.
**Gotchas:** `docs/reference/gotchas.md` — rare pitfalls moved out of per-turn context.
**Performance investigations:** Before touching a batch job that mutates millions of rows against a TimescaleDB hypertable and runs far slower than expected, follow `docs/foundation/performance-investigation-sop.md` — measure (`pg_stat_activity.wait_event`, `iostat -x 1`, `EXPLAIN ANALYZE`) before theorizing, never trust a read-only test for a write-path question, and check chunk count/compression status as first-class suspects. Two independent incidents (todos 149, 161) hit the same shape of bug two weeks apart; don't make it three.
**Planning system:** `.planning/PLANNING-SYSTEM.md` — how IDEAS.md → docs/ideas/ → docs/plans/ → todos/pending/ → ROADMAP.md → phases/ flow into each other. Current phase/progress: `.planning/STATE.md`. Todo prioritization (single source of truth for `pending/`): `.planning/todos/PRIORITIES.md` — drifts out of sync silently (new todos filed without a PRIORITIES.md entry); diff `ls todos/pending/` against it periodically.

## Done-Coding SOP

```
1. /simplify                # clean up changed code (invoke automatically)
2. /review                  # peer code review
3. pytest tests/unit/ -q    # must be green
4. commit on feature branch
5. git checkout main && git merge --ff-only <branch>
6. git branch -d <branch> && git worktree prune
7. git push origin main
```

**GSD-orchestrated phases (`/gsd-execute-phase`) enforce step 1 automatically** via a
`code_simplifier_gate` in `execute-phase.md` (added 2026-07-13 after Phases 142B, 143.1, and
144 all landed on `main` with this step silently skipped — GSD's own workflow never called it;
CLAUDE.md's SOP text only reached the loop when a human-driven session ran it manually). For
any work NOT driven through `/gsd-execute-phase`, still invoke `/simplify` manually before
`/review`.

**Commands:** `.venv/bin/pytest tests/unit/ -v` · `.venv/bin/ruff check . --fix` · `.venv/bin/black .` · `docs/reference/cheatsheet.md` for full reference.

## Architecture

**Layers (v3.0):** Feature Factory (replaces I1-I4) · I5-I7 archived · I8 AI (Ollama; effective model `nemotron-3-nano:4b` set by `OLLAMA_MODEL` in `.env` — the `settings.py` code default `gemma4:e4b` is NOT pulled locally, so a missing `.env` entry breaks all LLM calls). **I8 is target-state, not confirmed-running:** `BaseAIWorker`/`alpha_swarm`/`narrative_swarm` have had zero commits since the v3.0 rebuild started 2026-06-20, and both `indicagent-alpha-swarm`/`indicagent-narrative-compute` are `disabled`/`inactive` — dormant-pending-design, not archived like I1-I7. Check `systemctl status` + `git log` before citing this stack as live. Detail: `src/intelligence/CLAUDE.md`'s top banner.
**Pipeline (v2.x — ARCHIVED, no live consumer as of 2026-07-02):** `indicagent-intelligence-pipeline.service` is `failed`; `ExecStart` points at a deleted file. Do not restart this unit expecting it to work. Full architecture: `src/intelligence/CLAUDE.md`.
**Pipeline (v3.0):** `IBKR TWS → FeatureVectorPipeline (compute) → FeatureVectorWriter → feature_vectors → forward_return_writer → ic_engine → ensemble_trainer/EnsembleICEngine (alpha_ensemble_ic) → alpha_publisher → alpha_events`. `alpha_publisher` is the sole `alpha_events` writer.
**Typed Bus (v2.x — ARCHIVED, no live consumer as of 2026-07-02):** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` by `feature_writer`. `indicagent-feature-writer.service` is `inactive (dead)`.

**Service DAG:** canonical registry is `_DAG_ORDER` in `services/service_auditor.py`. Live state: `systemctl list-units --all | grep indicagent`. Monitoring: Grafana `:3001`.
**ML batch services** (`ml-training`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `roll-batch`): `inactive (dead)` between runs is correct.

## Core Runtime Files

- **DB queries:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`. Plain `psql -U postgres` fails.
- **Instrument asset class filter:** `instruments.contract_details->>'asset_class'` — values: `'equity'` (ETFs), `'futures'`, `'fx'`. No top-level column. Use `is_active = true AND contract_details->>'asset_class' = 'equity'` to target ETFs only.
- **`market_data_ohlcv` reads for compute/measurement:** use `market_data_ohlcv_tradeable` (a view, `WHERE volume > 0`), not the raw table — `market_data_ohlcv` is a continuous calendar grid containing synthetic-fill and IBKR flat-carry-forward placeholder bars (~82% of intraday rows). Raw-table access outside this needs a `tests/unit/test_market_data_ohlcv_boundary.py` allow-list entry with a reason; CI fails otherwise.
- **Historical backfill:** `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (default `--client-id 40`; provider uses 35; IDs must stay ≤ `_MAX_CLIENT_ID=50` in `ibkr.py`).
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `format_iso_ts()`, `parse_iso_ts()`
- `src/core/ai/` — AI agent infrastructure (`BaseAIWorker`, `Evaluator`, `AgentOutput`, `WorkerContext`, `IAIAgent`). `SignalContext` in `src/intelligence/ai/context.py`. `BaseGroupCoordinator` in `src/intelligence/ai/group_coordinator.py`.
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)
- **Narrative service (dormant, see Architecture note above):** `services/narrative_swarm.py` (`NarrativeSwarm`) → `indicagent-narrative-compute`. Worker: `NarrativeSynthesizer` in `src/intelligence/ai/narrative/narrative_agent.py`.

## Data Flow

```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: BarWriter + FeatureVectorWriter → TimescaleDB (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables

- `market_data_ohlcv` — raw OHLCV. Primary time column: `timestamp` (not `ts`). Timeframe column: `timeframe` (not `tf` — differs from `intelligence_features`).
- `intelligence_features` (v2.x — ARCHIVED, no live consumer as of 2026-07-02) — full feature vectors per bar. Column name: `ts` (not `feature_ts`)
- **Signal Ledger Architecture (SLA, Phase 128+) (v2.x — ARCHIVED, no live consumer as of 2026-07-02):**
  - `signal_events` — detection layer: one row per I7 plugin fire. Fields: `raw_confidence` (ICC), `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. Primary time: `ts`.
  - `trade_frames` — hypothesis layer: one row per entry_type per signal. Fields: `counterfactual_pnl_r` (CFL, always populated). ML trains on this.
  - `trade_executions` — execution layer: one row per live trade. Fields: `actual_pnl_r`, `actual_fill_price`, `exit_reason`.
  - `signal_ledger` — JOIN view (renamed from signal_ledger_full in Phase 130). Provides backward-compat query surface joining signal_events + trade_frames + trade_executions. Legacy monolith and signal_outcomes dropped in Phase 130.
- `llm_calls` — full LLM audit log; outcome back-filled by `llm_writer`
- `setup_performance` — per-setup rolling 30d stats; drives `perf_multiplier`; `sample_size >= 30` gate
- **Volume Profile**: `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h)

**Gotchas:** `docs/operations/operations-database.md` — `instruments.symbol` = base, contract code in `contract_details`.

## Adaptive Parameter Registry (APR)

All tunable numeric values live in `config_state` under `<domain>.<concept>.<param>` — accessed via `ConfigService.get(key, default=X)`. Hard-coded numeric thresholds, weights, periods, or counts in `src/` or `services/` are an architecture violation. Full spec: `docs/foundation/adaptive-parameter-registry.md`.

**Namespaces:** `threshold.*` · `weights.*` · `feature.*` · `regime.*` · `shadow.*` · `signal.*` · `swarm.*` · `roll.*` · `ui.*` (dashboard preferences) · `alpha.*` (v3.0 IC engine, ensemble, emission, Kelly, trade framing) · `infra.*` (batch sizes, queue depths, timeouts, audit intervals)

**Parameter lifecycle:** seed → user/operator preference → ml_learned → user_override. Every write recorded in `config_history` with `changed_by` and `reason`.

**Adding a parameter:** (1) INSERT into `config_schema` + `config_state` in a migration; (2) load via `ConfigService.get()` at init; (3) remove the hard-coded constant. Description must note provenance: `[initial_estimate]`, `[conventional]`, `[rca_analysis]`, or `[user_preference]`, and whether it is an ML learning target.

**APR mandate covers 4 categories beyond thresholds/weights/periods:**
1. **Seeds that affect algorithm output** → APR (e.g., `HMM_RANDOM_STATE = 42` → `alpha.hmm.random_state`; warn in description that changing invalidates downstream outputs).
2. **Behavioral lists** — lists controlling WHAT the algorithm processes → APR as JSON; load via `json.loads(cfg.get_sync(key, default_json))`.
3. **Infrastructure performance constants** — batch sizes, queue depths, timeouts → `infra.*`.
4. **Operator-visible switches** — any operator-facing toggle regardless of namespace.

**APR-exempt:** service identity (`_JOB`, log paths, unit names), schema identifiers (column/table names), statistical concept definitions (the `5` in `momentum_z_5`), derived/computed values, mathematical constants, DAG topology. Full exempt list: `docs/foundation/adaptive-parameter-registry.md`.

**Gradient column naming:** Use scale qualifiers (`fast`/`mid`/`slow`, `low`/`mid`/`high`, `primary`/`secondary`) instead of numbers for tunable calibration params. `return_fast` column + `alpha.ic.lookahead.fast = 1` APR key — update APR to change, no migration. Compare: `momentum_z_5` (5 defines the statistic, immutable) vs. `return_fast` (1 calibrates "fast," tunable). Full spec: `docs/foundation/naming-system.md §7`.

**Migrate-as-you-go:** Any numeric threshold, weight, period, or count encountered in `src/` or `services/` that is not APR-backed MUST be migrated in the same session. Module-level constants and inline magic numbers are architecture violations. Pattern for module-level utilities: `_config_service: Any | None = None` + `set_config_service()` + `get_sync()` wrapper, registered in `FeatureVectorPipeline._prewarm_threshold_config()` (`services/feature_vector_pipeline.py`). Pattern for plugin dataclasses: `_config_service: Any = field(default=None, compare=False, repr=False)`, read via `cfg.get_sync(key, fallback) if cfg else fallback`.

**Dashboard:** `/config/parameters` — view/edit all parameters, full change history per key.

## Plugin System (v2.x, archived 2026-07-02)

Entire I1-I7 tier has no live consumer. Full architecture, tier lists, shadow governance, AI agent authoring: `src/intelligence/CLAUDE.md`.

## DAG Invariants

Non-negotiable. Any violation is wrong regardless of whether it works locally.

1. **`ProviderMerger` is the sole writer to `market.bars`**
2. **Compute stages run in-process** — feature computation publishes to Kafka; Kafka is a sink, not an inter-stage pipe. Compute daemons (e.g. `FeatureVectorPipeline`) may hold a DB handle for their own reads (warmup history, ConfigService) and one-time schema bootstrap, but must never persist their own computed output rows.
3. **A compute daemon never writes its own computed output** — that persistence goes through a dedicated `BaseWriter`/`BaseBatch` subclass (e.g. `FeatureVectorWriter`), never inline in the compute daemon. (`BaseTracker`/`BaseAuditor` no longer exist as base classes — auditors like `BarAuditor` extend `BaseDaemon` directly.)
4. **All topic keys via `stream_keys.py`** — no hardcoded topic strings.
5. **No agent calls another agent directly** — topics are the only coupling.
6. **All timestamps UTC** — `datetime.now(UTC)` only; never `datetime.now()` or `datetime.utcnow()`.
7. **Scaling via systemd + Prometheus lag** — no Kubernetes HPA.

## Key Rules

**Core Patterns**
- **Executable returns only (Invariant 1)**: IC measurement MUST use `forward_returns.return_type = 'executable_open_to_open'`. The correct formula is `ln(open[T+N+1] / open[T+1])` — market-on-open entry, market-on-open exit. Theoretical `ln(close[T+N] / close[T])` captures overnight gaps that cannot be traded and overstates IC. All `forward_returns` queries in `ic_engine.py` must filter `WHERE return_type = 'executable_open_to_open'`.
- **Parallel dicts → dataclass**: 3+ `dict[str, X]` attributes keyed by same ID → consolidate into `dict[str, MyState]` with `_state(key)` factory. Pattern: `SignalTracker._signal_states`.
- **ProcessPoolExecutor workers are compute-only**: workers must return serializable results (rows, dicts) to the main process. All DB writes go through a single serial connection in main. Never open a write connection or call execute_batch/conn.commit() for writes from a worker subprocess — concurrent writers on the same TimescaleDB hypertable cause index-page deadlocks. (Fixed in regime_writer; pattern applies to all batch services: ic_engine, backfill_feature_factory, etc.)
- **Killing a ProcessPoolExecutor-based service's main process orphans its workers**: `kill <main_pid>` does not reap forkserver worker subprocesses — they survive, still holding DB connections/still writing. Always follow with `ps aux | grep <script.py> | awk '{print $2}' | xargs kill` and confirm zero remain before restarting.
- **Never log per-row inside a loop over the full corpus** (millions of rows on `--backfill`): a `logger.warning()` per occurrence floods the log file and adds real per-row overhead on a hot path. Accumulate a local counter and report once per partition/run instead — same shape whether the loop runs in-process or inside a `ProcessPoolExecutor` worker (worker accumulates and returns the count; main process sums and logs once). Pattern: `ic_engine.py`'s `n_skipped`. (Fixed in alpha_frame_writer.py/counterfactual_tracker.py, Phase 142B code review.)
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **`BaseGroupCoordinator` agent construction**: agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.
- **AI agents MUST use `self._llm_generate(context, ...)`** — never call `self._llm.generate()` directly.
- **`prompt_version` class attribute** on every `BaseAIWorker` subclass — set from agent's `ACTIVE_VERSION` constant.
- **`llm_calls` composite PK: `(call_id, called_at)`** — ON CONFLICT must use both columns.
- **Kafka is transport, not state store.** Hot state → local file checkpoint. Bar history → TimescaleDB.
- **Timestamp serialization**: use `format_iso_ts(dt)` from `service_utils.py`. Never inline `.isoformat().replace("+00:00", "Z")`.
- **`get_active_contracts()`** is a module-level function in `settings.py`. Call as `get_active_contracts(settings)`, not `settings.get_active_contracts()`.
- **asyncpg**: JSONB → `dict` (no `json.loads()`/`json.dumps()`), but ONLY on a pooled connection from `BaseBatch`'s `create_pool()`, which registers the codec. A bare `asyncpg.connect()` (e.g. a read-only reporting/evaluation branch) has no codec; jsonb columns come back as raw JSON text. Call `src.core.database_manager._setup_codecs(conn)` explicitly on any bare connection that reads jsonb. Timestamps → `datetime`. UUIDs → `str()` before Kafka.
- **structlog `event` kwarg collision**: Never pass `event=<value>` — use `signal=`, `payload=`, `data=` instead.
- **Service registry**: when adding a service, update `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py`; seed its lag threshold as an `alert.lag.*` APR key (loaded by `_load_lag_thresholds()`, hot-reloaded via Kafka) — do not hardcode it.
- **`INDICAGENT_ENV` consistency**: Mixed env prefixes → services subscribe to different topics → zero data flow.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: `src/observability/metrics.py` (direct OTel SDK — `prometheus_client` fully removed). Counters → `.add(1, attrs)`, histograms → `.record(val, attrs)`, up-down gauges → `.add(delta, attrs)`, point gauges → `.set(value, attrs)`. Never import `prometheus_client`.
- **Spans**: `observed_span(name, attributes={...})` from `src/observability/spans.py` — auto-records ERROR on raise. Use `ATTR_*` constants from same module.
- **`BaseWriter._parse_payload` return contract**: `None` → DLQ whole payload. `[]` → all-invalid (no DLQ). Only return `None` for truly unparseable payloads.
- **Exception variable name is `error`** — `except X as error:`, not `exc`.
- **File/class renames require test sweep:** `grep -r "OldName" tests/` — test imports break at pytest collection, not lint.
- **`BaseWriter.__init__` requires `name: str`** (non-optional): when removing `name=` from any writer, also update `BaseWriter.__init__` to accept `name: str | None = None`.
- **Oneshot `_agent.py` exceptions:** `services/feature_validation_agent.py`, `services/hmm_training_agent.py`, `services/ml_training_agent.py`, `services/ml_signal_training_agent.py` — `_agent` suffix intentionally preserved.
- **API health router prefix is `/health`** not `/api/health`. Routes: `/health/system`, `/health/database`, etc.
- **`agent_last_message_timestamp_seconds` label key is `agent_id`** — use `r["metric"].get("agent_id")` when querying from Prometheus.
- **Ollama JSON enforcement (nemotron-3-nano:4b):** system message MUST start with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Add `"Begin your response with { and end with }."` at end of user prompt.
- **Swarm raw signal confidence**: `calibrated_confidence` is null in Kafka payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

**Services**
- **Logging**: `structlog` → `logs/<snake_case_class_name>.log` via `setup_service_logging("logs/<name>.log")`. NOT journald.
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`** — not `agent=`.
- **`feature_vector_pipeline` subscribes to:** `topic_market_bars` (1m) AND `topic_market_bars_htf` (HTF).
- **Tests**: `tests/unit/`, `tests/integration/`. Unit tests must be CI-clean.

## OTel Health Contract

Every `BaseDaemon` subclass auto-inherits 5 mandatory OTel signals (D-26, non-negotiable): `agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total`. Four are labeled `agent_id`; `agent_crash_total` uses label key `agent` instead (`src/core/agent/base.py`'s `_crash_attrs`). No per-service code needed.
**Oneshot (D-06):** emit `job_completed_total{job, status}` at exit. `job` label matches systemd unit `%n` suffix exactly (kebab-case).

## Infrastructure

- **Server:** `192.168.68.53` — Claude Code runs ON this machine; never SSH.
- **IBKR Gateway:** Docker (`ib-gateway` container), bound to `127.0.0.1:7497`. All ib_insync in `src/providers/ibkr.py` only. VIX=`"VX"`, client IDs 35+.
- **Redpanda**: Kafka-compatible. Topics: dots, via `stream_keys.py`. Retention: minimal (transport, not storage).
- **Contracts**: always `get_active_contracts()` — never hardcode. Restart daemons on futures expiry.
- **Roll flow:** `roll-batch` (`scripts/ops/roll/ops_roll_batch.py`) — promotes front-month in `contract_metadata`, broadcasts via Kafka. Documented as nightly 8pm, but **all systemd timers are confirmed disabled as of 2026-07-02** — verify with `systemctl list-timers | grep indicagent` before assuming this runs on schedule.
- **Docker**: `cd production && docker compose up -d` after `docker-compose.yml` changes. All services have `logging: max-size/max-file` caps — do not remove them (TimescaleDB grew a 29GB log without them).
- **Ollama:** Docker (`ollama/ollama:rocm`). `docker exec ollama ollama <cmd>`. Kill `alpha_swarm` + `narrative_compute` before swapping models.

> Sudo, INDICAGENT_ENV debug, more: `docs/operations/operations-infrastructure.md`
