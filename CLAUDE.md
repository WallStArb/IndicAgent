# CLAUDE.md

Version: 5.59.0
<!-- Bump the patch version on every substantive edit to this file (convention, not enforced). -->

**Project nature:** Passion/learning project — not a production system. Architectural decisions prioritize correctness, rigor, and institutional-grade thinking. Renaissance Capital / Jim Simons principles are the north star. When giving advice, apply the same rigor you would to a system built to last — do not hedge around operational risk that doesn't apply.

**Principles:** Instrument everything · shadow mode first · data quality over model complexity · never drop data that could contain signal · earn capital through proof (count every look at the vintage, select with StepM, promote only with positive net expectation, confirm once on each book's own unsearched forward span; `docs/plans/2026-09-24-evidence-framework.md` and `docs/plans/2026-09-26-unified-research-to-production-design.md`, E15-E18) · segment by regime · automate manual tasks · empirical over theoretical · resist overfitting. Full doc: `docs/foundation/principles.md`.
**Design mindset:** Think as a council of senior engineers at Renaissance Technologies. Data integrity is paramount. Ruthlessly eliminate complexity. Silent wrong answers are worse than loud crashes. Deterministic DAG topology — every node does one thing, data flows one direction, no cycles. SoC: compute ≠ persistence ≠ transport. Async-first. Before committing to a design: (1) survives 10x volume? (2) what fails silently or introduces hidden bias? (3) does the DAG still hold? (4) what manual step does this eliminate?
**5-Step mandate (Musk):** Make requirements less dumb → delete → simplify → accelerate → automate. Run in order. Don't optimize what should be deleted. Don't accelerate in the wrong direction. Don't automate what isn't proven. Full doc: `docs/foundation/musk-5-step-process.md`.
**Naming:** Concept name (`snake_case`) derives all layer names: `signal_tracker` → `SignalTracker`, `indicagent-signal-tracker.service`, `topic_signal_tracker()`, `signal_trackers` table. **Ring rule:** `src/core/`, `src/observability/` = Ring 0 portable infrastructure (no domain vocab, no imports from `services/`); `src/intelligence/` = Ring 1 domain; `services/` = Ring 2 daemons. Topics: dots only, via `stream_keys.py`. Suffix taxonomy (`Tracker`/`Writer`/`Auditor`...), `Base*` prefix, `Agent` retired, and the eight surfaces (classes, files, topics, DB tables and columns, variables, routes, functions, constants): `docs/foundation/naming-system.md`.
**Glossary:** Every domain term has exactly one definition. Check before naming new concepts; glossary wins over existing code on collision. Full spec: `docs/foundation/glossary.md`. Retired terms (`AlphaEngine`, `ensemble alpha`, `alpha score`, `sleeve`, ...; unified design section 15) are banned in new code and docs; the pre-commit glossary check fails on new hits (todo 430).
**Doc locations:** `docs/foundation/` canonical home. `docs/` root is index only. `docs/research/` docs can go filename-stable (edited in place, no longer re-dated on rewrite) — check for a stale `YYYY-MM-DD-<name>.md` fork of an undated doc before citing or editing either.
**Before archiving anything in `docs/plans/`/`docs/research/`**: `grep -rl <filename>` first; stale-looking docs are usually still cross-referenced by live ones.
**Gotchas:** `docs/reference/gotchas.md` — rare pitfalls moved out of per-turn context.
**Performance investigations:** Before touching a batch job that mutates millions of rows against a TimescaleDB hypertable and runs far slower than expected, follow `docs/foundation/performance-investigation-sop.md`; measure (`pg_stat_activity.wait_event`, `iostat -x 1`, `EXPLAIN ANALYZE`) before theorizing, never trust a read-only test for a write-path question, and check chunk count/compression status as first-class suspects (todos 149, 161).
**Compressed-hypertable column type changes:** a migration doing decompress→`ALTER COLUMN TYPE`→recompress MUST end with a bare `VACUUM <table>;` (`compress_chunk()` does not reclaim the decompressed heap pages, and autovacuum misses internal chunk tables; migration 312's omission became a 768 GB disk-full incident). CI-enforced (`tests/unit/test_compressed_hypertable_migration_vacuum_check.py`). Template: `docs/foundation/timescaledb-compressed-column-migration.md`.
**Planning system:** `.planning/PLANNING-SYSTEM.md`: how IDEAS.md → docs/ideas/ → docs/plans/ → todos/pending/ → ROADMAP.md → phases/ flow into each other. Current phase/progress: `.planning/STATE.md`. Todo prioritization (single source of truth for `pending/`): `.planning/todos/PRIORITIES.md`; every pending todo needs a table row and every link must resolve (CI-enforced, `tests/unit/test_todo_priorities_link_integrity.py`).
**Adding a phase:** `gsd-sdk query phase.add` numbers from `.planning/phases/` directories, not ROADMAP.md; check `grep -n "### Phase" .planning/ROADMAP.md | tail` first and add by hand on a collision.
**Live phase-execution state:** ROADMAP.md plan checkboxes plus `NN-SUMMARY.md` presence in the phase dir are the granular truth; STATE.md phase entries lag (todo 383 sync bug) — check `git log --oneline` before citing a phase as not-yet-executed.
**Orchestrator executor subagents are in-process:** they die with their session; `/clear` keeps the process alive (the executor survives and its completion notification lands in the cleared session). Hand off via memory with a resume protocol; per-task atomic commits make any plan resumable.
**STATE.md Strategic Plan edits:** replace stale bullets with plain corrected facts; no stacked `CORRECTED <date>` blocks.

## Done-Coding SOP

Gate by diff class; the push is the only publishing boundary. Commit directly on main
(branch switching moves HEAD for every concurrent session in this shared checkout; the
branch dance is a hazard there, not isolation — when another session's WIP is dirty,
isolate with the detached-HEAD scratch worktree in `docs/reference/gotchas.md`).

```
1. Gate by diff class (decide up front):
   - docs/planning only: the test that consumes the files (e.g.
     test_todo_priorities_link_integrity.py for .planning/), then commit
   - small code change (single area, no schema or src/intelligence/research|statistics
     files): targeted tests for the touched area, then commit
   - substantive code: /simplify -> /review -> pytest tests/unit/ -q, then commit
     (+ scripts/research/determinism/repro_frozen.py bit-identical for
     src/intelligence/research/ or statistics/ edits)
2. Commit on main (pre-commit's 9 checks always run)
3. git push origin main; CI is the backstop
```

`/gsd-execute-phase` runs its own simplify gate (`code_simplifier_gate`); any other substantive work invokes `/simplify` before `/review`.

**Commands:** `.venv/bin/pytest tests/unit/ -v` · `.venv/bin/ruff check . --fix` · `.venv/bin/black .` · `docs/reference/cheatsheet.md` for full reference.

## Architecture

**Archived and dormant (no live consumer):** the v2.x I1-I7 pipeline and typed bus (`IntelligenceEvent`, `intelligence_features`; units `failed`/`inactive`, do not restart expecting them to work) and the I8 AI stack (`BaseAIWorker`, Ollama swarms, `disabled`). Check `systemctl status` + `git log` before citing any of it as live. Details, rules and the Ollama `.env` model gotcha: `src/intelligence/CLAUDE.md`.
**Pipeline (v3.5, adopted 2026-09-26; `docs/plans/2026-09-26-unified-research-to-production-design.md`, E18):** `ingest (IBKR -> market_data_ohlcv) -> feature (feature_vectors, market_regimes) -> measure (ic_engine: proposer, IC term structure, member monitoring) -> research (S0 panel -> S1 target -> S2 families -> S3 guards -> S7 combiner -> construction rule -> S8 book test; S6 ledger is the sole writer of research_run) -> frozen book -> forward runner (BookTracker/BookPositionWriter, sealed shadow) -> capital`. The old chain (`ensemble_trainer` -> `EnsembleICEngine` -> `alpha_publisher` -> `alpha_events`, plus `alpha_frame_writer`/`counterfactual_tracker`) still exists on disk until phase 186 deletes it; build nothing new on it.

**Service DAG:** canonical registry is `_DAG_ORDER` in `services/service_auditor.py`. Live state: `systemctl list-units --all | grep indicagent`. Monitoring: Grafana `:3001`.
**ML batch services** (`ml-training`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `roll-batch`): `inactive (dead)` between runs is correct.

## Core Runtime Files

- **DB queries:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`. Plain `psql -U postgres` fails.
- **Instrument asset class filter:** `instruments.contract_details->>'asset_class'` — values: `'equity'` (ETFs), `'futures'`, `'fx'`. No top-level column. Use `is_active = true AND contract_details->>'asset_class' = 'equity'` to target ETFs only.
- **Universe eligibility dimensions:** `instruments.compute_eligible` / `compute_eligible_1d` / `live_tradeable` (migration 337, Phase 174) — `is_active` alone conflates backfill/compute/live scope; `get_active_contracts(dimension=)` reads the split.
- **`market_data_ohlcv` reads for compute/measurement:** use `market_data_ohlcv_tradeable` (a view, `WHERE volume > 0`), not the raw table — `market_data_ohlcv` is a continuous calendar grid containing synthetic-fill and IBKR flat-carry-forward placeholder bars (~82% of intraday rows). Raw-table access outside this needs a `tests/unit/test_market_data_ohlcv_boundary.py` allow-list entry with a reason; CI fails otherwise. Deleting an allow-listed script requires removing its entry in the same commit (the stale-entry check fails CI).
- **Dividends (todo 428):** stored bars are price-only. `dividend_events` (Yahoo daily, owner-approved reference data; IBKR cross-check comes with phase 185 D5) is read through `dividend_events_reconciled`; outside `dividend_event_coverage` a name's dividends are unknown, never zero. Any research spec that holds across a session boundary declares `panel.total_return` (`src/intelligence/research/dividends.py`); intraday-only families don't need it.
- **Historical backfill:** `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (default `--client-id 40`; provider uses 35; IDs stay ≤ `_MAX_CLIENT_ID=50` in `ibkr.py`). Every IBKR history fetch takes the `ibkr_history_stream` lease (`src/core/resource_lease.py`, CI: `test_ibkr_history_lease_boundary.py`): one stream at a time, the nightly at priority tier, chains and manual runs at bulk tier; holders show in `pg_stat_activity` as `lease:ibkr_history_stream:<tier>:<holder>`. Wrapper scripts + symbol lists in `logs/backfill_ops/` are git-tracked (force-added; `logs/` otherwise ignored). Todo 449 campaign (through ~2026-10): lane watchdog logs are the progress monitor; never edit a lane script while its loop runs; loops exit after ~50 attempts (~2 min each), so after a gateway outage >~2 h relaunch `nohup bash logs/backfill_ops/intraday_chain.sh` (gap-aware; htf lane first, 5m follows).
- **IBKR history starts at a stock's last listing-venue move:** SMART-routed requests (1d and intraday) serve nothing before it (AMD 2015, PEP 2017, TLT 2016); the same contract routed to the old venue (`NYSE`, `ARCA`, `ISLAND`=Nasdaq, `AMEX`, `BATS`) serves it with venue-only volume. Error 162 "Query failed" marks it. `ohlcv_empty_history` rows written before todo 433's fix may be false. Todo 433, phase 185.
- **Onboarding instruments:** follow `docs/foundation/instrument-onboarding-sop.md` (source -> select -> classify -> manifest -> `universe_expansion_onboard_manifest.py` -> 1d backfill -> verify -> promote -> README). Never screen names on history or returns, never hand-write `instruments`, never deactivate a dead name (185 D8).
- **Running from a git worktree:** `Settings` reads the `.env` beside its own source tree, so symlink it (`ln -s /home/bg/dev/indicagent/.env <worktree>/.env`); worktrees have no `.venv`, so commit with `PATH=/home/bg/dev/indicagent/.venv/bin:$PATH` or the pre-commit hook blocks on missing ruff/black.
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `format_iso_ts()`, `parse_iso_ts()`
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_async logic (no imports outside this file)

## Data Flow

Streaming (dormant while the IBKR live feed is down): IBKR → Redpanda → services in memory; `BarWriter`/`FeatureVectorWriter` persist in batch. **The real-time path never touches the database directly.** Today's data arrives by nightly batch backfill.

### TimescaleDB Tables

- `market_data_ohlcv` — raw OHLCV. Primary time column: `timestamp` (not `ts`). Timeframe column: `timeframe` (not `tf` — differs from `intelligence_features`).
- Archived v2.x tables (`intelligence_features`, the Signal Ledger set, `llm_calls`, `setup_performance`, volume-profile columns): `src/intelligence/CLAUDE.md`.

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

## Instrument Tag Registry (ITR)

Claims about what an instrument is or how it behaves (sector, factor sensitivity, macro exposure) live in `tag_vocabulary`/`instrument_tags`, never hardcoded symbol lists. Human rows (`source='human'`) are never expired or overwritten by `TagCalibrator`; empirical rows expire only after `alpha.tag_calibrator.expiry_consecutive_fails` consecutive failures. Materiality (Phase 175) gates through `is_materiality_eligible()`, never `passes_materiality` alone. Spec: `docs/foundation/instrument-tag-registry.md`.


## Controlled Vocabulary Registry (CVR)

Valid codes per namespace (`regime_hmm`, `timeframe`, `asset_class`, ...) live in `controlled_vocabulary`, read via `VocabularyService` (cached at init, no hot-path DB calls). Definitional rows, never merged with ITR. `VocabularyDriftAuditor` flags live columns emitting unregistered codes. Spec: `docs/foundation/controlled-vocabulary-registry.md`.


## Security Classification Hierarchy (SCH)

Asset class > sector > industry group > industry, one current node per symbol, point in time and append-only (`classification_node`/`instrument_classification`, scheme `indicagent_v1`): reclassify = close `valid_to` + insert, same-UTC-day writes only (migrations 367/368). Read via `ClassificationService` or `current_level_name_sql()`. `Instrument.sector` is the level-2 node name; `contract_details->>'sector'` is historical only. Spec: `docs/foundation/security-classification-hierarchy.md`.


## Unified Concept Registry (UCR)

Lifecycle `candidate -> shadow_only -> active -> deprecated` for research artifacts in `concept_registry` (recipes, not their computed values). Only `ConceptRegistryService` flips an existing concept's status: no LLM or proposer override, ever. A migration adding a `FeatureVector` field may seed its row `active` directly. `feature_lifecycle` (chained after `ic_engine`) is the sole feature-domain writer, from the append-only `concept_evaluation` ledger. Spec: `docs/foundation/unified-concept-registry.md`.


## Plugin System (v2.x, archived 2026-07-02)

Entire I1-I7 tier has no live consumer. Full architecture, tier lists, shadow governance, AI agent authoring: `src/intelligence/CLAUDE.md`.

## Research Invariants (unified design section 12, E15-E18)

`temporal_integrity` (a read for t sees only facts knowable by t, by availability time) · `determinism` (bit-exact from snapshot hash + code key + spec hash) · `single_writer` (one writer per table, one direction) · `no_fill` (missing is NaN, warmup masked by declared memory, no placeholders reach compute) · `point_in_time` (universe, classification, tags, APR as of t) · `lineage` (every output traces to its recipe and run) · `asset_agnostic` (asset class is data, not a code branch) · `pure_compute` (pure functions over arrays, state at the edges).
**Data:** raw market data is permanent; derived data is cache (rebuildable, dropped only after its summary card is written); conclusions are records. **Evidence:** every backtest goes through the research runner and is counted; `alpha.validation.oos_start` is write-once; costs never enter a test statistic, but promotion needs positive net expectation.

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
- **Executable returns only (Invariant 1)**: IC measurement MUST use `forward_returns.return_type = 'executable_open_to_open'`. The correct formula is `ln(open[T+N+1] / open[T+1])` — market-on-open entry, market-on-open exit. Theoretical `ln(close[T+N] / close[T])` captures overnight gaps that cannot be traded and overstates IC. All `forward_returns` queries in `ic_engine.py` must filter `WHERE return_type = 'executable_open_to_open'`. The table is legacy (UD-25, design 14.7): `panel.forward_returns` is the one target definition, phase 186 drops the table, and new code computes targets with the kernel, never reads the table.
- **Parallel dicts → dataclass**: 3+ `dict[str, X]` attributes keyed by same ID → consolidate into `dict[str, MyState]` with `_state(key)` factory. Pattern: `SignalTracker._signal_states`.
- **ProcessPoolExecutor workers are compute-only**: workers must return serializable results (rows, dicts) to the main process. All DB writes go through a single serial connection in main. Never open a write connection or call execute_batch/conn.commit() for writes from a worker subprocess — concurrent writers on the same TimescaleDB hypertable cause index-page deadlocks. (applies to every batch service)
- **Killing a ProcessPoolExecutor-based service orphans its workers**: `kill <main_pid>` leaves forkserver workers holding DB connections and still writing. Follow with `ps -eo pid,cmd | awk '/<script.py>/ && !/awk/ {print $1}' | xargs kill` and confirm zero remain. Never `pkill -f`/`pgrep -f` a pattern that appears in your own command line (it kills the invoking shell, exit 144; bracket every occurrence, or use `ps | grep '[p]attern' | grep -v grep`). Then find a backend still running the killed query (`pg_stat_activity`, state `active`, wait `ClientWrite`) and `pg_terminate_backend()` it: it keeps its chunk locks and blocks the restarted run's writes.
- **Never edit a module ic_engine imports while a corpus run is live or resumable**: `code_content_key` hashes every first-party module ic_engine loads, so one edit discards every completed cell. Kill-and-resume with the same command is safe and skips cells whose fingerprints are already written; kill by PID and terminate any leftover ic_engine backend first (rule above).
- **Never log per-row inside a loop over the full corpus** (millions of rows on `--backfill`): a `logger.warning()` per occurrence floods the log file and adds real per-row overhead on a hot path. Accumulate a counter and log once per partition or run (a worker returns its count; main sums and logs). Pattern: `ic_engine.py`'s `n_skipped`.
- **Never materialize a wide (`SELECT tbl.*`) full-corpus DataFrame**: a 200+-column × millions-of-rows fetch costs a full-width copy on every later pandas op, so chunking or `del df` only moves the OOM to the next line (todo 234). Build the matrix directly from asyncpg rows (pattern: `scripts/research/feature_matrix.py`'s `fetch_feature_matrix`).
- **Dormant AI stack (`BaseAIWorker`, `BaseGroupCoordinator`, Ollama, `llm_calls`):** its invariants live in `src/intelligence/CLAUDE.md` ("Dormant AI stack rules"); read them before touching that code.
- **Kafka is transport, not state store.** Hot state → local file checkpoint. Bar history → TimescaleDB.
- **Timestamp serialization**: use `format_iso_ts(dt)` from `service_utils.py`. Never inline `.isoformat().replace("+00:00", "Z")`.
- **`get_active_contracts()`** is a module-level function in `settings.py`. Call as `get_active_contracts(settings)`, not `settings.get_active_contracts()`.
- **asyncpg**: JSONB → `dict` (no `json.loads()`/`json.dumps()`), but ONLY on a pooled connection from `BaseBatch`'s `create_pool()`, which registers the codec. A bare `asyncpg.connect()` (e.g. a read-only reporting/evaluation branch) has no codec; jsonb columns come back as raw JSON text. Call `src.core.database_manager._setup_codecs(conn)` explicitly on any bare connection that reads jsonb. Timestamps → `datetime`. UUIDs → `str()` before Kafka.
- **asyncpg dtype casting**: derive column types from `conn.prepare(sql).get_attributes()` (schema), never from inferring dtype off fetched row data — a column that's all-NULL in an early chunk (e.g. a late-backfilled feature) silently mistypes if inferred from data, and a downstream `dtype.kind in "fc"` filter then drops it from training with no error.
- **pandas 3 epoch-ns:** `DatetimeIndex.asi8` returns the index's own unit (microsecond default on pandas 3), not epoch-ns. Convert unit-explicitly: `pd.DatetimeIndex(values).to_numpy(dtype="datetime64[ns]").astype(np.int64)` (pattern: `scripts/research/feature_matrix.py::_epoch_ns`).
- **Service registry**: when adding a service, update `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py`; seed its lag threshold as an `alert.lag.*` APR key (loaded by `_load_lag_thresholds()`, hot-reloaded via Kafka) — do not hardcode it.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: `src/observability/metrics.py` (direct OTel SDK — `prometheus_client` fully removed). Counters → `.add(1, attrs)`, histograms → `.record(val, attrs)`, up-down gauges → `.add(delta, attrs)`, point gauges → `.set(value, attrs)`. Never import `prometheus_client`.
- **Spans**: `observed_span(name, attributes={...})` from `src/observability/spans.py` — auto-records ERROR on raise. Use `ATTR_*` constants from same module.
- **`bulk_update_by_key`'s `col_types` is load-bearing for correctness, not just DDL**: any column declared `"real"` gets float32-range-clamped before write (`services/_batch_utils.py::_clamp_to_real_range`) — a caller whose `col_types` still says `"double precision"` for a column a migration later narrowed to `real` silently loses that protection and can hit a Postgres "value out of range" write failure. Keep `col_types` in sync with the live schema, always.
- **Exception variable name is `error`** — `except X as error:`, not `exc`.
- **File/class renames require test sweep:** `grep -r "OldName" tests/` — test imports break at pytest collection, not lint.
- **`git add` with several pathspecs aborts entirely if any path doesn't match** (e.g. the pre-rename side of a moved todo file): none get staged. Stage a renamed path alone (`git add -- <new_path>`) before batching. After `git mv`, re-`git add` the new path: it carries the previously-staged blob, so earlier unstaged edits are otherwise left out of the commit.
- **Shared-checkout commits:** `git commit` itself carries an explicit pathspec (`git commit -m "..." -- <paths>`) — concurrent sessions share the index, so a bare commit sweeps their staged files (a bare commit has swept another session's file to origin). Never chain `git push` with a first-time commit: commit, verify `git show HEAD --stat`, push separately — the unpushed window (`reset --soft HEAD^`) is the only recovery.
- **A migration applied live via `psql -f` has no forcing function to get committed** — unlike code, its effect is already active in the DB even if the file never lands in git. Commit it in the same breath as applying it, not "later."
- **Research changes keep frozen verdicts bit-identical:** after any edit under `src/intelligence/research/` or `src/intelligence/statistics/`, run `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs` (from a worktree); it must report bit-identical.
- **New optional research-spec fields go in `spec.py`'s `_OPTIONAL_*_FIELDS`** (dropped from the canonical form when unset), or every recorded spec hash moves and the ledger's run records stop matching their specs.
- **Validating a test statistic:** check the H0 mean and sd of t and rejection counts against a binomial bound at each level, never one-sided p ranges alone (E16's bias hid behind p 0.28-0.77). Commit the pass criterion before the result exists.
- **Shift nulls have (sessions - L) / tau effective draws,** not one per shift: a persistent signal (tau 40-60) gets about 60-90 and cannot resolve p < 0.00167, however many shifts are run.
- **Ad hoc multiprocess scripts:** build the pool with `make_worker_pool(n, blas_threads_per_worker=1)` or export `OMP_NUM_THREADS=1`; a bare pool spawns 24 BLAS threads per numpy worker.

**Services**
- **Logging**: `structlog` → `logs/<snake_case_class_name>.log` via `setup_service_logging("logs/<name>.log")`. NOT journald.
- **Service logs rotate daily (~00:3x UTC)**: an empty/short current `.log` doesn't mean the process died — check `.log.1`/`.log.N.gz` for activity before today.
- **Tests**: `tests/unit/`, `tests/integration/`. Unit tests must be CI-clean.

## OTel Health Contract

Every `BaseDaemon` subclass auto-inherits 5 mandatory OTel signals (D-26, non-negotiable): `agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total`. Four are labeled `agent_id`; `agent_crash_total` uses label key `agent` instead (`src/core/agent/base.py`'s `_crash_attrs`). No per-service code needed.
**Oneshot (D-06):** emit `job_completed_total{job, status}` at exit. `job` label matches systemd unit `%n` suffix exactly (kebab-case).

## Infrastructure

- **Server:** `192.168.68.60` (DHCP; was `.53` before 2026-09-23). Claude Code runs ON this machine; never SSH. Runtime configs use `localhost`.
- **IBKR Gateway:** Docker (`ib-gateway` container), bound to `127.0.0.1:7497`. All ib_async in `src/providers/ibkr.py` only. VIX=`"VX"`, client IDs 35+.
- **Gateway 2FA hang:** login state lives in `docker logs ib-gateway` ("Second Factor Authentication" = waiting on human Keychain approval; "Login has completed" = authed). Re-send the push with `docker restart ib-gateway`; IBKR's server-side rate limit survives the restart (~5 min wait), then IBC's fresh login fires a new push. The nightly 23:59 UTC restart can re-trigger this (todo 395).
- **Redpanda**: Kafka-compatible. Topics: dots, via `stream_keys.py`. Retention: minimal (transport, not storage).
- **Contracts**: always `get_active_contracts()` — never hardcode. Restart daemons on futures expiry.
- **Timers:** check per unit with `systemctl list-timers | grep indicagent`; some fire (nightly backfill 01:00 EDT, regime coverage auditor 02:00 EDT), others are disabled (`indicagent-roll-batch.timer`: `scripts/ops/roll/ops_roll_batch.py` promotes the front month in `contract_metadata`).
- **Docker**: `cd production && docker compose up -d` after `docker-compose.yml` changes. All services have `logging: max-size/max-file` caps — do not remove them (TimescaleDB grew a 29GB log without them).

> Sudo, INDICAGENT_ENV debug, more: `docs/operations/operations-infrastructure.md`
