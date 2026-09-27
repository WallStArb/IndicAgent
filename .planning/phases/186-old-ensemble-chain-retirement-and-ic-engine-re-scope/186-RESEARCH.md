# Phase 186: Old ensemble chain retirement and ic_engine re-scope - Research

**Researched:** 2026-09-26 (finished 2026-09-27)
**Domain:** Deletion and data retention in a TimescaleDB research system; IC measurement on one target kernel; bulk-load and provenance; feature kernel registry
**Confidence:** HIGH for inventory and table facts (measured read-only against repo and database); MEDIUM for wall-clock and disk estimates (derived from logs, stated with inputs)

## Summary

The deletion inventory is mostly clean but has five live couplings the design did not list.
(1) The research package imports `src/intelligence/portfolio/weighting.py`, which imports
`src/intelligence/ensemble/{covariance,shrinkage,weights}.py`, and `ensemble/__init__.py`
eagerly imports `alpha_score.py` and `feature_selector.py`. So `src/intelligence/ensemble/` cannot
go wholesale. (2) `scripts/infrastructure/universe_expansion_promote_compute_eligible.py`, a step
of the onboarding SOP, imports `scripts.analysis.instrument_compute_eligibility_audit`, and
migrations 337/341 cite its predicate SQL, so that script must be promoted before
`scripts/analysis/` goes. (3) `repro_frozen.py` imports `run.py`, which imports
`services.ic_engine._checkpoint_content_key`, and `refit.py`/`snapshot.py` import
`services.ensemble_trainer`, `services.ic_engine` and `services.cross_sectional_regime_model` at
module level, so it cannot be moved as-is. (4) The frozen phase 179 and 181 S3 pickles reference
the class path `scripts.analysis.sleeve_walk_forward.evaluate` (a re-export shim of
`EvaluationResult`); deleting that file makes the frozen artifacts unloadable, so the promoted
`repro_frozen` needs an `Unpickler.find_class` remap. (5) `services/feature_lifecycle.py` reads
`ensemble_weights` (not `alpha_ensemble_ic`), so the lifecycle shrink must land before that drop.

Three stated premises are wrong or stale and change the plan. `context_writer` does not touch
`context_features`: it writes `ctx_events`/`ctx_snapshots` from topic `ctx.snapshot`, which has no
publisher, and both tables hold 0 rows; the unit is running and doing nothing. `feature_registry`
was already dropped by migration 311 (2026-08-10, commit 54f346ba9), so D-31 shrinks to deleting
one dead verify script and stale comments. `alpha.hmm.walk_forward.enabled` has been `true` since
2026-08-12 (`config_history`, changed_by brandon), so the Aug 12 and Aug 15 corpus regime runs were
walk-forward; STATE.md and memory say todo 248 is "not deployed". Also, the phase 183 runner has
no exploration mode (`research_run.mode` CHECK allows only `'real'`) and S0 does not read
`feature_vectors`, so D-33's "todo 445 through the runner in exploration mode, can run now" is not
possible as written.

Parity (D-21) has no exact stored counterpart for the proposer's cell: every stored
cross-sectional row (`symbol = 'POOLED'`, 330,280 rows) is stratified by a `market_regimes` label
(31 labels) or by earnings season, and its IC is a pooled Spearman over (bar_ts, symbol) rows
subsampled at stride `max(5, lookahead)` over the flattened row order. Parity must replay those
cell masks with kernel targets in a test harness, not the production proposer. Also every stored
cell's last bars carry targets past `oos_start` (training_window_end = oos_start =
2025-12-24 05:15 UTC), so D-19's purge would empty the parity target: run parity first, then purge.

**Primary recommendation:** start now with summary cards, the ctx-writer retirement, the
bulk-load primitive and DB hygiene measurements (all autonomous), do all edits in a git worktree
(the research runner refuses real runs when loaded first-party files are dirty), and plan the
rebuild as a gated plan whose unit is (symbol chunk, tf, time range) with the HMM regime computed
as a registry kernel in the same pass, never as a post-hoc UPDATE.

<user_constraints>
## User constraints (from CONTEXT.md)

### Locked decisions
(Copied verbatim from 186-CONTEXT.md as of commit 9b6cc19d2.)

#### Preconditions and lane boundaries
- **D-01:** No edits to any module ic_engine imports while an ic_engine corpus run is live or resumable (CLAUDE.md). Checked 2026-09-26: no ic_engine, backfill or regime_writer process running; all old-chain units inactive. Each plan that edits an ic_engine import re-checks with `ps aux` first.
- **D-02:** `src/intelligence/research/` belongs to the phase 183 session until family 2's run finishes (STATE.md lane table). Phase 186 does not edit it. Where the design says "promote into the research package", phase 186 promotes into a module outside it (`scripts/research/` or a new `src/intelligence/tools/`-style module the planner picks), and research-package imports are switched by the research lane or in a plan explicitly gated on that lane's release.
- **D-03:** Research tests import `scripts.analysis.sleeve_walk_forward.config.HarnessConfig` (tests/unit/research/test_evaluate*.py, test_portfolio*.py). The sleeve directory cannot be deleted until those imports are moved; that move is a research-lane-owned change or waits for its release (D-02).

#### Summary cards before any drop (design 14.2, 10.2 item 3)
- **D-04:** Summary cards are written as checked-in structured files (one per card, YAML front matter plus prose) under `docs/research/summary-cards/`, with the 10.2 fields: idea, recipe pointer (spec or pre-registration path, git commit), result numbers, known defects, spans looked at, why closed or reopened, `reproducible: false`. Phase 187 loads them into its clean UCR schema as `kind = 'legacy_verdict'` attempts. Rationale: `research_run`'s only writer is the S6 ledger (research lane), and the clean UCR schema is phase 187; files keep 186 unblocked and git is the record.
- **D-05:** About 20-25 cards: the 18 verdicts in `docs/research/construction-verdict-ledger.md` plus the old ensemble chain (phase 148 gates, gate166, the `ctf_momentum` gates, phase 179). Numbers are read from existing tables and reports before the drop, never re-scored.
- **D-06:** A card set is checked (every table to be dropped has at least one card citing what was learned from it, and a card-lint test validates front matter) before any drop migration is applied.

#### Consumer checks (design 14.1)
- **D-07:** Before deleting: `services/context_writer.py` (unit `indicagent-ctx-writer.service`, the one active unit here) gets a consumer check of `context_features` readers; if no live reader, stop and disable the unit, then delete. `services/cross_sectional_spread_tracker.py` is deleted if phase 183's R1 covers its long-short primitives; otherwise record why it stays. Check whether `feature_lifecycle` reads `alpha_ensemble_ic` beyond the removed gates.
- **D-08:** Every deletion and drop starts with a repo-wide grep for the module/table name (src, services, scripts, tests, systemd units, Grafana dashboards, docs that operate it) and records the result in the plan summary.

#### Code deletions (design 14.1, 14.6)
- **D-09:** Delete `services/ensemble_trainer.py`, `services/ensemble_ic_engine.py`, `services/alpha_frame_writer.py`, `services/counterfactual_tracker.py`, `services/alpha_publisher.py` (its input and output tables go; `BookTracker`/`BookPositionWriter` are new builds in phase 188, not a dependency), their systemd units, `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` entries in `services/service_auditor.py`, their APR keys, and their tests.
- **D-10:** Delete old-chain ops scripts: `scripts/ops/alpha/ops_ensemble_*`, `ops_emission_threshold_sweep.py`, `ops_ensemble_ic_gate.py`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`; orchestrator steps after `ic_engine` and `feature_lifecycle` in `ops_pipeline_monitor.sh` and `ops_corpus_pipeline_run.sh`.
- **D-11:** `scripts/analysis/sleeve_walk_forward/`: first promote `repro_frozen.py` and what it imports (todo 448 item 1, the seed of the `determinism` tool) outside the directory with its test; list every file importing the directory; delete only after D-03 is satisfied.
- **D-12:** `scripts/analysis/` (71 scripts, 26.8k lines) is deleted after summary cards exist and reusable helpers (`_date_panel.py`, cost-band helpers, `_nonlinear_interaction_combiner_shared.py`'s `fetch_training_matrix` pattern) are promoted per D-02. Tests importing deleted scripts are deleted with them; tests of promoted helpers move with the helper. `scripts/research/` stays.
- **D-13:** Git history is the archive. No `archive/` copies.

#### Drops (design 14.2)
- **D-14:** Drop after cards: `ensemble_weights`, `ensemble_alpha`, `alpha_ensemble_ic`, `alpha_events`, `alpha_frames`, `context_features` (9.7 GB) and `feature_ic_scores_history` (38 GB). Each drop is a migration committed in the same commit as it is applied, after the consumer grep, never while another session's run reads the table.
- **D-15:** Keep forever: `market_data_ohlcv`, `dividend_events`, phase 185 raw observations, `.planning/gate_look_log.jsonl`. `feature_ic_scores` stays; old-grid rows (per-symbol x regime) are deleted with the ic_engine shrink, current pooled rows stay until the fresh engine writes rows on rebuilt features.
- **D-16:** Every operation on a compressed hypertable follows `docs/foundation/performance-investigation-sop.md`; any decompress/alter/recompress migration ends with a bare `VACUUM` (CI-enforced).

#### Fresh ic_engine (design 11, 14.6 item 2, 14.7)
- **D-17:** Written fresh as three small pure jobs over `src/intelligence/statistics/ic_math.py` plus one writer: proposer (pooled cross-sectional IC per feature x timeframe x horizon), IC term structure (same cells across horizons), monitoring (per-member IC over time for frozen-book members). The per-symbol x regime grid is gone; regime-stratified IC survives as disclosure for `regime_volatility` only. Strangler: new engine beside the old one, parity, then the old one is deleted.
- **D-18:** Targets come only from `panel.forward_returns` (the research kernel) on an S0 panel, computed in symbol chunks (exact because columns are independent). Intraday horizons stay inside one session; decay beyond a session is measured on the daily clock. The fresh engine reads the kernel through its public API and does not edit the research package (D-02).
- **D-19:** IC rows whose target window ends at or after `alpha.validation.oos_start` are never written (todo 439's purge); existing rows crossing it are purged.
- **D-20:** The uniqueness key includes scope explicitly (todo 391). Writes go through the new COPY primitive (D-24).
- **D-21:** Parity: fresh engine pooled cells vs stored `feature_ic_scores` pooled rows on the same features, timeframes, horizons and window. The only allowed differences are the gap rows (a name not trading on a bar; the table's "N traded bars" horizon vs the kernel's fixed horizon), disclosed with counts. No old-engine recompute is needed for parity.
- **D-22:** After parity, one change deletes: the old `services/ic_engine.py`, `services/forward_return_writer.py` and its unit, the `forward_returns` table (14 GB), the fixed `alpha.ic.lookahead.*` APR keys, and every script reading the table. The CLAUDE.md executable-returns rule is updated in the same change to point at the kernel.
- **D-23:** Revision detection uses a bar content digest per (symbol, tf, range) (design 3.3), replacing the `forward_returns.computed_at` watermark (absorbs todo 412). The code key is per kernel, not ic_engine's all-imports `code_content_key`.

#### Bulk-load primitive (14.6 item 3, 14.5)
- **D-24:** One primitive in `services/_batch_utils.py`: `COPY` in chunk (time) order, compress each chunk when complete, a provenance batch record (writer, per-kernel code key, APR snapshot, input content digest, symbol x tf x time range), and that record as the idempotency key (rerun with the same key is a no-op). No per-row provenance column on compressed hypertables. Every new writer in this phase uses it. Absorbs todos 301, 343, 352. Tunables are `infra.*` APR keys.

#### Kernel registry and feature_factory split (14.6 item 1)
- **D-25:** `src/intelligence/feature_factory.py` (8,733 lines) splits into one module per feature origin (price dynamics, volume and flow, SMC, VP/SR, calendar, macro, regime) behind one kernel registry: declared inputs, declared memory, dtype, pure `compute(inputs up to t)`. Parity is byte-identical float32 on a feature sample before vs after; behavior changes are separate commits.
- **D-26:** Declared memory in the registry is the one source for feature-member memory (todo 448 item 2); `book_memory()` itself is phase 187.
- **D-27:** One causality probe over the pure entry point (truncate inputs at availability time, recompute, compare in float32 exactly or within 1 ulp; cross-sectional features truncate every symbol), tested on fixture panels (todo 448 item 3). The nightly `temporal_integrity` audit table and job are not in this phase; the research S3 guard adopts the probe in the research lane.
- **D-28:** The batch feature path (`services/backfill_feature_factory.py`, `feature_vector_persistence.py`) becomes the single rebuild writer on D-25 and D-24; the dormant `feature_vector_pipeline.py` only imports the same registry. Fix todo 339 (unbounded worker rows across IPC) on this path.

#### regime_writer (14.6 item 5)
- **D-29:** Walk-forward is the only mode; the full-history path is deleted once todo 248's refit deploys. Todo 290 (memory and query) and 291 (duplication) fixed, bundled with 286, 292, 289, 341, 420. Lands before the rebuild consumes regime columns.

#### Feature lifecycle (design 11, 14.6 item 6, 14.3)
- **D-30:** `services/feature_lifecycle.py` shrinks to data-quality checks: a feature is computed, valid, and above the coverage floor. Weak standalone IC never stops a feature being computed. The IC-gate paths go.
- **D-31:** Phase 170 plans 07-08 are rewritten as finishing the `feature_registry` retirement without the ensemble rehearsal (the `alpha_ensemble_ic` gate never clears).

#### feature_vectors rebuild (14.2, 14.7) - gated plan
- **D-32:** Preconditions, checked by the plan before any work and refusing otherwise: bar backfill complete for the rebuild's names and timeframes (owner, 2026-09-26: the rebuild is multiday, so it runs once on full bar history, never on a partial backfill). The rebuild covers all 931 `compute_eligible_1d` names; 1d exists for all of them, but only 233 have intraday bars, so the 5m backfill of the other 698 (todo 449) must finish first; phase 185 D2b derived 15m and 1h grid landed and tested; todo 445 decision recorded; D-24, D-25, D-28, D-29 landed; todo 426's disk guard in place (space for about 4x the table at the chosen names against free disk). "Backfill complete" is a coverage query per (symbol, tf) against the expected history span, recorded in the plan, with any provider-empty spans (`ohlcv_empty_history`) listed, not assumed. "Complete" means what todo 449's backfill can fetch; phase 185 D3's venue-move recovery is not a precondition (185 D-19 stands: recovered history enters afterwards through content-digest keys and recomputes only affected ranges).
- **D-32a:** The rebuild is multiday, so it must be resumable. Work is split into (symbol chunk, tf, time range) units keyed by the D-24 provenance record, so a kill-and-resume skips completed units. Worker-orphan and leftover-backend cleanup follow the CLAUDE.md rules. No edits to modules the rebuild imports while it is live or resumable (the ic_engine import rule applied to the rebuild). Its DB load is measured against the other lanes (research runs, nightly backfill) before launch, and the plan states the expected wall-clock time from a measured pilot chunk.
- **D-33:** Timeframe set from todo 445: if 5m adds no incremental IC that survives costs, the rebuild covers 15m, 1h and 1d; raw 5m bars keep ingesting either way. Todo 445's test runs through the research runner in exploration mode (so it is counted) and can run now; phase 186 owns getting it run and recorded.
- **D-34:** New table written append-only in time order, each chunk compressed when complete, provenance from the first row, cleaner schema (drop never-computed columns such as todo 421's rank_z features and exact duplicates such as todo 115). Sampled drift report against the old table, then swap names, then drop the old table. Replaces todos 411 and 426 step 2. The HMM columns enter only after todo 248's refit.
- **D-35:** After the rebuild, the fresh ic_engine runs on the rebuilt features and replaces the current pooled `feature_ic_scores` rows.

#### Database hygiene (14.5)
- **D-36:** Drop the duplicate non-PK index on `market_regimes` (same key as the PK, about 387-400 MB) and the duplicate on `construction_spreads`.
- **D-37:** Every surviving table gets a primary key; tables without one are dropped in the dead-table sweep (with consumer grep) or given one.
- **D-38:** `shared_buffers` (3 GB on a 29 GB host) and `work_mem` (8 MB) are measured under the performance-investigation SOP, then tuned (about 25% of RAM for `shared_buffers`; `work_mem` per batch session). The Postgres restart for `shared_buffers` happens only with no batch job running and is recorded with before/after measurements.

### Claude's discretion
- Plan and wave split, module names for promoted helpers (within D-02), card file schema details, the fresh engine's module layout, and the exact parity sample sizes (state them before running).

### Deferred ideas (out of scope)
- DAG manifest, per-writer database roles, `_DAG_ORDER` deletion, `service_auditor` reading the manifest, UCR clean schema and loading summary cards, `book_memory()`, research package refactor (item 8), StepM through the E17 battery (todo 448 item 4): phase 187.
- Nightly `temporal_integrity`, `no_fill`, `point_in_time` audit jobs (track B beyond the probe).
- `BookTracker`/`BookPositionWriter`, forward runner: phase 188.
- Todo 435 S0 wiring and the first feature family: after the rebuild, outside this phase.
- Todo 390 before `illiq` enters any family (not a phase 186 deliverable).
- A stored target cache: only if a profile of the new proposer shows recomputation dominates (14.7 item 5).
- Todo 443 (exporter scrape, idle-in-transaction timeout): quick lane.
</user_constraints>

<phase_requirements>
## Phase requirements

No REQ IDs are assigned (ROADMAP: "Requirements: TBD"). Traceability keys are D-01..D-38 plus
D-32a. The table maps each decision group to the findings below that enable it.

| Key | Research support |
|---|---|
| D-01, D-32a | Process check, import graph of `_checkpoint_content_key` (imports `backfill_feature_factory`, `regime_writer`); runner provenance refusal (pitfall 1) |
| D-02, D-03, D-11, D-12 | Import inventory of `scripts.analysis` (section "Deletion inventory"), repro_frozen dependency graph, pickle class-path finding |
| D-04..D-06 | Card sources table, front-matter schema, table-to-card coverage map |
| D-07 | ctx pipeline facts, spread tracker vs R1, feature_lifecycle reads `ensemble_weights` |
| D-08..D-10, D-14 | Module, script, table reader lists; unit-file facts |
| D-15, D-19..D-23 | `feature_ic_scores` row classes, stored-cell anatomy, kernel API, parity design |
| D-24 | `_batch_utils` primitives, TimescaleDB direct-compress constraint |
| D-25..D-28 | `feature_factory` anatomy, existing parity tests, batch path structure, todo 339 |
| D-29 | regime_writer paths, walk-forward flag history, UPDATE-into-feature_vectors blocked by the 426 guard |
| D-30, D-31 | feature_lifecycle reads, migration 311 already dropped `feature_registry` |
| D-32..D-35 | Coverage per tf, 5m backfill estimate, rebuild rows/disk/time, resumability, todo 445 runner gap |
| D-36..D-38 | Index definitions, 11 no-PK tables, PG settings and drift, temp-file spill evidence |
</phase_requirements>

## Project constraints (from CLAUDE.md)

- No edits to modules ic_engine imports while a corpus run is live or resumable; kill by PID, reap forkserver workers, `pg_terminate_backend` leftovers.
- `market_data_ohlcv` reads for compute go through `market_data_ohlcv_tradeable`; raw access needs an allow-list entry in `tests/unit/test_market_data_ohlcv_boundary.py`.
- Compressed-hypertable decompress/alter/recompress migrations end with bare `VACUUM` (CI: `test_compressed_hypertable_migration_vacuum_check.py`).
- A migration applied with `psql -f` is committed in the same breath.
- APR mandate: no hard-coded numeric thresholds, batch sizes, timeouts in `src/`/`services/`; new tunables are `infra.*`/`alpha.*` keys via migration (config_schema + config_state + config_history) with provenance tags.
- ProcessPoolExecutor workers are compute-only; one serial writer per table.
- Never materialize wide `SELECT *` full-corpus frames; derive dtypes from `conn.prepare(sql).get_attributes()`.
- Exceptions named `error`; UTC only (`datetime.now(UTC)`); topics via `stream_keys.py`; structlog never `event=`.
- Service registry: `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`; lag thresholds as `alert.lag.*` APR keys.
- File/class renames need `grep -r OldName tests/` sweeps; `git add` with a missing pathspec aborts the whole add.
- `.planning/todos/PRIORITIES.md` link integrity is CI-enforced (`test_todo_priorities_link_integrity.py`): every todo moved/closed updates its row.
- Done-coding SOP: `/simplify`, `/review`, `pytest tests/unit/ -q` green, feature branch, ff-merge to main, push.
- Worktrees: symlink `.env`, commit with `PATH=/home/bg/dev/indicagent/.venv/bin:$PATH`.
- Global: no AI attribution in commits, no em dashes, sentence-case headings.

## Architectural responsibility map

| Capability | Primary tier | Secondary tier | Rationale |
|---|---|---|---|
| Summary cards | Docs (git) | Test (card lint) | D-04: files, loaded by phase 187 |
| Old-chain deletion | Ring 2 services, scripts | Database (drops) | Services and tables die together, cards first |
| Fresh IC jobs (proposer, term structure, monitoring) | Ring 1 pure compute (`src/intelligence/...`) | Ring 2 writer service | Pure kernels, single writer (DAG invariant 3) |
| Targets | Research kernel `panel.forward_returns` (read-only import) | S0 `snapshot.build_panel` | UD-25, D-18 |
| Bulk load + provenance | Ring 2 shared utility (`services/_batch_utils.py`) | Database (provenance table) | D-24; Ring 0 must not hold domain vocabulary |
| Feature kernels | Ring 1 (`src/intelligence/features/`) | Ring 2 batch writer | D-25, D-28 |
| HMM regime labels | Ring 1 kernel (regime origin) | Ring 2 rebuild writer | Pure function of bars (reads only `market_data_ohlcv_tradeable`) |
| DB hygiene | Database | Docker compose config | D-36..D-38 |

## Environment availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| PostgreSQL | everything | yes | 18.4 (musl, container `timescaledb`) | none |
| TimescaleDB | compressed hypertables, direct-compress COPY | yes | 2.27.1 | none |
| pg_stat_statements | D-38 measurement | yes | installed | none |
| pg_buffercache | D-38 buffer measurement | no | - | `pg_stat_database`/`pg_statio_*`, or `CREATE EXTENSION pg_buffercache` in a migration |
| Python / venv | all code | yes | 3.14.4 | - |
| psycopg / asyncpg | COPY primitive | yes | 3.3.4 / 0.31.0 (both support COPY; asyncpg `copy_records_to_table`) | - |
| numpy / pandas / numba / scipy | kernels | yes | 2.4.2 / 3.0.1 / 0.67.0 / 1.17.1 | - |
| pyarrow, polars | optional staging | yes (requirements.txt) | >=14, >=1.0 | - |
| pytest | validation | yes | 9.0.3; 6,755 unit tests collected | - |
| Docker | Postgres restart (D-38) | yes | running | - |
| IBKR gateway | todo 449 5m backfill | yes (container `ib-gateway`) | - | - |
| Disk | rebuild, drops | 496 GB free of 914 GB (44% used); DB 176 GB | - | drops first |
| RAM | Postgres tuning | 29 GB host; Postgres container 3.8 GB; a second Postgres (`ssfi-timescaledb`) on the host | - | - |

No new external packages are needed. The package legitimacy gate does not apply (no installs).

**Running processes at research time (2026-09-26 23:06 UTC start):** four
`infrastructure_run_historical_pipeline.py` lanes, client ids 40-43, `--dimension backfill
--timeframes 1h,15m` over the 698 names without intraday history (logs
`logs/backfill_new_universe_intraday_20260926T2306_lane{0..3}.log`). These fetch 15m and 1h, not
5m; under 185 D2b stored 15m/1h are raw observations only, and todo 449 says only 5m is needed.
Flag to the coordinator. No ic_engine, regime_writer or backfill_feature_factory process was
running. `indicagent-ctx-writer` is the only active unit in scope.

## Deletion inventory (D-08, D-09, D-10, D-12)

### Old-chain services

| Module (lines) | Unit file | Real importers outside itself | Notes |
|---|---|---|---|
| `services/ensemble_trainer.py` (1,101) | `production/systemd/indicagent-ensemble-trainer.service` (not installed in /etc/systemd) | `scripts/analysis/sleeve_walk_forward/refit.py:38`, `v4b.py:29`, `scripts/analysis/regime_boundary_churn_check.py:506` (lazy); 9 unit test files | mentions only in src (comments) |
| `services/ensemble_ic_engine.py` (1,530) | none | `scripts/ops/alpha/ops_ensemble_ablation.py:85`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py:63`, `scripts/analysis/diagnose166_frame_calibration.py:83`; 12 unit test files | `ic_math.py` docstrings reference it |
| `services/alpha_frame_writer.py` (784) | none | `services/counterfactual_tracker.py:69`; 3 tests | |
| `services/counterfactual_tracker.py` (947) | none | none outside tests (2) | `gate_math.py` extracted from it |
| `services/alpha_publisher.py` (553) | `production/systemd/indicagent-alpha-publisher.service` (not installed) | none; 2 tests | `stream_keys.py:164` topic docstring; metrics in `src/observability/metrics.py:1221+` |
| `services/alpha_scorer.py` (359) | none | test only | NOT in D-09 but reads `alpha_frames`, writes `alpha_strategy_scores` (120 rows); dead with the chain. Delete with D-09 |
| `services/generate_ic_discovery_report.py` | none | none | reads `ensemble_weights`/`alpha_events`; dead with the chain |
| `services/context_writer.py` (413) | `indicagent-ctx-writer.service` installed, enabled, running | `service_auditor.py:80,167`; `tests/unit/services/test_context_writer.py` | see D-07 below |
| `services/cross_sectional_spread_tracker.py` (1,942) | none | `scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py:71`; tests `test_cross_sectional_spread_tracker.py`, `test_compute_universe_readers.py`, integration tests | see D-07 below |

Only two of the old-chain units exist as files, and neither is installed: `systemctl
list-unit-files` shows no ensemble, alpha-publisher, forward-return-writer, ic-engine or
feature-lifecycle unit. The others are orchestrator-invoked scripts. `service_auditor.py`
`_DAG_ORDER` lines 108-116 and 208-214, `_AGENT_ID_TO_UNIT` line 167 carry the entries.

### Shared helpers that are NOT dead

| Helper | Why it survives | Action |
|---|---|---|
| `src/intelligence/ensemble/{covariance,shrinkage,weights}.py` | `src/intelligence/portfolio/weighting.py:24-26` imports them; `src/intelligence/research/portfolio.py:46` imports `weighting` | Keep. Delete `alpha_score.py`, `feature_selector.py`, `stratum_fit.py` only after rewriting `ensemble/__init__.py` (it eagerly imports `alpha_score` and `feature_selector`; deleting them breaks every `import src.intelligence.ensemble.covariance`, which runs `__init__`). Tests `test_ensemble_math.py` split accordingly; `test_ensemble_mean_variance.py`, `test_ensemble_shrinkage.py`, `test_portfolio_weighting.py` stay. `stratum_fit` importers are all dead (ensemble_trainer, sleeve refit/v4b, `_nonlinear_interaction_combiner_shared`) |
| `src/intelligence/statistics/gate_math.py` | Importers: alpha_scorer, counterfactual_tracker, spread tracker, 5 scripts/analysis files, tests | Dead once those go: delete with its tests (`test_gate_math.py`, `test_frame_gate.py`) |
| `src/intelligence/statistics/ic_math.py`, `hac.py`, `correlation.py`, `panel_null.py` | Research package and fresh engine | Keep; only docstrings mention dead modules |
| `services/cross_sectional_regime_model.py` | Writes `market_regimes`; imported by `ic_engine`, sleeve `snapshot.py` | Keep (writer of a kept table) |
| `src/observability/corpus_manifest.py`, `corpus_manifest_verifier.py` | `base_batch.py` uses the manifest for every BaseBatch | Keep; remove the dead step names (verifier lines 389-404) |
| `scripts/ops/alpha/ops_ic_shrinkage.py` (orchestrator step 6) | Only consumers are ensemble_trainer and sleeve refit | Not listed in D-10 but dead after the chain: delete with step 6 |
| `scripts/analysis/instrument_compute_eligibility_audit.py` (288) | Imported by `scripts/infrastructure/universe_expansion_promote_compute_eligible.py:34` (onboarding SOP stage 8); predicate SQL cited by migrations 337, 341; tests `tests/unit/scripts/test_compute_ready_predicate_apr.py` | Promote to `scripts/infrastructure/` before D-12 |
| `scripts/analysis/_date_panel.py` (220), `_nonlinear_interaction_combiner_shared.py` (1,642; `fetch_training_matrix`), `personal_cost_hurdle.py`, `personal_cost_hurdle_by_tf.py` (cost bands) | Named in D-12 | Promote per D-02 to `scripts/research/` (outside the research package); `_nonlinear...` imports `stratum_fit` and ensemble modules, so promote only `fetch_training_matrix` |

### scripts.analysis importers outside the directory (real imports)

- `scripts/infrastructure/universe_expansion_promote_compute_eligible.py:34` (live, see above).
- `tests/live/test_sleeve_walk_forward_snapshot.py:13`.
- tests/unit, 30 files (listed by `grep -rlE "(from|import) +scripts\.analysis" tests/unit`), including research-lane-owned `tests/unit/research/test_evaluate.py`, `test_evaluate_session_scoring.py`, `test_evaluate_intraday.py`, `test_portfolio.py`, `test_portfolio_r1.py` (all `HarnessConfig`, D-03), and helper tests to move: `test_date_panel.py`, `test_nonlinear_interaction_combiner_shared.py`, `tests/unit/scripts/test_compute_ready_predicate_apr.py`.
- src/services: comments only (15 files, e.g. `research/portfolio.py:8`, `statistics/hac.py:6`, `ic_math.py:110`). Not imports.

Measured: `scripts/analysis/` holds 95 .py files (26,819 lines) including subdirs
`sleeve_walk_forward/` (2,159 lines) and `e16_null_size/`. Tests in files that import dead
modules or `scripts.analysis`: 62 files, 801 tests of the 6,755.

### repro_frozen dependency graph (D-11, todo 448 item 1)

`repro_frozen.py` imports `run`, `config.DEFAULT_CONFIG`, `signals.SIGNALS`,
`services._batch_utils.make_worker_pool`, `src.intelligence.research.evaluate`. `run.py` imports
`refit` (-> `services.ensemble_trainer`, `services.ic_engine`, `scripts.ops.alpha.ops_ic_shrinkage`,
`src.intelligence.ensemble.stratum_fit`), `snapshot` (-> `services.ic_engine`,
`services.cross_sectional_regime_model`), `synthetic`, `verdict`, and
`services.ic_engine._checkpoint_content_key` (for `_code_key`). The phase 181 check calls
`run.main(["--stage","s2sig", ...])`, which uses only `verify_snapshot`, `load_snapshot`,
`daily_panel`, `forward_returns`, `SIGNALS`, `refit_dates`, and `_save`'s code key.

**Pickle finding.** `logs/phase179/rerun_e14/s3_4dead18ade3bde16.pkl` and
`logs/phase181/s3_d3c9294661215c6d.pkl` embed the class path
`scripts.analysis.sleeve_walk_forward.evaluate` (the 4-line shim re-exporting
`EvaluationResult`). S2 pickles embed no first-party class paths. Deleting the shim makes the
frozen S3 artifacts unloadable. The promoted tool must unpickle with a `pickle.Unpickler`
subclass whose `find_class` maps `scripts.analysis.sleeve_walk_forward.evaluate` to
`src.intelligence.research.evaluate`, and the promoted test must exercise that mapping on a
fixture pickle.

**Promotion shape (recommended):** `scripts/research/determinism/` (outside the research
package, allowed by D-02): `config.py` (HarnessConfig, byte-identical), `results.py`
(`Snapshot`), `sessions.py` (`refit_dates`), `signals.py`, `snapshot_io.py` (only
`verify_snapshot`/`load_snapshot`, no DB or ic_engine imports), `repro_frozen.py` with an inline
s2sig stage (payload comparison ignores the code key, so `_code_key` is not needed) and the
remapping unpickler. Artifacts live in `logs/phase179`, `logs/phase181` (local, not in git; present).
Then the research lane switches its five tests' `HarnessConfig` import (D-03), after which the
sleeve directory can go.

## D-07 consumer checks

**context_writer.** Writes `ctx_events` (hypertable, no PK) and `ctx_snapshots` from topic
`topic_ctx_snapshot` (`stream_keys.py:432`). No publisher of that topic exists anywhere in
src/services/scripts. `ctx_events` 0 rows, `ctx_snapshots` 0 rows. Readers:
`src/persistence/repository/feature_repository.py:42` (v2.x repository) and
`scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py`. The unit does no work:
stop, disable, delete module, test, service_auditor entries, unit file in `production/systemd`
and `/etc/systemd/system` (needs sudo), and drop both ctx tables (no card needed beyond a note:
never held data).

**context_features** is a different table: 8,985 rows, 3 features (`flight_quality`,
`yield_slope_z`, `vix_z`), last `feature_date` 2026-06-23, 1.6 MB (not 9.7 GB; 9.7 GB is the sum
of the six chain tables). Only writer: `scripts/infrastructure/backfill/infrastructure_context_features_writer.py`
(todo 355); no reader (the `context_features` hits in `signal_*` code are a JSONB column of the
v2.x `signal_events` table). Delete the writer script with the drop; close todo 355.

**cross_sectional_spread_tracker vs R1.** The tracker is flat equal-weight decile long-short on
`ctf_momentum` with its own gates (`evaluate_spread_gate`, `shuffled_ranking_null_p`,
`attribution_verdict`). Phase 183's R1 (`research/portfolio.py` `rank_vol_neutral_weights`,
`rank_vol_neutral_returns`) is rank-weighted and vol-scaled, and S3/S8 replace the gates. R1 does
not reproduce the decile rule literally, but it covers the long-short construction role, and a
decile rule is expressible as a new `ConstructionRule` if ever wanted. Recommendation: delete,
with the `ctf_momentum` gates card recording the decile spec (decile 0.1, cost tiers 1/3/5/10 bps,
null shuffles) from `.planning/gate_look_log.jsonl`. `construction_spreads` (133 MB, 130,625 rows,
one construction, 1,047 chunks) then has no writer: drop the table with that card instead of only
its duplicate index.

**feature_lifecycle.** Does not read `alpha_ensemble_ic`. It LEFT JOINs `ensemble_weights`
(`_CELLS_SQL`, lines 436-457) for `standing_weight`, reads `feature_ic_scores` POOLED cells,
`concept_registry`, `concept_gate`, `concept_transition_log`, writes `concept_evaluation`, and
reads APR keys `alpha.ensemble.weight_version`, `alpha.ensemble.sign_symmetric`,
`alpha.ensemble.meta_fdr_min_fraction`, `alpha.decay.*`. Order: the D-30 shrink lands before the
`ensemble_weights` drop.

## Tables (D-14, D-15, D-36, D-37)

| Table | Size | Hypertable / compressed chunks | PK | Rows |
|---|---|---|---|---|
| `alpha_events` | 5,617 MB | yes, 80/81 | (event_id, bar_ts) | ~65.6M |
| `ensemble_alpha` | 3,367 MB | yes, 80/81 | (symbol, tf, bar_ts, weight_version) | ~106.7M |
| `ensemble_weights` | 224 kB | no | (symbol, tf, regime, weight_version, feature_name) | 358, one version `run_2025122405150000` |
| `alpha_ensemble_ic` | 32 kB | yes, 0 chunks | (event_row_id, scored_at) | 0 |
| `alpha_frames` | 56 kB | yes, 0 chunks | (frame_id, bar_ts) | 0 |
| `alpha_strategy_scores` | 64 kB | no | yes | 120 |
| `context_features` | 1.6 MB | no | yes | 8,985 |
| `feature_ic_scores_history` | 38 GB | yes, 0/2 compressed | none | ~49.3M |
| `feature_ic_scores` | 698 MB | yes, 2/2 | (feature_name, symbol, tf, regime, lookahead_bars, training_window_end) | 10.6M |
| `forward_returns` | 14 GB | yes, 84/85 | (symbol, tf, bar_ts) | ~103.9M |
| `feature_vectors` | 89 GB | yes, 83/86, 90-day chunks, segmentby symbol,tf, orderby bar_ts | (symbol, tf, bar_ts) | ~108.6M |
| `market_data_ohlcv` | 12 GB | yes, 256/258 | none (unique index `market_data_ohlcv_pkey_idx` on (timestamp, symbol, timeframe)) | ~674M |
| `market_regimes` | 1,806 MB | no | (regime_group, tf, ts) | |
| `construction_spreads` | 133 MB | yes, 1,047/1,047 | (construction_name, tf, bar_ts) | 130,625 |

Alpha tables with 0 rows (`alpha_ensemble_ic`, `alpha_frames`) mean their numbers live only in
docs and phase reports, not tables (cards must cite docs).

**The 11 tables without a PK:** `alpha_multiplier_shadow`, `ctx_events`, `dlq_events`,
`drift_monitor`, `feature_ic_scores_history`, `integrity_monitor`, `market_data_ohlcv`,
`service_health_events`, `signal_lineage`, `signal_transform_log`, `transform_graduation`. All are
hypertables except `transform_graduation`. Dispositions: drop with the sweep
`feature_ic_scores_history`, `ctx_events`; v2.x and empty (0 rows) `alpha_multiplier_shadow`,
`drift_monitor`, `service_health_events`, `signal_lineage`, `signal_transform_log`,
`transform_graduation` are drop candidates after the D-08 grep (the ring of archived v2.x code
still names them; check `src/persistence/` and `services/*auditor*`); `dlq_events` and
`integrity_monitor` are live and already carry unique indexes (`dlq_events_dedup_idx`,
`integrity_monitor_idempotency_uq` over a COALESCE expression, which cannot become a PK);
`market_data_ohlcv` has a unique index on (timestamp, symbol, timeframe), all NOT NULL.

**Duplicate indexes (D-36):**
- `market_regimes_pkey` UNIQUE btree (regime_group, tf, ts), 400 MB, idx_scan 0; `market_regimes_regime_group_tf_ts` btree (regime_group, tf, ts), 387 MB, idx_scan 31,851,960. Drop the non-PK one (`DROP INDEX CONCURRENTLY`, plain table); the planner switches to the PK. Before dropping, confirm with `EXPLAIN` on ic_engine's regime-timestamp prefetch.
- `construction_spreads_pkey` (construction_name, tf, bar_ts) and `construction_spreads_name_tf_idx` (construction_name, tf, bar_ts DESC) are redundant (btree scans backward); 8.6 MB each across chunks. Moot if the table is dropped (recommended above).

**PK on compressed hypertables (D-37).** TimescaleDB requires any unique index to include the
partition column (verified, `src/indexing.c`). Whether `ADD CONSTRAINT ... PRIMARY KEY USING INDEX`
works on a compressed hypertable was not verified; [ASSUMED] it is not supported on hypertables.
Recommendation: treat a unique index over NOT NULL key columns that includes the time column as
satisfying D-37 for `market_data_ohlcv` and record it, rather than decompressing 674M rows.

**Direct-compress COPY constraint.** TimescaleDB 2.24+ `SET timescaledb.enable_direct_compress_copy = on`
loads straight into columnstore, and its docs' example drops the PK "to allow direct compress
during COPY" [CITED: github.com/timescale/timescaledb docs/getting-started/events-uuidv7]. D-37
requires PKs. Use COPY into rowstore chunks in time order, then `compress_chunk()` per completed
chunk, which keeps the PK; do not use direct compress on tables with a PK.

## feature_ic_scores anatomy (D-15, D-17, D-19..D-21)

Row classes (all `training_window_end = 2025-12-24 05:15:00+00`, equal to `oos_start`):

| is_pooled | symbol | regime_scope | Rows | Meaning |
|---|---|---|---|---|
| f | per symbol | cross_sectional | 5,540,805 | per-symbol x market_regimes label |
| f | per symbol | earnings_season | 2,188,440 | per-symbol x season |
| f | per symbol | symbol_hmm | 1,585,494 | per-symbol x own HMM label |
| t | per symbol | pooled | 971,073 | per-symbol time-series IC, regime `_pooled` |
| t | POOLED | earnings_season | 210,600 | cross-sectional x season (62 labels) |
| t | POOLED | cross_sectional | 119,680 | cross-sectional x 31 market_regimes labels |

"Old grid" under D-15 = the 9,314,739 `is_pooled = false` rows. The 971,073 per-symbol pooled
rows are cited by the research ledger (section 5 disclosures, `regime_scope = 'pooled'`) and the
330,280 POOLED rows are read by `feature_lifecycle`; keep both until D-35 (recommendation).
Uniqueness today is three partial unique indexes plus a PK that omits `regime_scope` (todo 391:
scope encoded in the `regime` string). Stored lookaheads: 5m {6,12,39}, 15m {2,5,10}, 1h
{1,2,20,60}, 1d {1,2,5,10}.

**How a stored POOLED cell is computed** (`services/ic_engine.py`): `_compute_cross_sectional_tf`
(4634) fetches `feature_vectors JOIN forward_returns` (`return_type = 'executable_open_to_open'`,
chunk SQL at 4902-4915) for the regime_group's peer symbols at the bars carrying that regime
label, ordered by (bar_ts, symbol); `_compute_one_cross_sectional_cell` (3836) subsamples rows
`X_raw[0:n:scale_stride]` with `scale_stride = max(alpha.ic.subsample_min_stride = 5, lookahead)`
over the flattened (bar_ts, symbol) order, masks incomplete/non-finite targets, and
`_subsample_and_rank` (2062) takes `rankdata(axis=0)` over the whole pooled sample: a pooled
Spearman, not a per-date cross-sectional IC. Broadcast features go to
`_compute_one_broadcast_cell` (4156) against the peer-group mean return. CIs come from a circular
block bootstrap with a shared RNG. Bound: `bar_ts <= training_window_end`, so the last bars'
targets reach past `oos_start` (design 11, todo 439).

**No unstratified stored cell exists**, so D-21 as written has no direct target. There is no
stored `regime_volatility`-stratified IC either (`regime_volatility` is a `feature_vectors`
column; ic_engine never references it).

**Recommended parity design (D-21):** a parity harness (test-scoped script, not the proposer's
production path) that, for a stated sample (for example 30 features x 4 tf x each in-session
horizon x 3 regime labels, stated before running), rebuilds each stored cell's observation set
(regime label bars, symbol_list from `symbol_regime_class`, (bar_ts, symbol) order, stride),
computes the point IC (`ic_value` only; CIs are RNG-dependent) with the fresh engine's IC
function, twice: (a) with the table's targets, which must reproduce stored `ic_value` to float
tolerance (proves no statistic drift), and (b) with kernel targets, where differences are
disclosed with counts of gap rows and of end-of-window rows the kernel leaves NaN because S0
refuses `end_exclusive > oos_start`. Horizons crossing a session (1h 20 and 60) have no kernel
counterpart and are excluded with a count. Then the proposer's unstratified pooled cell is a new
statistic justified by (a) and (b). Order: parity, then the D-19 purge, then D-22.

**The kernel** (`src/intelligence/research/panel.py`, read only): `forward_returns(opens,
horizon=1, session=None, closes=None)` returns `ln(open[t+1+h]/open[t+1])`, NaN across sessions
when `session` is given, NaN for the last `1+h` rows; `fwd_span(h) = 1+h`. Panels:
`snapshot.build_panel(dsn, out_dir, symbols=, tf=, start=, end_exclusive=, dividends=)` reads
`market_data_ohlcv_tradeable`, refuses `end_exclusive` past `oos_start`, writes a content-hashed
directory; `build_grid(bars, tf)` is the pure grid step; `Panel.session` gives session indices.
So D-19 holds by construction for kernel targets when `end_exclusive = oos_start`.

**code_content_key.** `_checkpoint_content_key` (5361) hashes AST-normalized source of every
first-party module in `sys.modules` and explicitly imports `services.backfill_feature_factory` and
`services.regime_writer`. Any edit to feature_factory, regime_writer, `_batch_utils`, ic_math,
config or observability moves it. Resumability is `ic_cell_fingerprints`; no .pkl checkpoints
remain.

## Bulk-load primitive (D-24)

Existing in `services/_batch_utils.py` (1,369 lines): `bulk_update_by_key` (COPY into temp table
+ one JOIN-UPDATE, float32 clamp from `col_types`, refuses compressed tables outside a write
session), `compressed_hypertable_write_session` (sync and async; decompress-all unless
`decompress=False`; headroom guard `check_decompress_headroom` from todo 426 step 1, APR
`infra.compressed_hypertable_write_session.{disk_path,min_free_after_fraction}` default 10%),
`make_worker_pool`, `Float32ChunkAccumulator`, APR helpers. Row-at-a-time/`executemany` writers
today: `backfill_feature_factory._batch_insert`, `store_bars()` (manual multi-row VALUES),
ic_engine writers, `forward_return_writer`. Existing lineage-ish tables: `batch_job_checkpoints`
(0 rows), `ic_cell_fingerprints`, `backfill_status` (per (symbol, tf) status). No provenance
table exists.

The new primitive needs: a provenance table (for example `lineage_batch`: writer, target table,
per-kernel code key, APR snapshot hash plus the JSON of values, input content digest, symbol set
hash or list, tf, range start/end, row count, status, started/finished), with a unique key on
(writer, target, code key, APR hash, input digest, tf, range, symbols hash) as the idempotency
key; a load function that COPYs rows (psycopg `cursor.copy` binary or CSV, float32 clamp reused)
into a staging temp table then `INSERT ... SELECT` in `bar_ts` order into the target (or straight
COPY for append-only targets with no conflict possible); `compress_chunk()` on each chunk whose
range is fully covered by completed batch records; and refusal to write to a table whose
compression policy job is active over the target range. Tunables (`infra.bulk_load.*`: batch rows,
statement timeout, compress-after behavior) seeded by migration. Todos 301/343/352 bodies were
truncated in commit 75982e7e0; their originals are recoverable with `git show 75982e7e0^:<path>`.

## feature_factory and the batch path (D-25..D-28)

`src/intelligence/feature_factory.py` (8,733 lines, 236 top-level defs). Groupings visible in
source order: config (`FeatureFactoryConfig`, 424); price-bar primitives and per-bar helpers
(907-2045); calendar and session (1274-1352, 1981-2030, 3314-3420); oscillators (2045-2132);
`*_series_full` vectorized batch series (2154-3300, price dynamics, volume/flow, volatility);
`_PrecomputedSeries` (3450) and `_precompute_series` (3558); VP (3893-4037); S/R (4037-4214);
swing/trend/fib (4214-4830); SMC order blocks, FVG, sweeps, pools, zones, BOS/CHoCH, AMD
(4938-5960); session levels (5960); `_build_feature_vector` (6101) and `FeatureFactory.compute`
(6802, live per-bar) and `compute_batch` (7347, batch); `_cold_start_vector` (8343). Cross-asset,
factor betas, CTF, VP/SR and cross-tf divergences are injected by
`services/backfill_feature_factory._compute_symbol_tf` (1451), not the factory. Importers:
`feature_cache.py`, `features/cross_asset_series.py`, `feature_vector_pipeline.py`,
`feature_vector_writer.py`, `backfill_feature_factory.py`, `ops_ctf_columns_recompute_15m.py`;
20 test files. Existing parity scaffolding: `tests/unit/intelligence/test_feature_factory_batch_parity.py`
(29 tests, streaming vs batch at 1e-8), `test_feature_factory_batch.py` (42),
`test_feature_factory.py` (88). No kernel registry exists. `feature_vector_persistence.py` lives at
`src/intelligence/features/feature_vector_persistence.py` (927 lines), not `services/` as D-28 says.

Byte-identical float32 parity is feasible: `feature_vectors` stores `real` (311 of 322 columns),
the batch path is deterministic given bars and config (canary features use a seeded RNG keyed by
bar_ts and symbol), so a before/after run of `compute_batch` on fixture bars and on a sampled
set of real (symbol, tf) histories compared with `np.array_equal` after float32 cast is the
check. Columns all-NULL in every chunk per `pg_stats` (sampled statistics, verify before
dropping): `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` (todo 421),
`asian_session_high_dist_atr`, `asian_session_low_dist_atr`, `regime_rolling`. Exact duplicate:
`days_to_month_end = 1 - month_position` (todo 115).

**Resumability of the current batch path (D-32a c).** Units are whole-history (symbol, tf)
pairs. A pair is skipped when `backfill_status.status = 'complete'` and the actual
`feature_vectors` row count is within the coverage threshold of `rows_written` (todo 316 fix);
`--refresh` ignores both and overwrites with `ON CONFLICT DO UPDATE`. Each cell's rows and its
`_MARK_COMPUTE_COMPLETE_SQL` commit together; a failed cell is marked failed and the pool
continues (todo 318). Not resumable in the D-32a sense: no time-range unit, no provenance, the
checkpoint is a side table rather than the output, workers return one symbol's full 4-tf row list
across IPC (todo 339: about 191k rows per symbol held in memory), and writes go in place to the
live table.

## regime_writer (D-29) and the bundle todos

`services/regime_writer.py` (2,640 lines) reads only `market_data_ohlcv_tradeable`
(`_fetch_obs_matrix` 1431, `_fetch_obs_matrix_volatility` 1502) and bulk-UPDATEs
`feature_vectors` regime columns through `bulk_update_by_key` inside
`compressed_hypertable_write_session`. Dispatch (2111-2175): volatility family walk-forward;
trend family `_compute_symbol_tf_walk_forward` when `alpha.hmm.walk_forward.enabled`, else the
full-history `_compute_symbol_tf` (1568). The flag is `true` since 2026-08-12 18:20 UTC
(`config_history`: "Flipped alongside the post-231-symbol-expansion full corpus recompute"), and
corpus regime steps ran 2026-08-12 (9.7 h) and 2026-08-15 (10.2 h trend + 3.8 h volatility) after
it. SPY coverage is sparse (1d 1,260 of 4,834 rows labeled), consistent with walk-forward warmup
and skipped segments. STATE.md and memory say 248 is not deployed; reconcile before planning
D-29 (MEDIUM confidence: the step-2 logs are gone).

Two hard facts for the plan. (1) Today regime_writer cannot write at all: its UPDATE path needs
the decompress-all session on `feature_vectors`, which the 426 guard refuses (491 GB against
496 GB free minus the 10% reserve). (2) Because it is a pure function of bars, the HMM is a
natural "regime" origin kernel in the D-25 registry, computed in the rebuild pass and written
append-only. That removes the UPDATE writer entirely and satisfies D-34's append-only rule.

Todo status: 248 pending (fix built, flag on, see above); 286 pending (vol_of_vol nested warmup
`valid_start`); 289 pending (1d `regime_volatility` sparse, `refit_every_bars.1d = 252` never
re-validated against 250-bar windows); 290 body truncated by commit 75982e7e0 (original: 790 MB
per `_rolling` std at window 250 per worker, per-cell count(*) verify query, vocabulary_drift
double scan); 291 body truncated (original: three duplicated function pairs, 20-tuple worker args,
OTel attribute asymmetry); 292 pending (`hmm_vol_churn` rows predate WR-01); 341 pending (BIL,
ETHA, IBIT 100% NULL `regime`; nightly auditor fails on 5 symbols); 420 body truncated by
438872b97 (original: 1,223,265 weekend orphan rows in `market_regimes` for equity and rates;
make the writer replace per (group, tf) atomically). 421 body also truncated by 438872b97.
Recommended: restore the seven truncated todo bodies (290, 291, 301, 343, 352, 420, 421) from
git in the first plan.

## Feature lifecycle (D-30) and phase 170 (D-31)

`feature_lifecycle` (924 lines) implements material-fail flags, regime-shift stratum guards and
demotion hysteresis over POOLED IC cells joined to `ensemble_weights`. Under D-30 all of that goes;
the data-quality replacement needs, per feature per tf: computed (non-NULL share), valid (finite,
in declared dtype range), coverage above an APR floor. Todo 421's coverage check and todo 435's
S0 floor are the same statistic; define it once.

Phase 170 plans 07 and 08 are in `.planning/milestones/v3.1-phases/170-*/`. Plan 07 executed
(readers repointed). Plan 08's gate aborted on 2026-08-04, then the retirement shipped anyway as
migration `311_retire_feature_registry.sql` (commit 54f346ba9, 2026-08-10, "remove
feature_registry dual write, delete FeatureRegistryService"). Both `feature_registry` and
`feature_transition_log` are absent from the database and `feature_registry_service.py` is gone.
Residue: `scripts/ops/alpha/ops_concept_feature_migration_verify.py` (queries the dropped table),
comments in `schemas.py:1535`, `ops_ic_shrinkage.py:116`, `ensemble_trainer.py:463`. D-31 is a
small cleanup task, not a plan; the ROADMAP and design 14.3 are stale on this.

## Todo 445 (D-33)

The phase 183 runner has real and synthetic modes only (`runner.py:453`); `research_run.mode`
has `CHECK (mode = 'real')`, kinds `evidence`/`book_test`, FK to `concept_registry`, and guard
triggers; S0 reads bars only (`snapshot._BARS_SQL`), never `feature_vectors`. So "through the
research runner in exploration mode" is not runnable now, and adding exploration mode is a
research-package change (D-02) or phase 187 (design 7.2). Options: (a) wait for the research
lane to add exploration mode and a `feature_vectors` reader; (b) run 445 now as a committed
script in `scripts/research/`, in-sample only (`bar_ts < oos_start`), targets from
`panel.forward_returns` on an S0 15m panel, recorded as a summary-card-shaped record and a ledger
section 5 entry, with a note that phase 187 imports it as an exploration attempt. Recommend (b):
the decision gates the most expensive recompute, and the result is scoping disclosure, not a
verdict. This deviates from D-33's wording; the coordinator should confirm. Pitfalls for the test:
5m-at-15m-close alignment (a 5m row whose bar ends at the 15m close, not the 5m bar starting at
the 15m bar_ts; the N1 cross-timeframe join leak class), exclude regime/HMM columns and todo 421's
partial velocity columns, never load 300 columns x 101M rows at once (select per feature block
and symbol chunk).

## Bar coverage (D-32, owner update)

Measured 2026-09-26 on `market_data_ohlcv_tradeable` (7 s grouped query):

| Group | tf | Symbols with bars | Tradeable rows | Median first bar | p90 first bar | Last bar |
|---|---|---|---|---|---|---|
| 233 `compute_eligible` | 5m | 233 | 75,682,143 | 2006-07-07 | 2016-02-04 | 2026-09-25 |
| | 15m | 233 | 25,915,122 | 2006-08-08 | 2016-02-04 | 2026-09-25 |
| | 1h | 233 | 7,081,546 | 2006-05-05 | 2016-02-04 | 2026-09-25 |
| | 1d | 233 | 1,032,561 | 2006-08-11 | 2016-02-03 | 2026-09-23/24 |
| 698 `compute_eligible_1d` only | 5m | 0 | 0 | | | |
| | 15m | 11 (backfill running) | 856,304 | | | |
| | 1h | 15 (backfill running) | 335,878 | | | |
| | 1d | 698 | 2,829,157 | 2006-10-02 | 2020-03-19 | 2026-09-23/24 |

Eligibility: 932 active, 931 `compute_eligible_1d`, 233 `compute_eligible`, 0 `live_tradeable`.
`ohlcv_empty_history`: 5m 88 rows (74 reached request start), 15m 88, 1h 90, 1d 84; spans
2006-09-29 to 2024-07-23 intraday. `backfill_status` tracks feature compute: 5m 233 complete
(75,051,415 rows), 1d 233 complete and 699 pending, 1m 231 pending. Owners of the gaps: todo 449
(5m for the 698), phase 185 D2b (derived 15m/1h), 185 D3 (venue-move recovery, not a
precondition). Raw 5m grid is 5.35x tradeable (SPY 2,126,971 raw vs 397,554 tradeable).

## Estimates (inputs stated; all are estimates)

**5m backfill for 698 names (todo 449).** Inputs: `infra.ibkr.chunk_days.5m = 150`; depth 7,300
days, so at most 49 requests per full-depth name; sum of the 698 names' 1d history spans =
11,333 symbol-years (upper bound for intraday depth, since SMART intraday starts at a venue move)
-> about 27,600 requests. Pacing: `infra.ibkr.rate_limit_max_requests = 58` per 600 s per process
(IBKR's hard limit binds bars of 30 s or less; for 1 min and above only a soft slowdown applies,
migration 375). Observed today on the 1h/15m lanes: about 20-25 successful requests per lane-hour
with frequent 90 s timeouts, Error 162 cancels and one socket disconnect (lane logs: 14
symbol-tf fetches in the first 56 minutes across 4 lanes).
- Limiter-bound, 4 lanes: about 20 hours.
- Limiter-bound, 1 lane: about 80 hours.
- At today's observed rate, 4 lanes: about 13 days.
Measure a 10-name pilot (todo 449 requires it) before stating the plan's figure; request count
per name falls with later first bars.

**Rows and disk at 931 names.** Inputs: per symbol-year from the 233 names (5m 18.4k, 15m 6.3k,
1h 1.72k tradeable rows); 698-name span 11,333 symbol-years (upper bound); `feature_vectors` 820
bytes/row compressed, 4.52 KB/row uncompressed (89 GB, 491 GB, 108.6M rows);
`market_data_ohlcv` about 18 bytes per raw row compressed (12 GB / 674M).

| Item | Without 5m features | With 5m features |
|---|---|---|
| 5m raw bars for 698 names (always fetched) | about 1.2B raw rows, 222M tradeable, about 21 GB compressed | same |
| Rebuilt `feature_vectors` rows | 1d 3.9M + 15m 97M + 1h 27M = about 128M | + 5m 284M = about 412M |
| Compressed size | about 105 GB | about 338 GB |
| Uncompressed size | about 578 GB | about 1.86 TB |
| "4x the table" guard vs 496 GB free (minus 91 GB reserve) | 420 GB: fails today by about 15 GB, passes after the D-14/D-22 drops free about 61 GB | 1.35 TB: never fits |

So the drops must land before the rebuild, and 5m features at 931 names are infeasible under the
D-32 guard regardless of todo 445's answer unless the guard is redefined per chunk (peak is one
uncompressed 90-day chunk plus compressed totals, which is far smaller). The new schema drops
at least 7 columns, a small reduction.

**Rebuild wall-clock at 931 names.** Inputs: the 2026-08-12 corpus `feature_factory` step took
16,432 s at `infra.feature_factory.workers = 12` for about 151 names (the todo 316 desync skipped
about 80), about 4,300 rows/s including the executemany write; regime steps at 233 names took
9.7-10.2 h (trend, walk-forward) plus 3.8 h (volatility), about 2,200 rows/s. Linear scaling:
features about 8 h without 5m, about 27 h with 5m; HMM about 16 h without 5m, about 51 h with
5m; plus compression per chunk and COPY (COPY should beat executemany; todo 301 measured 2x for
VALUES batching). Total about 1 to 1.5 days without 5m, 3.5 to 4 days with 5m, before
time-range unit overhead (below). D-32a's measured pilot chunk replaces these numbers.

**Unit design consequence.** (symbol chunk, tf, time range) units recompute each unit's warmup:
declared memory up to 504 + 252 bars (1d `price_vol_corr_slow` plus z-score) means a 90-day range
on 1h carries about 108 sessions of warmup per 63 sessions of output (about 170% overhead), 15m
about 46%, 1d several years per quarter. Recommend a longer chunk interval for the new table (for
example 1 year: 15m about 5%, 1h about 43%) and 1d as one range per symbol chunk (1d is 3.9M
rows). The registry's declared memory (D-26) sets the warmup, and the causality probe (D-27) is
the test that the warmup is enough.

## Database settings (D-38)

Running: `shared_buffers` 3 GB (command line), `work_mem` 8 MB (command line),
`maintenance_work_mem` 2 GB, `effective_cache_size` 17 GB, `max_wal_size` 16 GB,
`max_parallel_workers` 24, `idle_in_transaction_session_timeout` 1 h (database level), buffer hit
98.86%, 46,224 temp files totaling 1,011 GB since stats reset (spills: the work_mem evidence).
Drift: `production/docker-compose.yml` says `work_mem=64MB` but the running container's command
has `work_mem=8MB`, so the container was not recreated after the compose edit. `shm_size: 512m`
limits dynamic shared memory for parallel hash joins if work_mem rises [ASSUMED: Postgres
`dynamic_shared_memory_type = posix` uses /dev/shm]. A second Postgres (`ssfi-timescaledb`)
shares the host's 29 GB. Settings change via compose command args, then `docker compose up -d`
(restart), only with no batch job running.

## Summary card sources (D-04..D-06)

**18 ledger verdicts** (`docs/research/construction-verdict-ledger.md` section 4, lines 104-122):
`jump_diffusion_decomposition`, `cointegrated_pairs_residual`, `retail_immediacy_provision`,
`dealer_hedging_flow`, `statistical_factor_residual`, todo 303 per-symbol trend regime, todo 304
percentile-rank regimes, todo 281 dominance/confirmation (rejected as HMM axes), N1
`nonlinear_interaction_combiner` (inconclusive), `range_pct_fast_xs_ls_h5`, phase 148
`alpha_score_directional` (killed on paper), `bars_since_high_fast_xs_ls_h5`,
`alpha_score_residual_single_security_15m`, `range_pct_fast_xs_ls_h5_single_name_only`, H-A
`extreme_volume_divergence`, H-B `confirmed_reversal`, `tsmom_sleeve`, phase 179 sleeve
walk-forward. Each row cites its doc, pre-registration or memory; concept_registry migrations
328-335 hold several verdict metadata blobs (script paths, dates).

**Old-chain processes** (additional cards): phase 142A ensemble IC (EIC-04/05 gates,
`ops_ensemble_ic_gate.py`, `alpha_ensemble_ic` empty); phase 142B frames and counterfactual
FRAME-04 (`alpha_frames` empty); phase 148 SCORE-01/02/03 (`alpha_strategy_scores` 120 rows,
`score03_gate2_execution_eval.py`); gate166 frame recalibration (gate_look_log
`gate166_baseline`, `gate166_scalar`, 2026-07-23; `.planning/milestones/v3.1-phases/166-*`);
`gate1_signal` (2026-07-22) and an unnamed 2026-07-23 look; `ctf_momentum` decile LS gates 1-2 and
the ctf_join_v2 re-verification (gate_look_log 2026-08-04, 2026-08-07; phase 167; 
`construction_spreads`); EM-CAL emission threshold
(`docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md`,
`measurement-alpha-emission.md`); the ensemble champion itself (`ensemble_weights` version
`run_2025122405150000`, 358 rows; `.planning/corpus_manifests/ensemble_trainer__*.json`;
`logs/corpus_pipeline/step_timings.jsonl`); phase 179 is already a ledger row. Table-only
caches with no conclusion (`context_features`, `feature_ic_scores_history`, ctx tables) get one
"dead cache" card each so D-06's coverage check passes. Total about 26.

**Card front matter (proposed):**

```yaml
---
card_id: legacy-2026-09-02-range-pct-fast-xs-ls-h5   # kebab, unique, stable
kind: legacy_verdict                                  # or dead_cache
title: range_pct_fast cross-sectional long-short, h5
verdict: DEAD                                          # DEAD|FAIL|INCONCLUSIVE|KILLED_ON_PAPER|REJECTED_AS_AXIS|NO_CONCLUSION
verdict_date: 2026-09-02
idea: one sentence
recipe:
  spec: docs/plans/...prereg.md                      # or null
  script: scripts/analysis/....py                    # path at recipe_commit
  recipe_commit: <40-hex>
results:                                               # numbers copied, never re-scored
  - {name: shuffled_null_p, value: 0.001, source: docs/research/...md#L113}
known_defects: [ ... ]
spans_looked_at: [{start: 2006-07-07, end: 2025-12-24, role: in_sample}]
forward_span_looks: 0                                  # from gate_look_log
tables: [ensemble_alpha, alpha_events]                 # D-06 coverage key
status_now: closed                                     # closed|reopened
reopened_as: null                                      # ledger section 2 pointer
reproducible: false
sources: [docs/..., .planning/gate_look_log.jsonl#gate1_ctf_momentum_decile_ls]
---
```

Card lint test (`tests/unit/test_summary_cards.py`): required keys and types, `reproducible` is
false, commit is 40-hex and exists in git (`git cat-file -e`, skipped if not a repo), every path
in `recipe`/`sources` exists at `recipe_commit` or HEAD, and a `DROP_TABLES` constant (the D-14
list plus ctx tables and `construction_spreads`) is fully covered by the union of `tables`.

## Architecture patterns

### System diagram (target after the phase)

```
IBKR -> market_data_ohlcv (raw, permanent) --tradeable view--> S0 panel (content-hashed)
                                     |                              |
                                     v                              v
        feature kernel registry (per-origin modules, pure)   panel.forward_returns (kernel)
        incl. regime (walk-forward HMM) kernel                      |
                     |                                              |
      rebuild writer (units: symbol chunk x tf x range)             |
                     | COPY in time order, compress per chunk       |
                     v                                              v
       feature_vectors (new, append-only)  -->  IC jobs: proposer | term structure | monitoring
                     |                                    |
         lineage_batch (provenance = idempotency key) <---+  COPY
                                                          v
                                             feature_ic_scores (scope in key)
                                                          |
                                     feature_lifecycle (data-quality only) -> concept_evaluation
```

### Recommended structure

```
src/intelligence/features/
  registry.py            # Kernel(name, inputs, memory_bars, dtype, compute); lookup, versions
  kernels/price.py volume.py smc.py vp_sr.py calendar.py macro.py regime.py
  causality_probe.py     # D-27
src/intelligence/measure/ (or similar, planner picks)
  proposer.py term_structure.py monitoring.py   # pure over ic_math
services/ic_measure.py   # the one writer during the strangler; renamed on D-22
services/_batch_utils.py # + bulk_load(), lineage record helpers
scripts/research/determinism/  # promoted repro_frozen and its minimal deps
docs/research/summary-cards/*.md
```

### Anti-patterns to avoid
- UPDATE into the rebuilt `feature_vectors` (regime or any late column): write regime in the same pass.
- A per-row provenance column on a compressed hypertable (design 12.1, the 768 GB class).
- Moving `repro_frozen.py` with its imports intact (drags ic_engine and ensemble_trainer along).
- Deleting `src/intelligence/ensemble/` wholesale.
- Using direct-compress COPY on a table with a PK.
- Hashing all imports for the new engine's code key (D-23 is per kernel).

## Don't hand-roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Forward returns | SQL LEAD or a new target | `panel.forward_returns` | UD-25 single definition |
| Panel grid | Own session grid | `snapshot.build_grid`/`build_panel` | Session anchoring, oos refusal |
| Rank IC, BH-FDR, HAC Sharpe, bootstrap | New stats | `ic_math.py` (`compute_ic_vectorized`, `apply_bh_fdr`, `_circular_block_bootstrap_ic`, `_compute_ic_rolling_metrics`) | Tested; parity depends on identical math |
| Float32 clamp in COPY | New clamp | `_clamp_to_real_range` via `col_types` | Todo 312 |
| Disk headroom | New guard | `check_decompress_headroom` | Todo 426 |
| Worker pools | Raw ProcessPoolExecutor | `make_worker_pool` | BLAS threads, forkserver |
| Chunk compression | Background policy | `compress_chunk()` per completed chunk, policy disabled during build | Deterministic, measurable |

## Runtime state inventory

| Category | Items found | Action |
|---|---|---|
| Stored data | Tables in D-14 plus ctx tables, `construction_spreads`, `alpha_strategy_scores`; `feature_ic_scores` old-grid rows; `concept_registry` 5 `ensemble_strategy` rows and IC-gate `concept_evaluation` rows (design 10.2: dropped in phase 187, not here); `backfill_status` rows reused by the rebuild | Migrations (drop, delete rows), commit with apply |
| Live service config | `indicagent-ctx-writer.service` enabled and running; Kafka topic `<env>.ctx.snapshot` and alpha events topic exist in Redpanda | Stop/disable unit; topic deletion optional (transport only) |
| OS-registered state | `/etc/systemd/system/indicagent-ctx-writer.service` (root-owned); no other old-chain unit installed; timers: nightly-backfill, regime-coverage-auditor (fails nightly, todo 341), dividend writer | `sudo systemctl disable --now`, remove file, daemon-reload |
| Secrets/env vars | None reference the deleted names (checked: settings use `INDICAGENT_ENV` prefixes only) | None |
| Build artifacts | `__pycache__` in `scripts/analysis/`, `scripts/ops/alpha/`; `.planning/corpus_manifests/*` for deleted steps | Delete dirs with the code; manifests stay as records |
| APR | `alpha.ensemble.*` 22, `alpha.ensemble_ic.*` 9, `alpha.frame.*` 120, `alpha.publisher.*` 1, `alpha.scoring.*` 7, `alpha.decay.*` 10, `alpha.ic.lookahead.*` 20, `alpha.forward_returns.*` 2 | Delete per key after grep: `alpha.ensemble.mv_condition_max` is read by `services/tag_calibrator.py:1254` (live) and pinned in frozen snapshot APR dicts; `alpha.ic.shrinkage_k` likewise; `alpha.ic.canary_rng_seed` read by backfill_feature_factory |

## Common pitfalls

1. **Dirty working tree blocks the research lane.** `research/provenance.py` refuses a real run
   if any loaded first-party file under src/, services/ or scripts/research/ is modified, staged
   or untracked. Phase 186 must work in a git worktree (symlink `.env`, venv PATH for hooks), never
   in the shared main checkout.
2. **Frozen pickles pin class paths.** See the pickle finding; also check any other pickle under
   `logs/phase17*`/`logs/phase18*` before deleting a module (`grep -ao` for module paths).
3. **`ensemble/__init__.py` eager imports.** Deleting `alpha_score.py` without editing
   `__init__` breaks the research package's import of `weighting`.
4. **Lifecycle before drop.** `feature_lifecycle` joins `ensemble_weights`; drop order matters.
5. **Purge before parity empties the target.** Every stored cell ends at `oos_start`; parity first.
6. **regime_writer is refused today.** Any plan that runs it in place hits the 426 guard; do not
   loosen the guard.
7. **Migration number collisions.** Latest is 379; phase 185 writes migrations concurrently.
   Check `ls production/migrations | sort -V | tail` immediately before numbering.
8. **Truncated todos.** 290, 291, 301, 343, 352, 420, 421 lost their bodies in commits 75982e7e0
   and 438872b97; plans citing them must read `git show <commit>^:<path>`.
9. **Stale planning facts.** STATE.md/memory on todo 248 deployment and ROADMAP/design on phase 170
   plans 07-08 are out of date; CONTEXT D-07's `context_writer`/`context_features` pairing is wrong.
10. **Orphaned workers on kill.** Batch services use forkserver pools; reap workers and terminate
    leftover backends (CLAUDE.md) before resuming the rebuild.
11. **Concurrent backfill load.** 4 IBKR lanes are writing `market_data_ohlcv` now; the coverage
    precondition query and the rebuild pilot must note concurrent load (D-32a).
12. **`feature_vector_persistence.py` path.** It is under `src/intelligence/features/`.
13. **Allow-lists.** Deleting a file listed in `test_market_data_ohlcv_boundary.py` or
    `test_compressed_hypertable_write_boundary.py` allow-lists fails `assert_allow_list_has_no_stale_entries`;
    edit the list in the same commit (`test_compressed_hypertable_write_boundary.py` names
    `ops_interaction_primitives_pilot.py`, which goes with D-22).

## State of the art

| Old approach | Current approach | When | Impact |
|---|---|---|---|
| `forward_returns` table via LEAD over traded rows | `panel.forward_returns` on S0 grid | UD-25, 2026-09-26 | Fixed horizon, no cross-session intraday |
| Refresh `feature_vectors` in place (decompress-all) | Rebuild append-only, compress per chunk | Design 14.2 | Avoids the 491 GB decompress |
| executemany / VALUES batching | COPY in chunk order | Design 14.5 | 107M/66M/18M call counts go |
| Compress by background policy | `compress_chunk()` when a chunk completes; direct-compress COPY exists in TimescaleDB 2.24+ but needs no PK | TimescaleDB 2.24+ | Use chunk-level compress with PK |

## Assumptions log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | `ADD PRIMARY KEY USING INDEX` is not supported on compressed hypertables | Tables | D-37 treatment of `market_data_ohlcv`; test on a scratch hypertable first |
| A2 | `/dev/shm` 512 MB limits parallel hash with higher work_mem | D-38 | Raise `shm_size` with work_mem |
| A3 | The 2026-08-12 feature step computed about 151 names | Estimates | Rebuild time off by up to 1.5x |
| A4 | Rebuild rows scale with 1d span for the 698 names | Estimates | Upper bound; real intraday spans shorter |
| A5 | The Aug 12/15 regime runs used walk-forward | regime_writer | Changes whether 248 is "deployed" |
| A6 | IBKR soft slowdown dominates 5m pacing | Estimates | 5m backfill between 20 h and 13 days |
| A7 | `pg_stats` null_frac 1 means never computed | feature_factory | Verify with a sampled count before dropping columns |

## Open questions

All six were resolved during discuss-phase (R-01..R-13 in CONTEXT.md) and are closed by the
written plans; markers below record the resolution.

1. **D-33 path for todo 445.** (RESOLVED, R-08) A committed counted script in `scripts/research/`
   (option b), plan 186-07; no research-runner edit, no external gate.
2. **5m features at 931 names.** (RESOLVED, R-09 + 186-07) 5m stays at 233 names unless the
   186-07 decision says otherwise; the disk guard is R-09, enforced by the 186-26 precondition
   checker on measured pilot numbers.
3. **Which feature_ic_scores rows are "pooled" under D-15.** (RESOLVED, R-07) 186-20 deletes the
   ~9.3M `is_pooled = false` rows; POOLED and per-symbol `_pooled` rows stay until 186-28
   replaces them (D-35).
4. **Todo 248 status.** (RESOLVED, R-10) 186-13 task 1 verifies the real flag state against
   `config_history` and corrects STATE.md and the memory entry.
5. **The running 1h/15m backfill of the 698 names.** (RESOLVED, observational) Became todo 449
   (filed during planning, running in its own session); 186-26 gates on its 5m completeness
   read-only (R-13) and phase 185 D2b owns the derived grid.
6. **market_regimes future.** (RESOLVED) Keep the table, drop the duplicate index (D-36, 186-05);
   the feature-source question stays with todo 435, untouched by phase 186.

## Recommended plan decomposition

Autonomous now unless marked. Every plan works in a worktree and runs the D-01 `ps aux` check
before editing any module in the `_checkpoint_content_key` closure.

| Wave | Plan | Tasks (2-4) | Depends on | Gate |
|---|---|---|---|---|
| 1 | 01 Planning hygiene and cards schema | restore 7 truncated todos; correct STATE (248 flag, phase 170 done, ctx facts); card schema + lint test | - | none |
| 1 | 02 Summary cards | 18 ledger cards; about 8 old-chain and dead-cache cards; D-06 coverage passes | 01 | none |
| 1 | 03 ctx retirement | stop/disable unit (sudo); delete context_writer, test, auditor entries, unit file; drop ctx tables (migration) | 02 for the drop | none |
| 1 | 04 DB measurement | D-38 baseline (pg_stat_statements, temp spills, `iostat`, buffer hit); drop `market_regimes` duplicate index (CONCURRENTLY); PK inventory decisions for the 11 | - | none |
| 1 | 05 Bulk-load primitive | lineage table migration + APR keys; `bulk_load()` with COPY, chunk compress, idempotency; tests with fakes and an integration test | - | D-01 check |
| 1 | 06 Todo 445 run | script in scripts/research; run in-sample; record decision | coordinator OK on option b | external decision |
| 2 | 07 Old chain deletion | D-09 modules plus alpha_scorer, generate_ic_discovery_report, gate_math, ensemble submodules (with `__init__` rewrite); D-10 scripts plus ops_ic_shrinkage; orchestrator steps 6-8; tests; APR keys per key | 02 | D-01 |
| 2 | 08 Lifecycle shrink | D-30 data-quality lifecycle; remove ensemble joins; D-31 residue cleanup | 02 | D-01 |
| 2 | 09 Chain drops | migrations for ensemble_*, alpha_*, context_features, feature_ic_scores_history, construction_spreads (+ spread tracker deletion), alpha_strategy_scores; commit with apply | 02, 07, 08 | cards checked |
| 2 | 10 Determinism promotion | scripts/research/determinism with remapping unpickler; tests; run bit-identical | - | D-01 (does not edit research package) |
| 2 | 11 Helper promotion | `instrument_compute_eligibility_audit` to scripts/infrastructure; `_date_panel`, cost-band, `fetch_training_matrix` to scripts/research; move tests | 02 | none |
| 3 | 12 Fresh IC jobs | proposer, term structure, monitoring over ic_math; writer on 05 with scope in key; kernel targets via S0 in symbol chunks | 05 | D-01 |
| 3 | 13 Parity and purge | parity harness (sample stated first), disclosure counts; D-19 purge; delete old-grid rows (SOP) | 12 | none |
| 3 | 14 Kernel registry split | registry + per-origin modules; byte-identical float32 parity; causality probe on fixtures | - | D-01 |
| 4 | 15 One-change deletion (D-22) | delete ic_engine, forward_return_writer, forward_returns drop, lookahead keys, table readers, CLAUDE.md rule | 13 | D-01 |
| 4 | 16 scripts/analysis deletion | delete dir after 10, 11 and research-lane switch of HarnessConfig imports | 10, 11, research lane release (D-03) | external |
| 4 | 17 Batch path as rebuild writer | units (symbol chunk, tf, range) on 05 and 14; todo 339 fix; regime as kernel; D-29 walk-forward only, bundle todos | 05, 14 | D-01 |
| 4 | 18 Postgres tuning | shared_buffers/work_mem change and restart with before/after | 04 | no batch job running |
| 5 | 19 Rebuild (gated) | precondition checker (coverage query, 449 done, 185 D2b, 445 decision, 05/14/17 landed, disk guard); pilot chunk timing; full run; drift report; swap; drop old | 15-17, 09 | todo 449, 185 D2b, 445 |
| 5 | 20 Fresh IC on rebuilt features (D-35) | run proposer on rebuilt table; replace pooled rows | 19 | 19 |

## Validation architecture

### Test framework

| Property | Value |
|---|---|
| Framework | pytest 9.0.3 |
| Config | `pytest.ini` |
| Quick run | `.venv/bin/pytest tests/unit/<file> -x -q` |
| Full suite | `.venv/bin/pytest tests/unit/ -q` (6,755 tests) |

### Decision group to test map

| Keys | Behavior | Type | Command | Exists |
|---|---|---|---|---|
| D-04..D-06 | card front matter valid; drop tables covered | unit | `pytest tests/unit/test_summary_cards.py -x` | Wave 0 |
| D-07..D-10 | no import of deleted modules anywhere | unit (collection) | `pytest tests/unit -q --co` then full suite | yes |
| D-11 | repro_frozen bit-identical after promotion; unpickler remap | unit + manual run | `pytest tests/unit/research_tools/test_repro_frozen.py -x`; `python scripts/research/determinism/repro_frozen.py <scratch>` | Wave 0 |
| D-14, D-16 | drop/delete migrations; vacuum rule | unit | `pytest tests/unit/test_compressed_hypertable_migration_vacuum_check.py` | yes |
| D-17..D-20 | proposer, term structure, monitoring pure functions on synthetic panels; scope in unique key | unit | `pytest tests/unit/measure/ -x` | Wave 0 |
| D-19 | no written row has target end >= oos_start | unit + SQL check | fixture test; `SELECT count(*) ... ` post-write | Wave 0 |
| D-21 | parity harness reproduces stored ic_value with table targets; disclosed diffs with kernel | script + unit | `pytest tests/unit/measure/test_parity_harness.py`; harness run log | Wave 0 |
| D-24 | COPY order, per-chunk compress, idempotent rerun no-op, float32 clamp | unit (fakes) + integration | `pytest tests/unit/test_bulk_load.py tests/integration/test_bulk_load.py` | Wave 0 |
| D-25 | byte-identical float32 before/after split | unit | `pytest tests/unit/intelligence/test_kernel_registry_parity.py` plus existing `test_feature_factory_batch_parity.py` | Wave 0 |
| D-27 | causality probe catches an injected lookahead kernel and passes real kernels | unit | `pytest tests/unit/intelligence/test_causality_probe.py` | Wave 0 |
| D-28 | todo 339: bounded worker payload | unit | `pytest tests/unit/services/test_backfill_feature_factory.py` | yes (extend) |
| D-29 | walk-forward only; full-history path absent | unit | `pytest tests/unit -k regime_writer` | yes (extend) |
| D-30 | lifecycle decides from data quality only | unit | `pytest tests/unit/test_feature_lifecycle.py` | yes (rewrite) |
| D-32, D-32a | precondition checker refuses; resume skips completed units | unit + pilot | `pytest tests/unit/test_rebuild_preconditions.py`; pilot log | Wave 0 |
| D-36..D-38 | index/PK state, settings | SQL checks recorded in summaries | psql queries in this doc | manual |

CI boundary tests touched: `test_market_data_ohlcv_boundary.py` (new readers must use the view),
`test_compressed_hypertable_write_boundary.py` (allow-list names deleted files),
`test_compressed_hypertable_migration_vacuum_check.py`, `test_todo_priorities_link_integrity.py`
(every todo closed or moved: 301, 343, 352, 355, 391-related, 411, 412, 421, 426, 439, 445, 448),
`test_span_coverage_compliance.py` (mentions old services by name), `test_ic_engine_active_scales_boundary.py`
and `test_ic_engine_worker_otel_boundary.py` (delete with the old engine), `tests/unit/_source_grep_helpers.py`.

### Sampling rate
- Per task commit: the touched test files plus `pytest tests/unit -q --co` (catches dead imports at collection).
- Per wave merge: full `tests/unit`.
- Phase gate: full suite green, repro_frozen bit-identical, parity report committed.

### Wave 0 gaps
- `tests/unit/test_summary_cards.py`
- `tests/unit/test_bulk_load.py`, `tests/integration/test_bulk_load.py`
- `tests/unit/measure/` (proposer, term structure, monitoring, parity harness)
- `tests/unit/intelligence/test_kernel_registry_parity.py`, `test_causality_probe.py`
- `tests/unit/test_rebuild_preconditions.py`
- promoted `repro_frozen` test with a fixture pickle carrying the old class path

## Security domain

| ASVS category | Applies | Control |
|---|---|---|
| V2 Authentication | no (local, superuser; per-writer roles are phase 187) | - |
| V4 Access control | partly | Destructive migrations only after cards and grep; sudo for unit removal |
| V5 Input validation | yes | Card lint; APR values parsed via ConfigService; SQL identifiers never from caller text |
| V6 Cryptography | no (content digests are integrity, sha256 from hashlib) | hashlib |
| V8 Data protection | yes | Raw data never dropped (D-15); drops committed with apply; disk guards |

| Threat | STRIDE | Mitigation |
|---|---|---|
| Accidental drop of a live table | Tampering | D-08 grep recorded; card coverage test; migration reviewed in the same commit |
| Unpickling artifacts | Tampering | Only local frozen artifacts; remapping unpickler limited to known class paths |
| Disk exhaustion | Denial of service | 426 guard, drops before rebuild, per-chunk compress |
| Forward-span leak via IC targets | Information disclosure (methodology) | Kernel on panels ending at oos_start; D-19 purge; write-once oos_start (todo 439) |

## Sources

### Primary (HIGH)
- Repository at HEAD 9b6cc19d2: files and line numbers cited above.
- Live database (read-only queries 2026-09-26): table sizes, chunks, PKs, indexes, row classes, APR, config_history, pg_settings, coverage.
- `logs/corpus_pipeline/step_timings.jsonl`, `logs/backfill_421_1d_refresh.out`, `logs/backfill_new_universe_intraday_20260926T2306_lane*.log`, frozen pickles under `logs/phase179`, `logs/phase181`.
- Context7 `/timescale/timescaledb`: `enable_direct_compress_copy` (2.24+), no-PK requirement example, unique index must include partition column (`src/indexing.c`), decompress-for-insert with unique constraints (`src/chunk_tuple_routing.c`).

### Secondary (MEDIUM)
- `docs/plans/2026-09-26-unified-research-to-production-design.md` sections 3, 10-12, 14, 16.
- Todos 248, 286, 289, 292, 339, 341, 411, 412, 426, 439, 445, 448, 449 and git-recovered 290, 291, 301, 343, 352, 420, 421.

### Tertiary (LOW)
- Throughput extrapolations (Estimates section).

## Metadata

**Confidence breakdown:**
- Deletion inventory and couplings: HIGH (grep plus import tracing).
- Table and index facts: HIGH (catalog queries).
- Parity design: MEDIUM-HIGH (code read; harness untested).
- Estimates: MEDIUM-LOW (log-derived, inputs stated).
- Todo 248 deployment state: MEDIUM.

**Research date:** 2026-09-26/27
**Valid until:** 2026-10-04 (fast-moving: concurrent backfill, phase 185 migrations, research lane)
