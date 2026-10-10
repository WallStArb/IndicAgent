# CLAUDE.md

Version: 5.62.0
<!-- Bump the patch version on every substantive edit to this file (convention, not enforced). -->

**Project nature:** Passion/learning project, not a production system. Decisions prioritize correctness, rigor, and institutional-grade thinking. Renaissance Capital / Jim Simons principles are the north star. Apply the rigor of a system built to last; do not hedge around operational risk that doesn't apply.

**Principles:** Instrument everything · shadow mode first · data quality over model complexity · never drop data that could contain signal · earn capital through proof (count every look at the vintage, select with StepM, promote only with positive net expectation, confirm once on each book's own unsearched forward span; `docs/plans/2026-09-24-evidence-framework.md` and `docs/plans/2026-09-26-unified-research-to-production-design.md`, E15-E18) · segment by regime · automate manual tasks · empirical over theoretical · resist overfitting. Full doc: `docs/foundation/principles.md`.
**Design mindset:** Think as a council of senior engineers at Renaissance Technologies. Data integrity is paramount. Ruthlessly eliminate complexity. Silent wrong answers are worse than loud crashes. Deterministic DAG topology: every node does one thing, data flows one direction, no cycles. SoC: compute ≠ persistence ≠ transport. Async-first. Before committing to a design: (1) survives 10x volume? (2) what fails silently or introduces hidden bias? (3) does the DAG still hold? (4) what manual step does this eliminate?
**5-Step mandate (Musk):** Make requirements less dumb → delete → simplify → accelerate → automate, in that order. Don't optimize what should be deleted, accelerate in the wrong direction, or automate what isn't proven. Full doc: `docs/foundation/musk-5-step-process.md`.
**Naming:** Concept name (`snake_case`) derives all layer names: `signal_tracker` → `SignalTracker`, `indicagent-signal-tracker.service`, `topic_signal_tracker()`, `signal_trackers` table. **Ring rule:** `src/core/`, `src/observability/` = Ring 0 portable infrastructure (no domain vocab, no imports from `services/`); `src/intelligence/` = Ring 1 domain; `services/` = Ring 2 daemons. Suffix taxonomy, `Base*` prefix, `Agent` retired, the eight surfaces: `docs/foundation/naming-system.md`.
**Glossary:** Every domain term has exactly one definition; check before naming anything new; glossary wins over code on collision (`docs/foundation/glossary.md`). Retired terms (`AlphaEngine`, `ensemble alpha`, `alpha score`, `sleeve`, ...; unified design section 15) are banned in new code and docs; the pre-commit glossary check fails on new hits.
**Docs:** `docs/foundation/` is canonical; `docs/` root is index only. Rare pitfalls and operational procedures (backfill, gateway, worker kill, git/shared-checkout, planning quirks): `docs/reference/gotchas.md`. Planning flow (IDEAS.md → docs/ideas/ → docs/plans/ → todos/pending/ → ROADMAP.md → phases/): `.planning/PLANNING-SYSTEM.md`; progress: `.planning/STATE.md`; todo priorities: `.planning/todos/PRIORITIES.md` (every pending todo needs a row, every link must resolve, CI-enforced).
**Compressed-hypertable column type changes:** a migration doing decompress→`ALTER COLUMN TYPE`→recompress MUST end with a bare `VACUUM <table>;` (migration 312's omission became a 768 GB disk-full incident). CI-enforced. Template: `docs/foundation/timescaledb-compressed-column-migration.md`.

## Done-Coding SOP

Gate by diff class; the push is the only publishing boundary. Commit directly on main (branch switching moves HEAD for every concurrent session in this shared checkout; when another session's WIP is dirty, use the detached-HEAD scratch worktree in `docs/reference/gotchas.md`). Always `git commit -m "..." -- <paths>`; never chain `git push` with a first-time commit.

```
1. Gate by diff class (decide up front):
   - docs/planning only: the test that consumes the files, then commit
   - small code change (single area, no schema or src/intelligence/research|statistics):
     targeted tests for the touched area, then commit
   - substantive code: /simplify -> /review -> pytest tests/unit/ -q, then commit
     (+ scripts/research/determinism/repro_frozen.py bit-identical for
     src/intelligence/research/ or statistics/ edits)
2. Commit on main (pre-commit's 9 checks always run)
3. git push origin main; CI is the backstop
```

`/gsd-execute-phase` runs its own simplify gate. **Commands:** `.venv/bin/pytest tests/unit/ -v` · `.venv/bin/ruff check . --fix` · `.venv/bin/black .` · `docs/reference/cheatsheet.md`.

## Architecture

**Removed (phase 185-45):** the v2.x I1-I7 signal path, typed bus and the I8 AI stack (ollama, langfuse, swarms). Archive: git tag `archive/v2x-ai-stack-2026-10` (local) and dumps in `data/backups/185-45/` until about 2026-11-06. A v2.x remainder (`pipeline/`, `plugins/`, `trading/`) stays only because `feature_vector_pipeline` imports it (todo 509); build nothing on it. Details: `src/intelligence/CLAUDE.md`.
**Pipeline (v3.5, adopted 2026-09-26; unified design, E18):** `ingest (IBKR -> market_data_ohlcv) -> feature (feature_vectors, market_regimes) -> measure (ic_measure: proposer, IC term structure, member monitoring) -> research (S0 panel -> S1 target -> S2 families -> S3 guards -> S7 combiner -> construction rule -> S8 book test; S6 ledger is the sole writer of research_run) -> frozen book -> forward runner (BookTracker/BookPositionWriter, sealed shadow) -> capital`. The old chain (`ensemble_trainer`, `EnsembleICEngine`, `alpha_publisher`, `alpha_events`, old ic_engine, `forward_return_writer`, `forward_returns`) was deleted in phase 186; build nothing on it.
**Service DAG:** registry is `_DAG_ORDER` in `services/service_auditor.py`; live state `systemctl list-units --all | grep indicagent`; Grafana `:3001`. ML batch services (`ml-training`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `roll-batch`) are `inactive (dead)` between runs, which is correct.
**Data flow:** streaming (IBKR → Redpanda → in-memory services; `BarWriter`/`FeatureVectorWriter` persist in batch) is dormant while the live feed is down; today's data arrives by nightly batch backfill. The real-time path never touches the database directly.

## Core Runtime

- **DB:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."` (plain `psql -U postgres` fails). `instruments.symbol` = base, contract code in `contract_details`; asset class is `contract_details->>'asset_class'`. Other DB gotchas: `docs/operations/operations-database.md`.
- **`market_data_ohlcv`:** time column `timestamp`, timeframe column `timeframe`. Compute and measurement read `market_data_ohlcv_tradeable` (view, `volume > 0`), never the raw table (synthetic-fill and carry-forward placeholder bars); raw access needs an allow-list entry in `tests/unit/test_market_data_ohlcv_boundary.py`.
- **Dividends:** bars are price-only; specs that hold across a session boundary declare `panel.total_return`; outside `dividend_event_coverage` dividends are unknown, never zero.
- **Contracts:** always `get_active_contracts(settings)` (module-level in `settings.py`), never hardcoded. Never `os.environ`; use `src/config/Settings`.
- **IBKR:** all ib_async in `src/providers/ibkr.py` only; Gateway is the `ib-gateway` container on `127.0.0.1:7497`. Every history fetch goes through `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (provider registry; external identities keep the ibkr name) under `FetcherLock`. Backfill, gateway 2FA and venue gotchas: `docs/reference/gotchas.md`.
- **Instrument onboarding:** `docs/foundation/instrument-onboarding-sop.md`. Never screen names on history or returns, never hand-write `instruments`, never deactivate a dead name.
- **Key modules:** `src/core/stream_keys.py` (all topic keys) · `src/core/database_manager.py` · `src/core/service_utils.py` (`setup_service_logging()`, `format_iso_ts()`, `parse_iso_ts()`, `min_bars_for_tf()`).
- **Server:** Claude Code runs ON this machine (`192.168.68.60`); never SSH; runtime configs use `localhost`. Docker: `cd production && docker compose up -d`; keep the log caps. More: `docs/operations/operations-infrastructure.md`.

## Adaptive Parameter Registry (APR)

All tunable numeric values live in `config_state` under `<domain>.<concept>.<param>`, read via `ConfigService.get(key, default=X)`. Hard-coded thresholds, weights, periods, or counts in `src/` or `services/` are an architecture violation. Spec: `docs/foundation/adaptive-parameter-registry.md`.

**Namespaces:** `threshold.*` · `weights.*` · `feature.*` · `regime.*` · `shadow.*` · `signal.*` · `roll.*` · `ui.*` · `alpha.*` · `infra.*`. **Lifecycle:** seed → user/operator preference → ml_learned → user_override; every write is recorded in `config_history` with `changed_by` and `reason`.

**Adding a parameter:** (1) INSERT into `config_schema` + `config_state` in a migration; (2) load via `ConfigService.get()` at init; (3) remove the hard-coded constant. The description notes provenance (`[initial_estimate]`, `[conventional]`, `[rca_analysis]`, `[user_preference]`) and whether it is an ML learning target.

**Also APR:** seeds that affect output (`alpha.hmm.random_state`; warn that changing it invalidates downstream outputs), behavioral lists (JSON via `json.loads(cfg.get_sync(key, default_json))`), infrastructure constants (`infra.*`), operator-visible switches. **Exempt:** service identity, schema identifiers, statistical concept definitions (the `5` in `momentum_z_5`), derived values, mathematical constants, DAG topology.

**Gradient naming:** tunable calibration params use scale qualifiers (`return_fast` + `alpha.ic.lookahead.fast = 1`), not numbers; change the APR key, no migration. Spec: `docs/foundation/naming-system.md §7`.

**Migrate-as-you-go:** any non-APR numeric threshold, weight, period, or count met in `src/` or `services/` is migrated in the same session. Module-level and plugin-dataclass patterns are in `docs/reference/gotchas.md`.

## Registries

- **ITR** (`tag_vocabulary`/`instrument_tags`): claims about what an instrument is or how it behaves live here, never in hardcoded symbol lists. Human rows are never expired or overwritten by `TagCalibrator`. Materiality gates through `is_materiality_eligible()`, never `passes_materiality` alone. `docs/foundation/instrument-tag-registry.md`.
- **CVR** (`controlled_vocabulary` via `VocabularyService`): valid codes per namespace, cached at init, never merged with ITR. `docs/foundation/controlled-vocabulary-registry.md`.
- **SCH** (`classification_node`/`instrument_classification`, scheme `indicagent_v1`): asset class > sector > industry group > industry, point in time and append-only; reclassify = close `valid_to` + insert, same-UTC-day writes only. Read via `ClassificationService` or `current_level_name_sql()`. `docs/foundation/security-classification-hierarchy.md`.
- **UCR** (`concept_registry`): `candidate -> shadow_only -> active -> deprecated`. Only `ConceptRegistryService` flips a status; no LLM or proposer override, ever. `feature_lifecycle` is the sole feature-domain writer. `docs/foundation/unified-concept-registry.md`.

## Research Invariants (unified design section 12, E15-E18)

`temporal_integrity` (a read for t sees only facts knowable by t, by availability time) · `determinism` (bit-exact from snapshot hash + code key + spec hash) · `single_writer` (one writer per table, one direction) · `no_fill` (missing is NaN, warmup masked by declared memory, no placeholders reach compute) · `point_in_time` (universe, classification, tags, APR as of t) · `lineage` (every output traces to its recipe and run) · `asset_agnostic` (asset class is data, not a code branch) · `pure_compute` (pure functions over arrays, state at the edges).
**Data:** raw market data is permanent, except for a name excluded under a written data-quality rule (`.planning/todos/pending/512-*`, owner 2026-10-08): its bar data and everything derived from it are deleted, and only its instrument metadata and a tombstone (is_active false, reason code, date, plan id, deleted row counts) remain; derived data is cache (rebuildable, dropped only after its summary card is written); conclusions are records. **Evidence:** every backtest goes through the research runner and is counted; `alpha.validation.oos_start` is write-once; costs never enter a test statistic, but promotion needs positive net expectation.
**Executable returns only:** IC targets come from the kernel `panel.forward_returns` (`src/intelligence/research/panel.py`), `ln(open[T+N+1] / open[T+1])`: market-on-open entry and exit. `ln(close[T+N] / close[T])` captures untradeable overnight gaps and overstates IC. Intraday horizons stay in-session. New code computes targets with the kernel and never reads a target table.
**Frozen verdicts:** after any edit under `src/intelligence/research/` or `src/intelligence/statistics/`, run `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs`; it must report bit-identical. New optional spec fields go in `spec.py`'s `_OPTIONAL_*_FIELDS` or every recorded spec hash moves.

## DAG Invariants

Non-negotiable. Any violation is wrong regardless of whether it works locally.

1. **`ProviderMerger` is the sole writer to `market.bars`**
2. **Compute stages run in-process**: feature computation publishes to Kafka; Kafka is a sink, not an inter-stage pipe. Compute daemons may hold a DB handle for their own reads (warmup history, ConfigService) and one-time schema bootstrap, but never persist their own output rows.
3. **A compute daemon never writes its own computed output**: persistence goes through a dedicated `BaseWriter`/`BaseBatch` subclass (e.g. `FeatureVectorWriter`). Auditors extend `BaseDaemon` directly.
4. **All topic keys via `stream_keys.py`**, no hardcoded topic strings.
5. **No agent calls another agent directly**: topics are the only coupling.
6. **All timestamps UTC**: `datetime.now(UTC)` only; never `datetime.now()` or `datetime.utcnow()`.
7. **Scaling via systemd + Prometheus lag**, no Kubernetes HPA.

## Key Rules

- **Kafka is transport, not state store.** Hot state → local file checkpoint; bar history → TimescaleDB.
- **ProcessPoolExecutor workers are compute-only:** return serializable results to main; all DB writes go through one serial connection in main (concurrent writers on a hypertable deadlock index pages). Killing such a service orphans workers; follow the kill procedure in `docs/reference/gotchas.md`.
- **Raw capture (528): every bar is stored under its supplier's label** (`source` on canonical rows; losers keep theirs in the raw archive). Nothing a vendor serves is dropped. Vendor onboarding: one `history_leaf` + one `VendorIngress` row + APR seeds.
- **Never edit a module a fingerprinted batch writer imports while its run is live or resumable** (`code_content_key` hashes it; one edit discards every completed cell). Kill-and-resume with the same command is safe.
- **Parallel dicts → dataclass:** 3+ `dict[str, X]` keyed by the same ID become `dict[str, MyState]` with a `_state(key)` factory.
- **Timestamps:** serialize with `format_iso_ts(dt)`, never inline `.isoformat().replace(...)`.
- **asyncpg:** JSONB is a `dict` only on a pooled `BaseBatch` connection; a bare `asyncpg.connect()` needs `_setup_codecs(conn)`. Derive dtypes from `conn.prepare(sql).get_attributes()`, never from fetched rows. Details: gotchas.
- **Service registry:** a new service updates `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py` and seeds its lag threshold as an `alert.lag.*` APR key.
- **Observability:** metrics via `src/observability/metrics.py` (OTel SDK; never `prometheus_client`); spans via `observed_span(...)`. Every `BaseDaemon` inherits 5 mandatory health signals; oneshots emit `job_completed_total{job, status}`.
- **Logging:** `structlog` → `logs/<snake_case_class_name>.log` via `setup_service_logging(...)`, not journald. Never log per-row in a full-corpus loop. Never materialize a wide `SELECT tbl.*` corpus DataFrame.
- **`bulk_update_by_key` `col_types`** must match the live schema (`"real"` columns are float32-clamped).
- **Style:** exception variable is `error` (`except X as error:`). Renames need a test sweep (`grep -r "OldName" tests/`). Tests live in `tests/unit/` (CI-clean) and `tests/integration/`.
- **Migrations applied live via `psql -f` are committed in the same breath.**
